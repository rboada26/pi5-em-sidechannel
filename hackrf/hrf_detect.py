#!/usr/bin/env python3
"""HackRF detection of the Pi emission using the proven tinySA method: K
interleaved carrier ON/OFF rounds, integrate power over a band around 286.8 MHz
(the line wanders ~10 kHz so we don't rely on one bin), then Welch t-test."""
import ctypes as C, numpy as np, time, subprocess

FS=8_000_000; CENTER=284_000_000; TARGET=286_800_000; BAND=75_000  # +/-75 kHz
SECS=0.3; LNA=40; VGA=40; AMP=1; K=16
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

def capture(secs):
    buf=bytearray(); done={"f":False}; tb=int(FS*secs)*2
    @CB
    def cb(tp):
        if not done["f"]:
            t=tp.contents; buf.extend(C.string_at(t.buffer,t.valid_length))
            if len(buf)>=tb: done["f"]=True
        return 0
    lib.hackrf_init(); dev=C.c_void_p()
    assert lib.hackrf_open(C.byref(dev))==0
    lib.hackrf_set_sample_rate(dev,float(FS)); lib.hackrf_set_freq(dev,CENTER)
    lib.hackrf_set_amp_enable(dev,AMP); lib.hackrf_set_lna_gain(dev,LNA); lib.hackrf_set_vga_gain(dev,VGA)
    assert lib.hackrf_start_rx(dev,cb,None)==0
    t0=time.time()
    while not done["f"] and time.time()-t0<secs+4: time.sleep(0.02)
    lib.hackrf_stop_rx(dev); lib.hackrf_close(dev); lib.hackrf_exit()
    d=np.frombuffer(bytes(buf),dtype=np.int8).astype(np.float32)
    return d[0::2]+1j*d[1::2]

NS=8192
f=np.fft.fftshift(np.fft.fftfreq(NS,1/FS))+CENTER
win=(np.abs(f-TARGET)<=30_000)                 # narrow search window for the wandering line
ref=((f>=TARGET-700_000)&(f<=TARGET-200_000))|((f>=TARGET+200_000)&(f<=TARGET+700_000))
def bandpow(x):
    n=len(x)//NS; X=x[:n*NS].reshape(n,NS)*np.hanning(NS)
    P=(np.abs(np.fft.fft(X,axis=1))**2).mean(0); P=np.fft.fftshift(P)
    # PEAK bin in the window (the line) minus local noise-floor median
    return 10*np.log10(P[win].max()+1e-9)-10*np.log10(np.median(P[ref])+1e-9)

def ssh(cmd,bg=False):
    a=["ssh","-o","BatchMode=yes","pi@raspberrypi.local",cmd]
    if bg: return subprocess.Popen(a,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return subprocess.run(a,stdin=subprocess.DEVNULL,timeout=20,capture_output=True,text=True).stdout.strip()
def con():
    ssh("rm -f /tmp/tx_stop; cd ~/tempest-ddr && setsid ./tx_ddr --carrier >/tmp/tx.log 2>&1 </dev/null & sleep 1",bg=True)
    time.sleep(2.0); return ssh("pgrep -x tx_ddr >/dev/null && echo YES||echo NO")=="YES"
def coff():
    ssh("pkill -9 -x tx_ddr 2>/dev/null; touch /tmp/tx_stop"); time.sleep(1.0)

ON=[]; OFF=[]
print("interleaved ON/OFF, band = 286.8 +/- %.0f kHz (signal minus local reference)"%(BAND/1e3))
for k in range(K):
    assert con(),"carrier start fail"; ON.append(bandpow(capture(SECS)))
    coff();                           OFF.append(bandpow(capture(SECS)))
    print("  round %d/%d  ON=%+.2f  OFF=%+.2f dB"%(k+1,K,ON[-1],OFF[-1]))
ssh("pkill -9 -x tx_ddr 2>/dev/null; touch /tmp/tx_stop")
ON=np.array(ON); OFF=np.array(OFF)
diff=ON.mean()-OFF.mean()
se=np.sqrt(ON.var(ddof=1)/len(ON)+OFF.var(ddof=1)/len(OFF))+1e-9
print("\n  mean ON=%+.2f  mean OFF=%+.2f  diff=%+.2f dB  t=%.1f  %s"%(
    ON.mean(),OFF.mean(),diff,diff/se,"DETECTED" if diff/se>=3 else "not significant"))
