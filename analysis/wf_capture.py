#!/usr/bin/env python3
"""Waterfall capture, robust version: two phases (carrier ON, then OFF), each with
the carrier state VERIFIED by pgrep before sweeping. Saves freqs/times/amps/states."""
import sys, time, subprocess, numpy as np
sys.path.insert(0, "/home/robert/em-proj/tempest-ddr")
from sa_tinysa import TinySA

PORT = "/dev/ttyACM0"
START, STOP, PTS = 280_000_000, 293_000_000, 290
N_PER = 20                      # sweeps per phase
OUT = "/home/robert/em-proj/captures/waterfall.npz"

def ssh(cmd, bg=False):
    args = ["ssh","-o","BatchMode=yes","pi@raspberrypi.local",cmd]
    if bg:  # fire-and-forget (remote tx_ddr self-backgrounds with &)
        return subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(args, stdin=subprocess.DEVNULL, timeout=20,
                          capture_output=True, text=True).stdout.strip()

def carrier_on():
    ssh("rm -f /tmp/tx_stop; cd ~/tempest-ddr && sudo -n setsid ./tx_ddr --carrier "
        ">/tmp/tx_carrier.log 2>&1 </dev/null & sleep 1", bg=True)
    time.sleep(3)
    return ssh("pgrep -x tx_ddr >/dev/null && echo YES || echo NO") == "YES"

def carrier_off():
    ssh("sudo -n pkill -9 -x tx_ddr 2>/dev/null; touch /tmp/tx_stop")
    time.sleep(1.5)
    return ssh("pgrep -x tx_ddr >/dev/null && echo YES || echo NO") == "NO"

sa = TinySA(PORT)
# warm-up until a full-length scan
freqs = None
for _ in range(6):
    fs, ys = sa.scan(START, STOP, PTS)
    if len(fs) >= PTS - 5:
        freqs = np.array(fs); break
    time.sleep(0.3)
assert freqs is not None, "no valid warm-up scan"

def grab(n, label):
    out_a, out_t, out_s = [], [], []
    while len(out_a) < n:
        fs, ys = sa.scan(START, STOP, PTS)
        ys = np.array(ys)
        if len(ys) != len(freqs):
            continue
        out_a.append(ys); out_t.append(time.monotonic()); out_s.append(label)
        print("  [%s] sweep %2d/%d  peak=%.1f dBm @ %.2f MHz"
              % (label, len(out_a), n, ys.max(), freqs[int(np.argmax(ys))]/1e6))
    return out_a, out_t, out_s

assert carrier_on(), "carrier failed to start"
print("carrier ON confirmed"); a1,t1,s1 = grab(N_PER, "ON")
assert carrier_off(), "carrier failed to stop"
print("carrier OFF confirmed"); a2,t2,s2 = grab(N_PER, "OFF")
sa.close()

amps = np.vstack(a1+a2)
times = np.array(t1+t2); times -= times[0]
states = np.array(s1+s2)
switch_t = (times[len(a1)-1] + times[len(a1)]) / 2
np.savez(OUT, freqs=freqs, times=times, amps=amps, switch_t=switch_t, states=states)
# quick contrast check at the known emission bins
for tgt in (286.8e6,263.4e6):
    j=int(np.argmin(np.abs(freqs-tgt)))
    on=amps[states=='ON',j].mean(); off=amps[states=='OFF',j].mean()
    print("  %.2f MHz  ON=%.1f OFF=%.1f  d=%+.1f dB"%(freqs[j]/1e6,on,off,on-off))
print("saved", OUT, "shape", amps.shape, "switch_t=%.1fs"%switch_t)
