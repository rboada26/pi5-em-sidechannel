#!/usr/bin/env python3
"""Averaged ON/OFF differencing with a per-bin significance test, to separate a
real board emission from intermittent ambient. For each span: capture K interleaved
ON and OFF sweeps (toggling the carrier each round so ambient drift affects both
equally), then report bins where mean(ON)-mean(OFF) is large AND statistically
significant (Welch t). Saves per-span npz for later plotting."""
import sys, time, subprocess, numpy as np
sys.path.insert(0, "/home/robert/em-proj/tempest-ddr")
from sa_tinysa import TinySA

PORT = "/dev/ttyACM0"
K = 8  # ON/OFF rounds per span (interleaved) -> K sweeps each state

def ssh(cmd, bg=False):
    a=["ssh","-o","BatchMode=yes","pi@raspberrypi.local",cmd]
    if bg: return subprocess.Popen(a,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return subprocess.run(a,stdin=subprocess.DEVNULL,timeout=20,capture_output=True,text=True).stdout.strip()

def carrier_on():
    ssh("rm -f /tmp/tx_stop; cd ~/tempest-ddr && sudo -n setsid ./tx_ddr --carrier >/tmp/tx_carrier.log 2>&1 </dev/null & sleep 1",bg=True)
    time.sleep(2.5); return ssh("pgrep -x tx_ddr >/dev/null && echo YES || echo NO")=="YES"
def carrier_off():
    ssh("sudo -n pkill -9 -x tx_ddr 2>/dev/null; touch /tmp/tx_stop"); time.sleep(1.2)
    return ssh("pgrep -x tx_ddr >/dev/null && echo YES || echo NO")=="NO"

sa=TinySA(PORT)
def scan(a,b):
    for _ in range(4):
        fs,ys=sa.scan(a,b,290)
        if len(fs)>=285: return np.array(fs),np.array(ys)
        time.sleep(0.3)
    return None,None

def survey(start,stop,tag):
    freqs=None; ON=[]; OFF=[]
    for k in range(K):
        assert carrier_on(), "carrier on fail"
        f,y=scan(start,stop);
        if y is not None: ON.append(y); freqs=f
        assert carrier_off(), "carrier off fail"
        f,y=scan(start,stop)
        if y is not None: OFF.append(y)
        print("  %s round %d/%d done"%(tag,k+1,K))
    ON=np.vstack(ON); OFF=np.vstack(OFF)
    mon,moff=ON.mean(0),OFF.mean(0); diff=mon-moff
    # Welch t per bin
    vON,vOFF=ON.var(0,ddof=1),OFF.var(0,ddof=1)
    se=np.sqrt(vON/len(ON)+vOFF/len(OFF))+1e-9
    t=diff/se
    out="/home/robert/em-proj/captures/avgdiff_%s.npz"%tag
    np.savez(out,freqs=freqs,mon=mon,moff=moff,diff=diff,t=t,ON=ON,OFF=OFF)
    order=np.argsort(t)[::-1][:5]
    print("  [%s %g-%g MHz] top bins by t-stat (real emission = high t at stable f):"%(tag,start/1e6,stop/1e6))
    for i in order:
        print("    %.3f MHz  diff=%+.1f dB  t=%.1f  (ON=%.1f OFF=%.1f)"%(freqs[i]/1e6,diff[i],t[i],mon[i],moff[i]))
    print("    band: max diff=%+.1f dB, max t=%.1f, median|diff|=%.2f dB"%(diff.max(),t.max(),np.median(np.abs(diff))))
    return out

spans=[(100e3,30e6,"lo"),(30e6,120e6,"vhf"),(120e6,300e6,"uhf")]
for a,b,tag in spans:
    print("=== survey %s %g-%g MHz ==="%(tag,a/1e6,b/1e6)); survey(a,b,tag)
sa.close()
ssh("sudo -n pkill -9 -x tx_ddr 2>/dev/null; touch /tmp/tx_stop")
print("done")
