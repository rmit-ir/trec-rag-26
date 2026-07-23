import json, sys, urllib.request

URL = "http://127.0.0.1:8099/search"

def search(q, k=3):
    data = json.dumps({"query": q, "k": k}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

for q in sys.argv[1:]:
    d = search(q, 3)
    hits = d["results"]
    print(f"### Q: {q}")
    print(f"    hits: {len(hits)}")
    for r in hits:
        snip = " ".join(r["snippet"].split())[:150]
        print(f"    [{r['rank']}] {r['docno']}: {snip}")
    print()
