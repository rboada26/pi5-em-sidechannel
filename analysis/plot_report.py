#!/usr/bin/env python3
"""Generate report figures from the real captured data."""
import csv, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

OUT = "/home/robert/em-proj/report"
import os; os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size":11,"axes.grid":True,"grid.alpha":0.25,
                     "figure.dpi":130,"savefig.dpi":130,"savefig.bbox":"tight"})
BLUE,RED,GREY="#1f6feb","#d1242f","#6e7781"

def load_csv(p):
    r=list(csv.reader(open(p)))[1:]
    return np.array([float(x[0]) for x in r]),np.array([float(x[1]) for x in r])

# ---------- Fig 1: why averaging matters (HF ambient trap) ----------
f_on,on=load_csv("/home/robert/em-proj/captures/on.csv")
f_off,off=load_csv("/home/robert/em-proj/captures/off.csv")
d=np.load("/home/robert/em-proj/captures/avgdiff_lo.npz")
fig=plt.figure(figsize=(10,4.2))
gs=GridSpec(1,2,wspace=0.26)
ax=fig.add_subplot(gs[0])
ax.plot(f_on/1e6, on-off, color=RED, lw=1.1)
ax.axhline(0,color=GREY,lw=.8)
ax.set_title("Single ON/OFF pair (looks like signal)",fontsize=11)
ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("ON − OFF (dB)")
ax.set_xlim(0.1,30); ax.set_ylim(-15,15)
j=int(np.argmax((on-off)[f_on<25e6]))
ax.annotate("apparent +10 dB\n@ ~18 MHz",(f_on[j]/1e6,(on-off)[j]),
            xytext=(21,11),fontsize=8.5,color=RED,
            arrowprops=dict(arrowstyle="->",color=RED,lw=.8))
ax2=fig.add_subplot(gs[1])
ax2.plot(d["freqs"]/1e6, d["diff"], color=BLUE, lw=1.1)
ax2.axhline(0,color=GREY,lw=.8)
ax2.fill_between(d["freqs"]/1e6,-1,1,color=BLUE,alpha=0.10)
ax2.set_title("Averaged 8×ON / 8×OFF (ambient cancels)",fontsize=11)
ax2.set_xlabel("Frequency (MHz)"); ax2.set_ylabel("mean ON − mean OFF (dB)")
ax2.set_xlim(0.1,30); ax2.set_ylim(-15,15)
ax2.text(15,10,"flat → the HF lines were\nambient shortwave, not the Pi",
         fontsize=8.5,color=BLUE,ha="center")
fig.suptitle("Fig 1 — Single-pair differencing is fooled by ambient HF; averaging reveals the truth",
             fontsize=11.5,y=1.02)
fig.savefig(f"{OUT}/fig1_averaging.png"); plt.close(fig)

# ---------- Fig 2: the real UHF detection ----------
z=np.load("/home/robert/em-proj/captures/avgdiff_uhfzoom.npz")
f=z["freqs"]/1e6
fig=plt.figure(figsize=(10,4.4))
gs=GridSpec(2,1,height_ratios=[2,1],hspace=0.08)
ax=fig.add_subplot(gs[0])
ax.plot(f,z["moff"],color=GREY,lw=1.1,label="carrier OFF (mean of 12)")
ax.plot(f,z["mon"],color=RED,lw=1.1,label="carrier ON (mean of 12)")
for fl,name in [(263.4,"263.4 MHz"),(286.8,"286.8 MHz")]:
    ax.axvline(fl,color=BLUE,ls=":",lw=.9)
    ax.text(fl,-71,name,rotation=90,va="top",ha="right",fontsize=8,color=BLUE)
ax.set_ylabel("Level (dBm)"); ax.set_title("Fig 2 — Averaged spectra: activity-dependent UHF emission",fontsize=11.5)
ax.legend(loc="lower left",fontsize=8.5,framealpha=.9); ax.set_xticklabels([])
ax.set_xlim(f.min(),f.max())
axt=fig.add_subplot(gs[1],sharex=ax)
axt.plot(f,z["t"],color=BLUE,lw=1.0)
axt.axhline(4,color=RED,ls="--",lw=.9); axt.text(f.min()+.5,4.3,"t = 4",color=RED,fontsize=8)
axt.set_ylabel("Welch t"); axt.set_xlabel("Frequency (MHz)")
axt.fill_between(f,0,z["t"],where=z["t"]>4,color=BLUE,alpha=0.25)
axt.set_xlim(f.min(),f.max()); axt.set_ylim(-3,11)
fig.savefig(f"{OUT}/fig2_uhf_detection.png"); plt.close(fig)

# ---------- Fig 3: waterfall of the 286.8 MHz line ----------
w=np.load("/home/robert/em-proj/captures/waterfall.npz",allow_pickle=True)
f=w["freqs"]/1e6; amps=w["amps"]; st=w["states"]
nsw=amps.shape[0]; n_on=int(np.sum(st=="ON"))
fig=plt.figure(figsize=(10,4.6))
gs=GridSpec(1,2,width_ratios=[3,1.15],wspace=0.28)
ax=fig.add_subplot(gs[0])
im=ax.imshow(amps,aspect="auto",origin="lower",cmap="viridis",
             extent=[f.min(),f.max(),0,nsw],vmin=np.percentile(amps,5),vmax=np.percentile(amps,99))
ax.axhline(n_on,color="white",lw=1.4,ls="--")
ax.text(f.min()+.2,n_on+0.5,"carrier OFF ↑",color="white",fontsize=8.5,va="bottom")
ax.text(f.min()+.2,n_on-0.5,"carrier ON ↓",color="white",fontsize=8.5,va="top")
ax.axvline(286.8,color="#ffd33d",ls=":",lw=1.0)
ax.set_xlabel("Frequency (MHz)"); ax.set_ylabel("Sweep # (time →)")
ax.set_title("Fig 3 — Waterfall: 286.8 MHz line intensifies +4.4 dB while the Pi memory loop runs",fontsize=10.5)
cb=fig.colorbar(im,ax=ax,pad=0.02); cb.set_label("dBm",fontsize=9)
# side panel: power at 286.8 MHz vs sweep
j=int(np.argmin(np.abs(f-286.8)))
band=amps[:,max(0,j-2):j+3].mean(1)
axp=fig.add_subplot(gs[1])
yy=np.arange(nsw)
axp.plot(band[:n_on],yy[:n_on],color=RED,lw=1.3,marker="o",ms=3,label="ON")
axp.plot(band[n_on:],yy[n_on:],color=GREY,lw=1.3,marker="o",ms=3,label="OFF")
axp.axhline(n_on,color="k",ls="--",lw=.8)
axp.set_xlabel("Level @286.8 MHz (dBm)"); axp.set_ylabel("Sweep #")
axp.set_ylim(0,nsw-1); axp.legend(fontsize=8,loc="upper right")
axp.set_title("+4.4 dB when ON",fontsize=9)
fig.savefig(f"{OUT}/fig3_waterfall.png"); plt.close(fig)

print("wrote fig1_averaging.png, fig2_uhf_detection.png, fig3_waterfall.png to",OUT)
