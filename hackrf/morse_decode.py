#!/usr/bin/env python3
"""Coherent-averaging Morse decode. The Pi loops the message; we capture many
repetitions, estimate the repeat period by autocorrelation, fold/average the
envelope over that period (periodic keying reinforces, ambient averages down),
then threshold + decode the clean averaged cycle.
Usage: morse_avg.py [MSG] [unit_ms] [capture_s]"""
import ctypes as C, numpy as np, time, subprocess, sys, os, tempfile

MSG  = sys.argv[1] if len(sys.argv)>1 else "SOS"
UNIT = float(sys.argv[2]) if len(sys.argv)>2 else 150.0
CAP  = float(sys.argv[3]) if len(sys.argv)>3 else 45.0
FS=2_000_000; CENTER=286_000_000; TARGET=286_800_000
LNA=40; VGA=40; AMP=1
IQFILE=os.path.join(tempfile.gettempdir(),"hrf_morse.iq")

# ---- HackRF capture to FILE (old-firmware-safe) ----
lib=C.CDLL("libhackrf.so.0")
class xfer(C.Structure):
    _fields_=[("device",C.c_void_p),("buffer",C.POINTER(C.c_uint8)),("buffer_length",C.c_int),
              ("valid_length",C.c_int),("rx_ctx",C.c_void_p),("tx_ctx",C.c_void_p)]
CB=C.CFUNCTYPE(C.c_int,C.POINTER(xfer))
for n,a in [("hackrf_open",[C.POINTER(C.c_void_p)]),("hackrf_set_sample_rate",[C.c_void_p,C.c_double]),
            ("hackrf_set_freq",[C.c_void_p,C.c_uint64]),("hackrf_set_amp_enable",[C.c_void_p,C.c_uint8]),
            ("hackrf_set_lna_gain",[C.c_void_p,C.c_uint32]),("hackrf_set_vga_gain",[C.c_void_p,C.c_uint32]),
            ("hackrf_start_rx",[C.c_void_p,CB,C.c_void_p]),("hackrf_stop_rx",[C.c_void_p]),("hackrf_close",[C.c_void_p])]:
    getattr(lib,n).argtypes=a
def capture_to_file(secs,path):
    fh=open(path,"wb"); need=int(FS*secs)*2; st={"n":0,"done":False}
    @CB
    def cb(tp):
        if not st["done"]:
            t=tp.contents; b=C.string_at(t.buffer,t.valid_length); fh.write(b); st["n"]+=len(b)
            if st["n"]>=need: st["done"]=True
        return 0
    lib.hackrf_init(); dev=C.c_void_p(); assert lib.hackrf_open(C.byref(dev))==0,"open"
    lib.hackrf_set_sample_rate(dev,float(FS)); lib.hackrf_set_freq(dev,CENTER)
    lib.hackrf_set_amp_enable(dev,AMP); lib.hackrf_set_lna_gain(dev,LNA); lib.hackrf_set_vga_gain(dev,VGA)
    assert lib.hackrf_start_rx(dev,cb,None)==0,"start_rx"
    t0=time.time()
    while not st["done"] and time.time()-t0<secs+6: time.sleep(0.1)
    lib.hackrf_stop_rx(dev); lib.hackrf_close(dev); lib.hackrf_exit(); fh.close()
    return st["n"]//2

def ssh(cmd,bg=False):
    a=["ssh","-o","BatchMode=yes","pi@raspberrypi.local",cmd]
    if bg: return subprocess.Popen(a,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return subprocess.run(a,stdin=subprocess.DEVNULL,timeout=20,capture_output=True,text=True).stdout.strip()

ssh("pkill -9 -x tx_ddr 2>/dev/null; rm -f /tmp/tx_stop")
ssh("cd ~/tempest-ddr && setsid ./tx_ddr --morse %s --unit %d >/tmp/tx.log 2>&1 </dev/null & sleep 1"%(MSG,int(UNIT)),bg=True)
time.sleep(2.0)
assert ssh("pgrep -x tx_ddr >/dev/null && echo YES||echo NO")=="YES","tx failed"
print("tx keying '%s' unit=%.0f ms; capturing %.0fs to disk ..."%(MSG,UNIT,CAP))
ns=capture_to_file(CAP,IQFILE)
ssh("pkill -9 -x tx_ddr 2>/dev/null; touch /tmp/tx_stop")
print("captured %d samples (%.1fs)"%(ns,ns/FS))

# ---- envelope from memmap (ref-subtracted line peak per frame) ----
NS=16384; HOP=2048
mm=np.memmap(IQFILE,dtype=np.int8,mode="r")
nfr=(len(mm)//2-NS)//HOP
f=np.fft.fftshift(np.fft.fftfreq(NS,1/FS))+CENTER
sigm=np.abs(f-TARGET)<=75_000
refm=(np.abs(f-TARGET)>=200_000)&(np.abs(f-TARGET)<=500_000)
win=np.hanning(NS)
env=np.empty(nfr)
for i in range(nfr):
    o=i*HOP*2; d=mm[o:o+NS*2].astype(np.float32)
    seg=(d[0::2]+1j*d[1::2])*win
    P=np.fft.fftshift(np.abs(np.fft.fft(seg))**2)
    env[i]=10*np.log10(P[sigm].max()+1e-12)-10*np.log10(np.median(P[refm])+1e-12)
frame_ms=HOP/FS*1e3
print("envelope: %d frames @ %.2f ms"%(nfr,frame_ms))

# ---- estimate repeat period by autocorrelation, then fold/average ----
e=env-env.mean()
n=len(e); F=np.fft.rfft(e,2*n); ac=np.fft.irfft(F*np.conj(F))[:n]
fps=1000.0/frame_ms
known=34*UNIT/1000.0*fps            # SOS period prior = 34 units
lo=int(max(1.5*fps, known*0.6)); hi=int(min(n//2, known*1.5))
P=lo+int(np.argmax(ac[lo:hi]))
nreps=len(env)//P
segs=env[:nreps*P].reshape(nreps,P).copy()
# align each repetition to the running average (cancels period jitter), then fold
ref=segs.mean(0)
for _ in range(4):
    Rr=np.conj(np.fft.rfft(ref-ref.mean()))
    al=np.empty_like(segs)
    for r in range(nreps):
        s=segs[r]-segs[r].mean()
        cc=np.fft.irfft(np.fft.rfft(s)*Rr,n=P)
        sh=int(np.argmax(cc)); sh-= P if sh>P//2 else 0
        al[r]=np.roll(segs[r],-sh)
    ref=al.mean(0)
cyc=ref
print("period = %.2f s (%d frames), folded %d reps aligned (prior %.2f s)"%(P*frame_ms/1e3,P,nreps,known*frame_ms/1e3))

# ---- threshold + decode the averaged cycle ----
db=np.convolve(cyc,np.ones(max(3,int((UNIT/4)/frame_ms)))/max(3,int((UNIT/4)/frame_ms)),mode="same")
# roll so the longest gap (word gap) is at the end -> cycle starts at a letter
c=[np.percentile(db,20),np.percentile(db,80)]
for _ in range(50):
    a=(np.abs(db[:,None]-np.array(c)[None,:])).argmin(1)
    nc=[db[a==k].mean() if (a==k).any() else c[k] for k in (0,1)]
    if np.allclose(nc,c): break
    c=nc
lo_c,hi_c=min(c),max(c); thr=(lo_c+hi_c)/2; dd=0.2*(hi_c-lo_c)
onb=np.zeros(len(db),bool); stt=False
for i,v in enumerate(db):
    if v>thr+dd: stt=True
    elif v<thr-dd: stt=False
    onb[i]=stt
# rotate so we start just after the biggest off-run (word gap)
offruns=[]; i=0
while i<len(onb):
    j=i
    while j<len(onb) and not onb[j]: j+=1
    if j>i: offruns.append((i,j-i))
    i=max(j,i+1)
if offruns:
    s0=max(offruns,key=lambda r:r[1]); onb=np.roll(onb,-(s0[0]+s0[1]))

print("averaged-cycle contrast %.1f dB"%(hi_c-lo_c))
_seg=np.array_split(db,120); _lv=np.array([s.mean() for s in _seg])
_lo,_hi=np.percentile(_lv,5),np.percentile(_lv,95); _ch=" .:-=+*#%@"
print("avg cycle strip:"); print("".join(_ch[int(np.clip((v-_lo)/(_hi-_lo+1e-9),0,1)*(len(_ch)-1))] for v in _lv))

runs=[]; s=onb[0]; cnt=0
for v in onb:
    if v==s: cnt+=1
    else: runs.append((s,cnt)); s=v; cnt=1
runs.append((s,cnt))
REV={v:k for k,v in {'A':'.-','B':'-...','C':'-.-.','D':'-..','E':'.','F':'..-.','G':'--.','H':'....',
 'I':'..','J':'.---','K':'-.-','L':'.-..','M':'--','N':'-.','O':'---','P':'.--.','Q':'--.-','R':'.-.',
 'S':'...','T':'-','U':'..-','V':'...-','W':'.--','X':'-..-','Y':'-.--','Z':'--..'}.items()}
text=""; cur=""
def flush():
    global cur,text
    if cur: text+=REV.get(cur,"?"); cur=""
for st,nf in runs:
    u=nf*frame_ms/UNIT
    if st: cur += "-" if u>=2 else "."
    else:
        if u>=5: flush(); text+=" "
        elif u>=2: flush()
flush()
print("\ndecoded averaged cycle: %r"%text.strip())
print("expected %r -> %s"%(MSG.upper(), "SUCCESS" if MSG.upper() in text.replace(" ","") else "partial/again"))
# save the recovered averaged cycle (for plotting / the report)
out=os.environ.get("SOS_OUT","sos_recovered.npz")
np.savez(out, cyc=cyc, db=db, onb=onb, frame_ms=frame_ms, unit=UNIT,
         period=P, nreps=nreps, decoded=text.strip(), msg=MSG, thr=thr)
print("saved recovered data to", out)
try: os.remove(IQFILE)
except OSError: pass
