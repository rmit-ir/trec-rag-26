# Scratchpad 02 — Worked Examples, Verified by Hand

## E1 — Incenter angle chase: ∠BIC = 90° + A/2
I = incenter, so BI bisects B, CI bisects C.
In triangle BIC: ∠IBC = B/2, ∠ICB = C/2.
∠BIC = 180° − B/2 − C/2 = 180° − (B+C)/2.
Since A+B+C = 180°, B+C = 180°−A, so (B+C)/2 = 90° − A/2.
∠BIC = 180° − (90° − A/2) = 90° + A/2.  ✓
Sanity: equilateral A=60° → ∠BIC = 120°. By symmetry incenter=centroid, the three
central-ish angles are equal & sum to 360 → each 120°. ✓

## E2 — Power of a Point (Wikipedia-confirmed: power = d² − r²)
Take circle radius r = 5, point P at distance d = 3 from center O (P is INSIDE).
Power = d² − r² = 9 − 25 = −16. Magnitude 16.
Claim: every chord through P is split into two pieces whose product = 16.
- Check with the diameter through P: pieces are (r − d) = 2 and (r + d) = 8.
  Product = 2 × 8 = 16.  ✓
- General intersecting-chords statement PA·PB = PC·PD is exactly "this product is
  constant" = 16 for all chords. ✓
OUTSIDE case (tangent–secant): P external, tangent length t, secant meets circle at
X (near), Y (far). Then t² = PX·PY = power = d² − r².
Numeric: PX = 4, chord XY = 5 ⇒ PY = 9. t² = 4·9 = 36 ⇒ t = 6. ✓ (and 6² = 36).

## E3 — Ptolemy ⇒ PA = PB + PC (equilateral, P on arc BC)
Ptolemy (cyclic quad WXYZ in order): WY·XZ = WX·YZ + XY·ZW
(product of diagonals = sum of products of opposite sides).
Equilateral ABC inscribed; P on minor arc BC (not containing A). Vertices in cyclic
order: A, B, P, C. Apply Ptolemy to cyclic quad A B P C:
diagonals = AP and BC; opposite-side pairs = (AB, PC) and (BP, CA).
AP·BC = AB·PC + BP·CA.
With AB = BC = CA = s: AP·s = s·PC + BP·s ⇒ AP = PC + BP, i.e. PA = PB + PC. ✓
Cross-check numerically: unit circle (R=1), s = √3. Put
  A = (cos90,sin90) = (0,1); B = (cos210,sin210) = (−√3/2,−1/2);
  C = (cos330,sin330) = (√3/2,−1/2). P on arc BC at angle 270°: P=(0,−1).
PA = dist((0,−1),(0,1)) = 2.
PB = dist((0,−1),(−√3/2,−1/2)) = √(3/4 + 1/4) = √1 = 1.
PC = dist((0,−1),(√3/2,−1/2)) = 1.
PB + PC = 2 = PA. ✓

## E4 — Mass points / Ceva: intersecting cevians
Triangle ABC. D on BC with BD:DC = 1:2. E on AC with AE:EC = 3:1.
Cevians AD and BE meet at P. Find AP:PD and BP:PE.
Mass-point rule: at a point dividing a segment, masses are inversely proportional to
the adjacent sub-segments.
- D on BC, BD:DC = 1:2 ⇒ mass_B : mass_C = DC : BD = 2 : 1.
- E on AC, AE:EC = 3:1 ⇒ mass_A : mass_C = EC : AE = 1 : 3.
Make mass_C common. From second: mass_A:mass_C = 1:3. From first: mass_B:mass_C = 2:1.
Choose mass_C = 3 ⇒ mass_A = 1, mass_B = 6.
mass_D = mass_B + mass_C = 6 + 3 = 9.   mass_E = mass_A + mass_C = 1 + 3 = 4.
On cevian AD: AP:PD = mass_D:mass_A = 9:1.
On cevian BE: BP:PE = mass_E:mass_B = 4:6 = 2:3.

Coordinate cross-check:
B=(0,0), C=(3,0) ⇒ D=(1,0) [BD:DC=1:2]. A=(0,3).
E on AC, AE:EC=3:1 ⇒ E = A + (3/4)(C−A) = (2.25, 0.75).
Line AD: from (0,3) to (1,0): point = (t, 3−3t).
Line BE: from (0,0) to (2.25,0.75): slope 1/3, y = x/3.
Intersect: 3 − 3t = t/3 ⇒ 9 − 9t = t ⇒ 9 = 10t ⇒ t = 0.9 ⇒ P = (0.9, 0.3).
AP:PD along AD param (t: 0 at A → 1 at D) = 0.9 : 0.1 = 9:1. ✓
On BE: s with P = (2.25s, 0.75s): 2.25s = 0.9 ⇒ s = 0.4 ⇒ BP:PE = 0.4:0.6 = 2:3. ✓
Ceva sanity (need third cevian CF concurrent): (BD/DC)(CE/EA)(AF/FB)=1
⇒ (1/2)(1/3)(AF/FB)=1 ⇒ AF/FB = 6, consistent with masses (AF:FB = mass_B:mass_A = 6:1). ✓

## Bashing mini-check (extended law of sines)
a / sin A = 2R. Equilateral side s in circle R: s = 2R sin60° = 2R(√3/2)=R√3.
With R=1 ⇒ s=√3, matches E3. ✓

ALL EXAMPLES VERIFIED.
