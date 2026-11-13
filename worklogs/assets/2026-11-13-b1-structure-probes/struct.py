import json, re, statistics as st, sys

REPO = "/Users/e103037/repos/trec-rag-26/"
S = "/private/tmp/claude-501/-Users-e103037-repos-trec-rag-26/a338f9d1-c459-45d3-b4fc-ccc948c3754f/scratchpad/"
b1 = [l.strip() for l in open(REPO + "RMIT-ADM+S scores/batch1-topics.txt") if l.strip()]


def load(p):
    return {json.loads(l)["metadata"]["narrative_id"]: json.loads(l) for l in open(p)}


runs = {
    "glm": load(REPO + "data/outputs/submissions/owa-glm5-t119/rag_output_trec_rag_2026.jsonl"),
    "sol": load(S + "sol/rag_output_trec_rag_2026.jsonl"),
}
print(b1[:3], sum(t in runs["glm"] for t in b1), sum(t in runs["sol"] for t in b1))


def feats(r):
    items = r["answer"]
    txt = "\n".join(i["text"] for i in items)
    return dict(
        words=len(txt.split()),
        items=len(items),
        heads=len(re.findall(r"^#{1,6} ", txt, re.M)),
        bold=len(re.findall(r"\*\*[^*]+\*\*", txt)),
        bullets=len(re.findall(r"^\s*([-*•]|\d+\.) ", txt, re.M)),
        tables=len(re.findall(r"^\|.*\|\s*$", txt, re.M)),
        paras=len([p for p in txt.split("\n\n") if p.strip()]),
        cites=sum(len(i["citations"]) for i in items),
        refs=len(r["references"]),
    )


for k, rs in runs.items():
    F = [feats(rs[t]) for t in b1]
    print(k, {m: round(st.mean(f[m] for f in F), 1) for m in F[0]})

if len(sys.argv) > 1:
    t = sys.argv[1]
    for k, rs in runs.items():
        print("=" * 30, k, t)
        print(rs[t]["metadata"]["narrative"][:500])
        for i in rs[t]["answer"]:
            print(i["text"])
            print("   [cit]", i["citations"])

print("---- heading-like items (<=12 words, no final period, no citations) / label-prefix items ----")
for k, rs in runs.items():
    H = []; L = []; D = []
    for t in b1:
        its = rs[t]["answer"]
        h = [i for i in its if len(i["text"].split()) <= 12 and not i["text"].strip().endswith((".", "?", "!")) and not i["citations"]]
        H.append(len(h))
        L.append(sum(bool(re.match(r"^[A-Z][^.:]{2,40}: ", i["text"])) for i in its))
        D.append(sum(not i["citations"] for i in its))
    print(k, "headings/report", round(st.mean(H), 1), "per-topic", H, "| label-prefix", round(st.mean(L), 1), "| uncited items", round(st.mean(D), 1))
