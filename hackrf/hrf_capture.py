#!/usr/bin/env python3
"""Minimal HackRF RX via libhackrf directly (ctypes), avoiding the newer
hackrf_set_hw_sync_mode() call that 2015 firmware doesn't support. Proves the
device streams with old firmware. Captures ~0.4s of int8 IQ at a given freq.
Usage: hrf_capture.py <freq_Hz> <out.iq> [seconds] [lna] [vga]"""
import ctypes as C, numpy as np, time, sys

freq = int(float(sys.argv[1])) if len(sys.argv)>1 else 286_800_000
out  = sys.argv[2] if len(sys.argv)>2 else "/tmp/hrf.iq"
secs = float(sys.argv[3]) if len(sys.argv)>3 else 0.4
lna  = int(sys.argv[4]) if len(sys.argv)>4 else 24     # 0..40 step 8
vga  = int(sys.argv[5]) if len(sys.argv)>5 else 20     # 0..62 step 2
FS   = 8_000_000
TARGET_BYTES = int(FS*secs)*2

lib = C.CDLL("libhackrf.so.0")
class xfer(C.Structure):
    _fields_=[("device",C.c_void_p),("buffer",C.POINTER(C.c_uint8)),
              ("buffer_length",C.c_int),("valid_length",C.c_int),
              ("rx_ctx",C.c_void_p),("tx_ctx",C.c_void_p)]
CB = C.CFUNCTYPE(C.c_int, C.POINTER(xfer))
buf = bytearray(); done = {"f":False}
@CB
def rx_cb(tp):
    if not done["f"]:
        t=tp.contents
        buf.extend(C.string_at(t.buffer, t.valid_length))
        if len(buf) >= TARGET_BYTES: done["f"]=True
    return 0

def chk(r,m):
    if r!=0: print("ERR",m,"rc=",r); sys.exit(1)

lib.hackrf_open.argtypes=[C.POINTER(C.c_void_p)]
lib.hackrf_set_sample_rate.argtypes=[C.c_void_p,C.c_double]
lib.hackrf_set_freq.argtypes=[C.c_void_p,C.c_uint64]
lib.hackrf_set_amp_enable.argtypes=[C.c_void_p,C.c_uint8]
lib.hackrf_set_lna_gain.argtypes=[C.c_void_p,C.c_uint32]
lib.hackrf_set_vga_gain.argtypes=[C.c_void_p,C.c_uint32]
lib.hackrf_start_rx.argtypes=[C.c_void_p,CB,C.c_void_p]
lib.hackrf_stop_rx.argtypes=[C.c_void_p]
lib.hackrf_close.argtypes=[C.c_void_p]

chk(lib.hackrf_init(),"init")
dev=C.c_void_p()
chk(lib.hackrf_open(C.byref(dev)),"open")
chk(lib.hackrf_set_sample_rate(dev,float(FS)),"sample_rate")
chk(lib.hackrf_set_freq(dev,freq),"set_freq")
lib.hackrf_set_amp_enable(dev,0)
lib.hackrf_set_lna_gain(dev,lna)
lib.hackrf_set_vga_gain(dev,vga)
chk(lib.hackrf_start_rx(dev,rx_cb,None),"start_rx")
t0=time.time()
while not done["f"] and time.time()-t0 < secs+4: time.sleep(0.03)
lib.hackrf_stop_rx(dev); lib.hackrf_close(dev); lib.hackrf_exit()

d=np.frombuffer(bytes(buf),dtype=np.int8)
I=d[0::2].astype(np.float32); Q=d[1::2].astype(np.float32)
d.tofile(out)
print("freq=%.3f MHz  captured %d samples (%.2f s)" % (freq/1e6, len(I), len(I)/FS))
print("I.std=%.1f Q.std=%.1f mean|IQ|=%.1f  -> %s" %
      (I.std(), Q.std(), np.hypot(I,Q).mean(), "STREAMING OK" if I.std()>0.5 else "NO SIGNAL/zeros"))
print("saved", out)
