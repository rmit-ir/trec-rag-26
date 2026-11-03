import json,re,hashlib
from pathlib import Path
root=Path("/home/el7/E103037/repos/trec-rag-26")
kun=Path("/scratch/fast/kun/projects/trec-rag-26")
runs={"aus_agent":"sol-aus-default-test119-20260807","aus_agent_v2":"sol-aus-v2-research-first-test119-20260807"}
for system,run in runs.items():
 subpath=kun/"data/outputs/submissions"/run/"rag_output_trec_rag_2026.jsonl"
 print("submission_path",str(subpath),"exists",subpath.exists())
 if not subpath.exists(): subpath=root/"data/outputs/submissions"/run/"rag_output_trec_rag_2026.jsonl"
 official={d["metadata"]["narrative_id"]:d for line in subpath.read_text().splitlines() if line.strip() for d in [json.loads(line)]}
 selected={};failures=[];excluded=[]
 for p in sorted((kun/"data/outputs"/system).glob("20260807*.output.json")):
  d=json.loads(p.read_text())
  if d.get("metadata",{}).get("run_id")!=run:continue
  tr=d.get("trace",{});qid=d["metadata"]["narrative_id"]
  tok=tr.get("summary",{}).get("tokens",{})
  status=tr.get("status")
  item={"qid":qid,"path":str(p),"status":status,"tokens":tok,"cost":tr.get("summary",{}).get("cost",{})}
  if status!="completed":failures.append(item);continue
  target=official.get(qid)
  if not target or any(d.get(k)!=target.get(k) for k in ("references","answer")):
   excluded.append({"qid":qid,"path":str(p)});continue
  assert qid not in selected,("duplicate",qid)
  selected[qid]=item
 assert set(selected)==set(official),(run,len(selected),set(official)-set(selected))
 logpath=kun/"tasks/task-comparison/logs"/(run+".log")
 archived=root/"worklogs/assets"/("2026-08-07-"+("sol-aus-default-test119" if system=="aus_agent" else "sol-aus-v2-research-first-test119")+".log")
 pattern=r'\[(rag2026-\d+)\]\s+"processed_tokens":\s*(\d+)'
 logged=dict((q,int(n)) for q,n in re.findall(pattern,logpath.read_text()))
 archive_logged=dict((q,int(n)) for q,n in re.findall(pattern,archived.read_text()))
 assert logged==archive_logged,(run,"log copies disagree")
 assert set(logged)==set(selected),(run,"log topic mismatch")
 for q,item in selected.items():
  assert item["tokens"]["processed"]==logged[q],(run,q,"log tokens mismatch")
  assert item["tokens"]["processed"]==item["tokens"]["input_uncached"]+item["tokens"]["output"],(run,q,"token accounting mismatch")
 fields=("input","input_uncached","output","cache_read","cache_write","total","processed")
 totals={k:sum(item["tokens"].get(k,0) for item in selected.values()) for k in fields}
 failed_totals={k:sum(item["tokens"].get(k,0) for item in failures) for k in fields}
 result={"run_id":run,"n":len(selected),"submission_path":str(subpath),"submission_sha256":hashlib.sha256(subpath.read_bytes()).hexdigest(),"totals":totals,"mean_processed":totals["processed"]/len(selected),"estimated_usd_per_topic":totals["processed"]*5/1000000/len(selected),"estimated_usd_per_topic_including_failed":(totals["processed"]+failed_totals["processed"])*5/1000000/len(selected),"failed_totals":failed_totals,"failed_attempts":failures,"excluded":excluded,"log_path":str(logpath),"log_sha256":hashlib.sha256(logpath.read_bytes()).hexdigest(),"archive_path":str(archived),"unpriced_calls":sum(i["cost"].get("unpriced_calls",0) for i in selected.values()),"priced_calls":sum(i["cost"].get("priced_calls",0) for i in selected.values()),"per_topic_columns":["qid","processed","input_uncached","output","cache_read"],"per_topic":[[q]+[selected[q]["tokens"].get(k,0) for k in ("processed","input_uncached","output","cache_read")] for q in sorted(selected,key=lambda q:int(q.split("-")[-1]))]}
 print(json.dumps(result))
