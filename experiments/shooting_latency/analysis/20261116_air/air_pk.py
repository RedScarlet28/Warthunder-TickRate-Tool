import numpy as np, os, sys
S=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,'.')
from analyze_shooting import load_clock
D='data/20261116_air/'
off,_=load_clock(D+'DESKTOP-42SCBR7/clock_desktop-42scbr7_vs_192-168-1-225_20261116_145309.jsonl')
rows=[l.strip().split(',') for l in open(os.path.join(S,'air_pkts.csv'))]
dn_t=np.array([float(r[0]) for r in rows if r[1]=='178.154.233.44']); dn_l=np.array([int(r[5]) for r in rows if r[1]=='178.154.233.44'])
up_t=np.array([float(r[0]) for r in rows if r[3]=='178.154.233.44']); up_l=np.array([int(r[5]) for r in rows if r[3]=='178.154.233.44'])
def rate(t,name):
    g=np.diff(t)*1000; h,e=np.histogram(g,bins=np.arange(0,80,1)); top=np.argsort(h)[::-1][:5]
    ph=np.exp(2j*np.pi*np.outer(np.arange(15,130,0.01),t-t[0])).mean(1) if len(t)<60000 else None
    print(name,'pps',len(t)/(t[-1]-t[0]),'gap modes ms',[(int(e[i]),int(h[i])) for i in top])
    fr=np.arange(15,130,0.02); Z=[]
    for f in fr: Z.append(abs(np.exp(2j*np.pi*f*(t-t[0])).sum())**2/len(t))
    Z=np.array(Z); i=np.argsort(Z)[::-1]
    out=[]; 
    for j in i:
        if all(abs(fr[j]-o)>0.5 for o,_ in out): out.append((round(fr[j],2),int(Z[j])))
        if len(out)==5: break
    print('  Rayleigh peaks',out)
rate(dn_t,'server->you'); rate(up_t,'you->server')
# convert downstream times to Salty ref clock
dref=dn_t+off(dn_t)
dn,hold,own,_,rem,_=np.load(os.path.join(S,'air.npy')).T
rh=~np.isnan(rem)
# bytes per 20 ms bin relative to press, -500..+800 ms, average over heard vs missing (mid of run)
t=dn-dn[0]; mid=(t>60)&(t<t.max()-60)
bins=np.arange(-500,801,25)
def prof(mask):
    acc=np.zeros(len(bins)-1); 
    for p in dn[mask]:
        m=(dref>p-0.5)&(dref<p+0.8); h,_=np.histogram((dref[m]-p)*1000,bins=bins,weights=dn_l[m]); acc+=h
    return acc/mask.sum()
H=prof(rh&mid); M=prof(~rh&mid)
base_H=H[bins[:-1]<-100].mean(); base_M=M[bins[:-1]<-100].mean()
print('downstream bytes per 25 ms bin, heard vs missing (minus baseline):')
for b,h,m in zip(bins[:-1],H-base_H,M-base_M):
    print(f'{b:5d} {h:7.1f} {m:7.1f}  {"#"*max(0,int(h/4))}|{"*"*max(0,int(m/4))}')
print('n heard',(rh&mid).sum(),'n missing',(~rh&mid).sum())
