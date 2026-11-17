import numpy as np, os
S=os.path.dirname(os.path.abspath(__file__))
dn,hold,own,_,rem,_=np.load(os.path.join(S,'air.npy')).T
oh=~np.isnan(own); e=oh&(own<185); t=(dn-dn[0])[e]; y=own[e]
iqr=lambda x: np.subtract(*np.percentile(x,[75,25]))
def wait(t,f,ph): return (1-((t*f+ph)%1))/f*1000
best=min(((iqr(y-wait(t,f,p)),f,p) for f in np.arange(46.84,46.90,0.0005) for p in np.linspace(0,1,100,endpoint=False)))
print('block fit: f=%.4f Hz (card rate %.1f Hz) resid IQR %.2f'%(best[1],best[1]*1024,best[0]))
r=y-wait(t,best[1],best[2])
print('resid pct',np.percentile(r,[5,25,50,75,95]).round(1))
for f in [24,48,60,120]:
    print('extra step',f, round(min(iqr(r-wait(t,f,p)) for p in np.linspace(0,1,100,endpoint=False)),2))
# simulation: what residual would remain if 24 or 48 Hz wait were present, with block removed perfectly
rng=np.random.default_rng(0)
for P in [41.67,20.83,16.67,8.33]: print(f'uniform {P} ms alone IQR', round(iqr(rng.uniform(0,P,100000)),2))
# check other time-structure: residual vs time (Salty audio mapping drift?)
for k in range(5):
    m=(t>=k*120)&(t<(k+1)*120); 
    if m.sum()>5: print('t',k*120,'n',m.sum(),'resid median',np.median(r[m]).round(1),'IQR',iqr(r[m]).round(1))
