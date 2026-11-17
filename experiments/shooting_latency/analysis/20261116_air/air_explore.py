import sys, json, numpy as np, csv
sys.path.insert(0, '.')
from analyze_shooting import load_clock
D='data/20261116_air/'
ins=[json.loads(l) for l in open(D+'SALTY/inputs_Salty_20261116_145304.jsonl')][1:]
dn=np.array([x['t_wall_ns']/1e9 for x in ins if x['down']]); up=np.array([x['t_wall_ns']/1e9 for x in ins if not x['down']])
def onsets(p):
    r=list(csv.DictReader(open(p))); return np.array([float(x['t_wall_s']) for x in r]), np.array([float(x['strength']) for x in r])
so,ss=onsets(D+'SALTY/onsets_k25.csv')
do_,ds=onsets(D+'DESKTOP-42SCBR7/onsets_k40.csv')
off,_=load_clock(D+'DESKTOP-42SCBR7/clock_desktop-42scbr7_vs_192-168-1-225_20261116_145309.jsonl')
dref=do_+off(do_)
def hist(on, lo, hi):
    d=[]
    for p in dn:
        m=(on>p+lo/1000)&(on<p+hi/1000); d+=list((on[m]-p)*1000)
    h,e=np.histogram(d,bins=np.arange(lo,hi,10)); 
    for a,b in zip(e,h): print(f'{a:5.0f} {"#"*int(b/3)} {b}')
print('SALTY own: all onsets after press'); hist(so,0,500)
print('DESKTOP remote:'); hist(dref,0,700)
print('==== per press')
hold=(up-dn)*1000
def first(on, st, p, lo, hi):
    m=np.where((on>p+lo/1000)&(on<p+hi/1000))[0]
    return ((on[m[0]]-p)*1000, st[m[0]]) if len(m) else (np.nan, 0)
own=np.array([first(so,ss,p,100,260) for p in dn]); rem=np.array([first(dref,ds,p,230,410) for p in dn])
oh=~np.isnan(own[:,0]); rh=~np.isnan(rem[:,0])
print('presses',len(dn),'own heard',oh.sum(),'remote heard',rh.sum())
print('crosstab own/remote: both',(oh&rh).sum(),'own only',(oh&~rh).sum(),'remote only',(~oh&rh).sum(),'neither',(~oh&~rh).sum())
early=own[:,0]<185
print('own early (130-160) n',(oh&early).sum(),' remote heard frac',rh[oh&early].mean().round(2))
print('own late (190-250) n',(oh&~early).sum(),' remote heard frac',rh[oh&~early].mean().round(2))
for lo,hi in [(0,50),(50,60),(60,70),(70,80),(80,200)]:
    m=(hold>=lo)&(hold<hi); print(f'hold {lo}-{hi} ms n={m.sum()} own={oh[m].mean():.2f} own_early={(oh&early)[m].mean():.2f} remote={rh[m].mean():.2f}')
t0=dn[0]
for k in range(0,11):
    m=(dn-t0>=k*60)&(dn-t0<(k+1)*60)
    if m.sum(): print(f'min {k}: n={m.sum()} own={oh[m].mean():.2f} remote={rh[m].mean():.2f}')
# gap before press
g=np.r_[9,np.diff(dn)]
for lo,hi in [(0,0.8),(0.8,1.0),(1.0,1.3),(1.3,9)]:
    m=(g>=lo)&(g<hi); print(f'gap {lo}-{hi}s n={m.sum()} remote={rh[m].mean():.2f} own={oh[m].mean():.2f}')
# tick phase of press (24 Hz), using own early delay sawtooth
ph=(dn*24)%1
for k in range(6):
    m=(ph>=k/6)&(ph<(k+1)/6); print(f'phase24 {k}/6 n={m.sum()} remote={rh[m].mean():.2f} own_early={(oh&early)[m].mean():.2f}')
r=rem[rh,0]; print('remote delay pct',np.percentile(r,[5,25,50,75,95]).round(0))
o=own[oh&early,0]; print('own early pct',np.percentile(o,[5,25,50,75,95]).round(1))
import os; np.save(os.path.join(os.path.dirname(os.path.abspath(__file__)),'air.npy'),np.c_[dn,hold,own,rem])
