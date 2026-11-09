"""Recompute per-topic generation cost from token usage and rate cards.
Run: python worklogs/assets/2026-11-09-cost-recompute.py
Tokens: SCORES.md per-topic averages (brief/facets/owa/facetrag) and exact Sol totals
from worklogs/assets/2026-11-04-sol-cost-recovery.json (119 topics each)."""
from decimal import Decimal as D
M = D(1_000_000)
# (uncached_in, cached_in, out) USD per 1M
AZ_SOL  = (D(5), D("0.5"), D(30))              # OpenAI list; Azure Global Standard assumed equal
AZ_LUNA = (D("0.20"), D("0.02"), D("1.20"))    # Bedrock Luna rates / 1.10 (Bedrock markup)
# Bedrock Sol, derived from AWS Cost Explorer Aug 7: write, read, out
BR_SOL_WRITE, BR_SOL_READ, BR_SOL_OUT = D("6.88"), D("0.55"), D("33.00")
GLM5 = (D("1.20"), D("3.20"))                  # Bedrock zai.glm-5 in/out per 1M (AWS usage types)

def cost(tok, rate): return sum(D(t)*r for t, r in zip(tok, rate))/M

per_topic = {
 "brief-hybrid":  (293077, 322397, 7544),
 "brief-base":    (319561, 388548, 8024),
 "facets":        (138936,  71421, 5912),
}
sol_total = {  # exact totals over 119 topics (successful attempts)
 "sol-default":        (21683003, 24080679,  725051),
 "sol-research-first": (39333645, 43950115, 1246976),
}
print("== Azure-equivalent (OpenAI list, no cache-write fee), USD/topic")
for k, t in per_topic.items():
    print(k, round(cost(t, AZ_LUNA if k == "facets" else AZ_SOL), 4))
for k, t in sol_total.items():
    print(k, round(cost(t, AZ_SOL)/119, 4), "total", round(cost(t, AZ_SOL), 2))
print("== Bedrock billed rates (uncached input billed as cache write)")
tot = D(0)
for k, (u, c, o) in sol_total.items():
    t = (D(u)*BR_SOL_WRITE + D(c)*BR_SOL_READ + D(o)*BR_SOL_OUT)/M
    tot += t; print(k, round(t/119, 4), "total", round(t, 2))
print("two runs total", round(tot, 2), "vs AWS Aug-07 $532.77 ->", round(tot/D("532.77")*100, 1), "%")
print("== owa-glm5 at AWS GLM-5 rate, USD/topic", round((D(415080)*GLM5[0]+D(5899)*GLM5[1])/M, 4),
      "run", round((D(415080)*GLM5[0]+D(5899)*GLM5[1])/M*119, 2))
