exec(open("struct.py").read().split("def feats")[0])
b2=[l.strip() for l in open(REPO+"RMIT-ADM+S scores/batch2-topics.txt") if l.strip()]
def capsh(i):
    t=i["text"].strip(); L=[c for c in t if c.isalpha()]
    return len(t.split())<=12 and len(L)>=6 and sum(c.isupper() for c in L)/len(L)>0.8
for name,ts in (("B1",b1),("B2",b2),("all119",list(runs["glm"]))):
    for k,rs in runs.items():
        c=[sum(capsh(i) for i in rs[t]["answer"]) for t in ts]
        print(name,k,"ALLCAPS headings/report",round(st.mean(c),1),"topics with any",sum(x>0 for x in c),"/",len(ts))
