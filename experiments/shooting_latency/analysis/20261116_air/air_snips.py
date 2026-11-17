import numpy as np, csv, wave, sys, os
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from scipy.signal import butter, sosfilt
S=os.path.dirname(os.path.abspath(__file__)); D='data/20261116_air/'
A=np.load(os.path.join(S,'air.npy')); dn,hold,own,_,rem,_=A.T
sys.path.insert(0,'.'); from analyze_shooting import load_clock
off,_=load_clock(D+'DESKTOP-42SCBR7/clock_desktop-42scbr7_vs_192-168-1-225_20261116_145309.jsonl')
def mapper(csvp):
    r=list(csv.DictReader(open(csvp))); t=np.array([float(x['t_wall_s']) for x in r]); s=np.array([int(x['sample']) for x in r])
    return lambda tw: np.interp(tw,t,s)
def load(w):
    f=wave.open(w); return np.frombuffer(f.readframes(f.getnframes()),np.int16).reshape(-1,2).mean(1)/32768
sos=butter(4,1500,'hp',fs=48000,output='sos')
sw=sosfilt(sos,load(D+'SALTY/audio_Salty_20261116_145305.wav')); dw=sosfilt(sos,load(D+'DESKTOP-42SCBR7/audio_desktop-42scbr7_20261116_145309.wav'))
sm=mapper(D+'SALTY/audio_Salty_20261116_145305.onsets.csv'); dm=mapper(D+'DESKTOP-42SCBR7/audio_desktop-42scbr7_20261116_145309.onsets.csv')
oh=~np.isnan(own); rh=~np.isnan(rem)
io=np.where(oh&~rh)[0]; ib=np.where(oh&rh)[0]
rng=np.random.default_rng(1); pick=list(rng.choice(io[(io>30)&(io<240)],7,replace=False))+list(rng.choice(ib[(ib>30)&(ib<240)],3,replace=False))
fig,ax=plt.subplots(len(pick),1,figsize=(13,1.7*len(pick)),sharex=True)
tt=np.arange(-0.1,0.8,1/48000)
for a,i in zip(ax,pick):
    p=dn[i]; s0=int(sm(p-0.1)); seg=sw[s0:s0+len(tt)]
    a.plot(tt*1000, seg/(np.abs(sw[s0-96000:s0+96000]).max())+1.1,lw=.4,label='Salty (shooter)')
    dl=p-off(np.array([p]))[0]; d0=int(dm(dl-0.1)); seg=dw[d0:d0+len(tt)]
    a.plot(tt*1000, seg/(np.abs(dw[d0-96000:d0+96000]).max())-1.1,lw=.4,c='C3',label='your PC (observer)')
    a.axvline(0,c='k',lw=.8); a.axvline(hold[i],c='k',ls=':',lw=.8); a.axvspan(230,410,color='C3',alpha=.08)
    a.set_yticks([]); a.set_ylim(-2.2,2.2); a.set_ylabel(f'#{i} {"heard" if rh[i] else "MISSING"}\nhold {hold[i]:.0f} ms',rotation=0,labelpad=45,fontsize=8)
ax[0].legend(loc='upper right',fontsize=7); ax[-1].set_xlabel('ms after Salty presses fire (dotted = release; shaded = where the remote shot should be)')
plt.tight_layout(); plt.savefig(os.path.join(S,'snips.png'),dpi=80)
