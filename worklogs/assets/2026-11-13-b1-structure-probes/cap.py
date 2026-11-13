import json, re, statistics as st
exec(open("struct.py").read().split("def feats")[0])
STOP = {"a","an","and","as","at","but","by","for","in","of","on","or","the","to","vs","vs.","with","from","into"}
def titlecase(s):
    w = [x for x in re.findall(r"[A-Za-z][A-Za-z'’\-/&.]*", s)]
    return len(w) >= 2 and all(x[0].isupper() or x.lower() in STOP for x in w)
def label(t):
    m = re.match(r"^([^:.\n]{3,60}):\s", t)
    return bool(m) and titlecase(m.group(1))
def allcaps(t):
    return len(re.findall(r"\b[A-Z]{4,}\b", t))
def heading(i):
    t = i["text"].strip().rstrip(".:")
    return len(t.split()) <= 12 and titlecase(t)
for k, rs in runs.items():
    A=[];B=[];C=[];D=[];tot=[]
    for t in b1:
        its = rs[t]["answer"]
        A.append(sum(heading(i) for i in its))
        B.append(sum(label(i["text"]) for i in its))
        C.append(sum(allcaps(i["text"]) for i in its))
        D.append(sum(heading(i) or label(i["text"]) for i in its))
    print(k, "titlecase-heading items", round(st.mean(A),1), A)
    print("  inline Title-Case label:", round(st.mean(B),1), B)
    print("  ALLCAPS tokens:", round(st.mean(C),1), "| topics with any structural marker:", sum(1 for a,b in zip(A,B) if a or b), "/17")
    print("  any marker total/report:", round(st.mean(D),1))
