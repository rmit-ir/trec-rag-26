import sys
exec(open("struct.py").read().split("def feats")[0])
for T in sys.argv[1:]:
    print("\n########", T); print("ASK:", runs["glm"][T]["metadata"]["narrative"])
    for k,rs in runs.items():
        its=rs[T]["answer"]; print("\n==",k,len(its),"items")
        for i in its: print(" -",i["text"][:110].replace("\n"," "))
