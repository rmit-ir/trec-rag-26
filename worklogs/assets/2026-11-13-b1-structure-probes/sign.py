exec(open("struct.py").read().split("def feats")[0])
import csv
d={}
for r in csv.DictReader(open(REPO+"RMIT-ADM+S scores/rag-sxs-counts-batch1.tsv"),delimiter="\t"):
    w,t,l=int(r["wins"]),int(r["ties"]),int(r["losses"]); d.setdefault(r["run"],{})[r["narrative-id"]]=(w-l)/(w+t+l)
M={
 "enumerators":r"\b(First|Second|Third|Finally|Lastly|Next|Then)\b[,:]|\(\s*[a-z1-9]\s*\)|\b[1-9]\)|^\s*[1-9]\.\s",
 "any-case colon lead-in":r"^[A-Za-z][^.:;]{2,50}:\s",
 "phase/step markers":r"\b(Month|Months|Step|Phase|Stage|Year|Quarter|Week|Days?)\s*\d",
 "semicolons":r";",
 "'if/when…then' decision rules":r"^(If|When|Stay|Hire|Choose|Prioriti[sz]e|Avoid|Start|Begin)\b",
}
for k,rs in runs.items():
    print(k)
    for m,p in M.items():
        c=[sum(len(re.findall(p,i["text"],re.M)) for i in rs[t]["answer"]) for t in b1]
        print("  %-30s mean %.1f  topics>0 %d/17"%(m,st.mean(c),sum(x>0 for x in c)))
# per-topic: does glm-sol margin move with sign-post gap?
import statistics
def tot(rs,t): return sum(len(re.findall(M["enumerators"],i["text"],re.M))+len(re.findall(M["phase/step markers"],i["text"],re.M)) for i in rs[t]["answer"])
xs=[tot(runs["glm"][t])-tot(runs["sol"][t]) for t in b1] if False else [tot(runs["glm"],t)-tot(runs["sol"],t) for t in b1]
ys=[d["owa-glm5-t119"][t]-d["sol-research-first"][t] for t in b1]
print("corr(glm-sol signpost gap, net margin) =",round(statistics.correlation(xs,ys),2))
