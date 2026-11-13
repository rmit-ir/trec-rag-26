exec(open("struct.py").read().split("def feats")[0])
import re
for k,rs in runs.items():
    r=rs["rag2026-13"]; its=r["answer"]
    w=[len(i["text"].split()) for i in its]
    unc=[i for i in its if not i["citations"]]
    print(k,"items",len(its),"words",sum(w),"refs",len(r["references"]),"cited items",len(its)-len(unc),"uncited",len(unc),"median words/item",sorted(w)[len(w)//2])
    print("  first item:",its[0]["text"][:90])
    print("  Month/phase-structured items:",sum(bool(re.match(r"(Month|During month|At month)",i["text"])) for i in its))
    print("  second-person items:",sum(bool(re.search(r"\byou(r)?\b",i["text"],re.I)) for i in its))
