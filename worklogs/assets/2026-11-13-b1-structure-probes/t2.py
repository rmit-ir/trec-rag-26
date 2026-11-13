exec(open("struct.py").read().split("def feats")[0])
import re
T="rag2026-2"
for k,rs in runs.items():
    r=rs[T]; its=r["answer"]
    if k=="glm": print(r["metadata"]["narrative"][:600])
    w=[len(i["text"].split()) for i in its]
    print("=====",k,"items",len(its),"words",sum(w),"refs",len(r["references"]),"uncited",sum(not i["citations"] for i in its))
    for i in its: print(" -",i["text"][:230].replace("\n"," "))
