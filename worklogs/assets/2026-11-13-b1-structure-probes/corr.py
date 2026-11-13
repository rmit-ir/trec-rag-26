import json, csv, statistics as st
d=json.load(open("/Users/e103037/repos/trec-rag-26-report/worklogs/assets/2026-11-08-batch1-readability.json"))["per_topic"]
P={}
for r in d:
    if r["batch"]==1: P.setdefault(r["qid"],{})[r["run"]]=r
net={}
for r in csv.DictReader(open("/Users/e103037/repos/trec-rag-26/RMIT-ADM+S scores/rag-sxs-counts-batch1.tsv"),delimiter="\t"):
    w,t,l=int(r["wins"]),int(r["ties"]),int(r["losses"]); net.setdefault(r["narrative-id"],{})[r["run"]]=(w-l)/(w+t+l)
qs=sorted(P)
y=[net[q]["owa-glm5-t119"]-net[q]["sol-research-first"] for q in qs]
def rk(v): s=sorted(v); return [s.index(x)+1+(v.count(x)-1)/2 for x in v]
print("n",len(qs),"| glm-sol net margin>0 on",sum(m>0 for m in y))
for m in ["words","references","words_per_sentence","reading_ease","fk_grade","ari","coleman_liau","gunning_fog","difficult_words","sentences"]:
    x=[P[q]["owa-glm5"][m]-P[q]["sol-research-first"][m] for q in qs]
    print("%-20s pearson %5.2f spearman %5.2f | GLM better on %2d/17 topics"%(m,st.correlation(x,y),st.correlation(rk(x),rk(y)),sum((a>0)==(b>0) for a,b in zip(x,y) if True) if False else 0))
# win rate split: topics where glm is easier-to-read vs not
for m,easier in [("reading_ease",lambda a:a>0),("words_per_sentence",lambda a:a<0),("words",lambda a:a<0)]:
    g=[(P[q]["owa-glm5"][m]-P[q]["sol-research-first"][m]) for q in qs]
    A=[yy for a,yy in zip(g,y) if easier(a)]; B=[yy for a,yy in zip(g,y) if not easier(a)]
    print(m,"glm easier/shorter on",len(A),"topics: mean margin",round(st.mean(A),2),"| else",len(B),"topics:",round(st.mean(B),2) if B else "n/a")
