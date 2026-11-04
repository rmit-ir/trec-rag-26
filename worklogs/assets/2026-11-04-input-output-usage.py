import json,hashlib
from pathlib import Path
root=Path("/home/el7/E103037/repos/trec-rag-26")
runs=[
("brief_revise_agent","brief-revise-base-test119-20260808","brief-base-t119"),
("brief_revise_agent","brief-revise-hybrid-test119-20260808","brief-hybrid-t119"),
("facets_agent","facets-agent-test119-20260808","facets-t119"),
("facet_rag","facet-rag-test119-20260808","facetrag-t119"),
("open_weight_agent","open-weight-agent-glm5-test119-20260809","owa-glm5-t119")]
fields=("input","input_uncached","output","cache_read","cache_write","total","processed")
for system,run,tag in runs:
 sub=root/"data/outputs/submissions"/tag/"rag_output_trec_rag_2026.jsonl"
 official={d["metadata"]["narrative_id"]:d for line in sub.read_text().splitlines() if line.strip() for d in [json.loads(line)]}
 selected={};failed=[];excluded=[]
 for p in sorted((root/"data/outputs"/system).glob("202608*.output.json")):
  with p.open() as header:
   prefix=header.read(2048)
  if run not in prefix:continue
  d=json.loads(p.read_text())
  if d.get("metadata",{}).get("run_id")!=run:continue
  tr=d.get("trace",{});qid=d["metadata"]["narrative_id"]
  if tr.get("status")!="completed": failed.append({"qid":qid,"path":str(p),"tokens":tr.get("summary",{}).get("tokens",{})});continue
  target=official.get(qid)
  if not target or any(d.get(k)!=target.get(k) for k in ("answer","references")):
   excluded.append(str(p));continue
  assert qid not in selected,("duplicate",run,qid)
  tok=tr["summary"]["tokens"]
  selected[qid]={"path":str(p),"tokens":tok}
 assert len(selected)==119 and set(selected)==set(official),(run,len(selected))
 totals={k:sum(d["tokens"].get(k,0) for d in selected.values()) for k in fields}
 for q,d in selected.items():
  t=d["tokens"]
  assert t["processed"]==t["input_uncached"]+t["cache_write"]+t["output"],(run,q,t)
 print(json.dumps({"run_id":run,"tag":tag,"n":119,"totals":totals,"means":{k:v/119 for k,v in totals.items()},"submission_sha256":hashlib.sha256(sub.read_bytes()).hexdigest(),"failed_attempts":failed,"excluded":excluded,"per_topic_columns":["qid"]+list(fields),"per_topic":[[q]+[selected[q]["tokens"].get(k,0) for k in fields] for q in sorted(selected,key=lambda q:int(q.split("-")[-1]))]}))
