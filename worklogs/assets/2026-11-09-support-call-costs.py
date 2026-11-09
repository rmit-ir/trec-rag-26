import re,json,glob,sys,ast
H="/home/el7/E103037/repos/trec-rag-26/tasks/task-comparison/logs/"
O="/research/remote/petabyte/users/oleg/trec_rag_26_data/outputs/"
runs=[("brief-base","brief-revise-base-test119-20260808","brief_revise_agent",(5.5,.55,33.0)),
      ("brief-hybrid","brief-revise-hybrid-test119-20260808","brief_revise_agent",(5.5,.55,33.0)),
      ("owa-glm5","oss-agent-glm5-test119-20260809","open_weight_agent",(1.2,0,3.2))]
import os
for name,rid,sysd,(pi,pc,po) in runs:
    lf=H+rid+".log"
    if not os.path.exists(lf):
        c=glob.glob(H+name.split("-")[0]+"*"+rid.split("-")[-2]+"*.log"); print("missing",lf,c); continue
    seg={};cur={}
    for l in open(lf,errors="ignore"):
        m=re.match(r"\[(rag2026-\d+)\]",l)
        if not m: continue
        s=m.group(1)
        if " starting:" in l: cur[s]=[0,0,0]
        u=re.search(r"usage=(\{.*\})",l)
        if u and s in cur:
            d=ast.literal_eval(u.group(1))
            cur[s][0]+=d.get("input_tokens",d.get("inputTokens",0));cur[s][1]+=d.get("cache_read_input_tokens",0);cur[s][2]+=d.get("output_tokens",d.get("outputTokens",0))
        if "finished status=completed" in l and s in cur:
            seg[s]=cur.pop(s)
    n=len(seg);i=sum(v[0] for v in seg.values());cr=sum(v[1] for v in seg.values());o=sum(v[2] for v in seg.values())
    # trace totals
    ti=tc=to=tn=0;seen={}
    for f in glob.glob(O+sysd+"/*.output.json"):
        try:d=json.load(open(f))
        except:continue
        if d["metadata"].get("run_id")!=rid or d["trace"]["status"]!="completed":continue
        seen[d["trace"]["query_id"]]=d["trace"]["summary"]["tokens"]
    for t in seen.values(): ti+=t["input_uncached"];tc+=t["cache_read"];to+=t["output"]
    tn=len(seen)
    sup=(i*pi+cr*pc+o*po)/1e6; tr=(ti*pi+tc*pc+to*po)/1e6
    print(name,"slots_completed",n,"traces",tn,"support in/cr/out",i,cr,o,"$%.2f"%sup,"trace in/cr/out",ti,tc,to,"$%.2f"%tr,"total/topic $%.3f (trace %.3f + sup/n %.3f)"%((sup+tr)/max(tn,1),tr/max(tn,1),sup/max(n,1)))
