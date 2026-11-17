import numpy as np, os
S=os.path.dirname(os.path.abspath(__file__))
dn,hold,own,_,rem,_=np.load(os.path.join(S,'air.npy')).T
rh=~np.isnan(rem); t=(dn-dn[0]); y=rem[rh]; tt=t[rh]
iqr=lambda x: np.subtract(*np.percentile(x,[75,25]))
print('remote n',rh.sum(),'median',np.median(y),'IQR',iqr(y).round(1))
for k in range(0,700,60):
    m=(tt>=k)&(tt<k+60)
    if m.sum()>3: print(f' {k:3d}s n={m.sum():2d} median {np.median(y[m]):.0f} IQR {iqr(y[m]):.0f}')
def wait(t,f,ph): return (1-((t*f+ph)%1))/f*1000
res=sorted((min(iqr(y-wait(tt,f,p)) for p in np.linspace(0,1,24,endpoint=False)),f) for f in np.arange(15,60,0.01))
print('best', [(round(f,2),round(q,1)) for q,f in res[:6]])
for f in [24,24.48,48,49.1]: print(f, round(min(iqr(y-wait(tt,f,p)) for p in np.linspace(0,1,60,endpoint=False)),1))
# own-only vs both: hold and remote miss by own delay
oh=~np.isnan(own)
print('remote heard vs own delay group: early',rh[oh&(own<185)].mean().round(2),'late',rh[oh&(own>=185)].mean().round(2))
# misses: previous tap heard? cluster check (runs test)
x=rh[(t>60)&(t<t.max()-60)].astype(int); p=x.mean(); n=len(x)
runs=1+np.sum(x[1:]!=x[:-1]); er=1+2*n*p*(1-p); print('runs',runs,'expected if independent',round(er,1))
# P(miss | previous miss)
print('P(miss|prev miss)',round(np.mean(1-x[1:][x[:-1]==0]),2),'P(miss|prev heard)',round(np.mean(1-x[1:][x[:-1]==1]),2))
