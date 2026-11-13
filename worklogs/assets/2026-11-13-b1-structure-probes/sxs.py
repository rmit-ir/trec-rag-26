import csv, statistics as st
P="/Users/e103037/repos/trec-rag-26/RMIT-ADM+S scores/rag-sxs-counts-batch1.tsv"
d={}
for r in csv.DictReader(open(P),delimiter="\t"):
    w,t,l=int(r["wins"]),int(r["ties"]),int(r["losses"])
    d.setdefault(r["run"],{})[r["narrative-id"]]=(w,t,l)
b1=[l.strip() for l in open("/Users/e103037/repos/trec-rag-26/RMIT-ADM+S scores/batch1-topics.txt") if l.strip()]
# structured topic order from cap.py: indices of GLM markers
heads=[0,8,0,0,0,15,0,6,0,0,0,0,7,0,0,0,0]; labs=[0,4,0,0,0,7,0,0,0,0,0,0,2,0,0,6,0]
S=[t for t,h,b in zip(b1,heads,labs) if h or b]
print("structured:",S)
def net(x): w,t,l=x; return (w-l)/(w+t+l)
print("topic  glm(w/t/l) net | sol(w/t/l) net | struct")
for t in b1:
    g=d["owa-glm5-t119"][t]; s=d["sol-research-first"][t] if "sol-research-first" in d else None
    print(t,g,round(net(g),2),"|",s,round(net(s),2),"|","S" if t in S else "")
for name,ts in (("structured",S),("plain",[t for t in b1 if t not in S]),("all",b1)):
    for run in d:
        print(name,run,"mean net",round(st.mean(net(d[run][t]) for t in ts),3),"n",len(ts))
