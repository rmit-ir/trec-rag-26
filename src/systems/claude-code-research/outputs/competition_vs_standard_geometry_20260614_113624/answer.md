# Two Geometries: The One You Learned in School vs. the One on the Olympiad

If you took geometry in an American high school, you learned a real and beautiful subject. You proved triangles congruent, you memorized that the inscribed angle is half the central angle, you used the Pythagorean theorem more times than you can count, and you probably filled out at least one two-column proof that felt like filling out a tax form.

Then somebody hands you a problem from the AMC, the AIME, or a math olympiad, and it might as well be written in a different language. The diagram has a circle, three cevians, an incenter, and a point "M, the midpoint of arc BC," and you're asked to prove that three lines you've never heard of all pass through one spot.

Here's the surprising part: **competition geometry uses almost the same axioms and facts you already know.** There's no secret extra geometry hidden from civilians. What's different is the *culture* — the goals, the mindset, and a toolkit of theorems and techniques that the standard curriculum simply never gets around to teaching. This post is a tour of that gap, with worked examples you can follow using only what you already know.

---

## The core difference: verification vs. discovery

Standard high school geometry is mostly about **verification**. You are given a statement ("the diagonals of a parallelogram bisect each other") and asked to *confirm* it through a structured proof. The path is usually short and the answer is known in advance. The skill being graded is whether you can justify each step with a named reason.

Competition geometry is about **discovery**. Nobody tells you which theorem to use. The whole challenge is figuring out *what is even true* in the picture, and then finding a chain — often a long and clever one — that gets you there. A single hard olympiad problem can eat an hour, and the satisfying click comes from spotting a hidden structure: a circle that wasn't drawn, two triangles that are secretly similar, a point that's secretly the center of something.

A second difference is **speed vs. depth**, and it splits the contests into tiers:

- **AMC 10/12** (multiple choice, ~3 minutes/problem): you just need the *number*. Slick shortcuts and "plug in nice values" are king.
- **AIME** (integer answers 0–999, ~12 minutes/problem): heavier computation, real theorems, but still no proof required.
- **Olympiads** (USAMO, IMO; a few problems over 4+ hours): full written proofs. Rigor and creativity both matter, and a beautiful synthetic argument is the goal.

So the same word, "geometry," covers a fast number-hunting game *and* a slow proof-writing art. Both reward a body of tools your class skipped. Let's look at them.

---

## The mindset shift, before any new theorems

Three habits separate a competitor from a strong classroom student, and none of them require new facts:

**1. Angle chasing.** This is the bread and butter. You label everything in sight in terms of a few unknown angles and relentlessly propagate equalities using the inscribed-angle theorem, the exterior-angle fact, isosceles triangles, and parallel lines. Most "find the angle" contest problems are pure bookkeeping once you commit to labeling. Competitors do this so much that they adopt **directed angles modulo 180°**, a convention that makes one argument cover all the different-looking diagrams at once (so you don't lose points because your picture had the point on the "wrong" side).

**2. Auxiliary constructions.** The classroom rarely asks you to *add* to the figure. Competition geometry is often won the instant you draw the one extra line, circle, or point that wasn't there: drop a perpendicular, extend a segment to where it meets a circle again, reflect a point over a midpoint, or draw the circle through four points that "look concyclic." Knowing *which* line to add is the art.

**3. Seeing configurations.** Experienced solvers recognize recurring mini-structures on sight — "oh, that's a spiral similarity," "those four points are concyclic," "that's the arc midpoint, so it's equidistant from three points." The classroom teaches facts; competition teaches *patterns*.

Now the toolbox.

---

## Tool 1: Power of a Point

Your class taught the special cases of this and never named the general idea.

> **Power of a Point.** Fix a point P and a circle. Draw *any* line through P that meets the circle at two points X and Y. Then the product of signed distances PX · PY is the *same* for every such line. If P is outside and PT is a tangent, that constant equals PT². [[1]](https://artofproblemsolving.com/wiki/index.php/Power_of_a_Point_Theorem) [[2]](https://en.wikipedia.org/wiki/Power_of_a_point)

This bundles three facts into one:

- **Two chords crossing inside:** chords AB and CD meet at P ⟹ PA · PB = PC · PD.
- **Two secants from outside:** ⟹ PA · PB = PC · PD.
- **Tangent–secant:** PT² = PA · PB.

**Worked example (chord–chord).** Two chords AB and CD of a circle meet at an interior point P. You're told PA = 8, PB = 6, the whole chord CD has length 16, and PC < PD. Find PC.

Power of the point gives PC · PD = PA · PB = 8 · 6 = 48. We also know PC + PD = 16. So PC and PD are the two roots of
$$x^2 - 16x + 48 = 0 \implies x = \frac{16 \pm \sqrt{256 - 192}}{2} = \frac{16 \pm 8}{2} = 12 \text{ or } 4.$$
Since PC < PD, **PC = 4** (and PD = 12). No coordinates, no trig — one identity and a quadratic.

**Worked example (tangent–secant).** From a point P outside a circle, the tangent PT has length 6, and a secant through P meets the circle at A (near) then B (far) with PA = 4. Find the chord length AB.

PT² = PA · PB ⟹ 36 = 4 · PB ⟹ PB = 9, so **AB = PB − PA = 5.**

Power of a Point is also the backbone of the **radical axis** — the locus of points with equal power to two circles — which competitors use to prove three lines are concurrent in one line of reasoning. That concept never appears in the standard curriculum.

---

## Tool 2: Real angle chasing — the "arc midpoint" lemma (a.k.a. "Fact 5")

Here's a result so common in olympiads that students just call it **Fact 5** (from a famous handout). It shows what trained angle-chasing buys you.

> **Incenter–Excenter Lemma.** In triangle ABC, let the bisector of angle A meet the circumcircle again at M (so M is the midpoint of arc BC not containing A). Let I be the incenter. Then
> $$MB = MC = MI.$$
> That is, M is the center of a circle through B, I, and C. (The lemma actually says the opposite excenter lies on this circle too, hence its other nicknames: the *Trillium* or *Chicken-Foot* lemma.) [[3]](https://web.evanchen.cc/handouts/Fact5/Fact5.pdf) [[4]](https://en.wikipedia.org/wiki/Incenter%E2%80%93excenter_lemma)

Your class has all the pieces to prove this; it just never strings them together. Write the angles as A = 2α, B = 2β, C = 2γ (so α + β + γ = 90°). Watch the chase:

- **∠MBI = ∠MBC + ∠CBI.** Now ∠MBC and ∠MAC subtend the same arc MC, so ∠MBC = ∠MAC = α. And BI bisects angle B, so ∠CBI = β. Hence **∠MBI = α + β.**
- **∠MIB** is an *exterior* angle of triangle ABI at vertex I (since A, I, M are collinear). An exterior angle equals the sum of the two remote interior angles: ∠MIB = ∠IAB + ∠IBA = α + β. Hence **∠MIB = α + β.**

Triangle MBI has two equal angles, so it's isosceles: **MB = MI.** By the mirror-image argument, MC = MI. Done.

Notice the flavor: no measurement, no algebra, just relentless substitution of equal angles. That's 80% of olympiad geometry. A classroom student *could* produce this, but they were never trained to reach for "let me name the half-angles and chase."

---

## Tool 3: Mass point geometry (and Ceva / Menelaus)

Standard class makes you grind through similar triangles to find ratios on a cevian (a segment from a vertex to the opposite side). Competitors often skip all of it with a physics trick: hang weights on the vertices and let the figure *balance*.

> **Mass points.** Place a mass at each vertex. A point that balances two masses sits on the segment between them, dividing it *inversely* to the masses (heavier end = shorter segment). At any balance point, masses add. The whole figure's behavior follows from a few balance conditions. [[5]](https://mathcircle.berkeley.edu/sites/default/files/archivedocs/2015/lecture/MassPointGeometry_8Sep2015.pdf) [[6]](https://en.wikipedia.org/wiki/Mass_point_geometry)

**Worked example.** In triangle ABC, point D lies on BC with BD : DC = 3 : 1, and point E lies on AC with AE : EC = 2 : 3. Cevians AD and BE meet at P. Find AP : PD and BP : PE.

Assign masses so each given ratio balances:

- E is on AC with AE : EC = 2 : 3. Mass is inverse to distance, so mass(A) : mass(C) = 3 : 2.
- D is on BC with BD : DC = 3 : 1, so mass(B) : mass(C) = 1 : 3.

Make mass(C) agree in both: take **mass(C) = 6.** Then mass(A) = 9 and mass(B) = 2.

Quick sanity check: at D the mass is mass(B) + mass(C) = 8, and BD : DC = mass(C) : mass(B) = 6 : 2 = 3 : 1 ✓. At E the mass is mass(A) + mass(C) = 15, and AE : EC = mass(C) : mass(A) = 6 : 9 = 2 : 3 ✓.

Now P balances A against D, so
$$AP : PD = \text{mass}(D) : \text{mass}(A) = 8 : 9.$$
And P balances B against E, so
$$BP : PE = \text{mass}(E) : \text{mass}(B) = 15 : 2.$$

Two ratios, no similar triangles, no coordinates. The rigorous theorems underneath are **Ceva's Theorem** (when do three cevians meet at one point?) and **Menelaus's Theorem** (when do three points on the sides lie on one line?), plus a trig version of Ceva for angle conditions. All standard competition equipment; none of it in the typical course. [[7]](https://en.wikipedia.org/wiki/Ceva's_theorem)

---

## Tool 4: Ptolemy's Theorem

The classroom gives you the Pythagorean theorem for right triangles. Competition gives you its cousin for circles.

> **Ptolemy's Theorem.** For a quadrilateral ABCD inscribed in a circle (a *cyclic* quadrilateral), the product of the diagonals equals the sum of the products of opposite sides:
> $$AC \cdot BD = AB \cdot CD + BC \cdot DA.$$
[[8]](https://en.wikipedia.org/wiki/Ptolemy's_theorem) [[9]](https://artofproblemsolving.com/wiki/index.php/Ptolemy's_theorem)

**Worked example (the golden ratio falls out).** Take a regular pentagon ABCDE with side length s and diagonal length d. Look at the cyclic quadrilateral ABCD: its sides are AB = BC = CD = s and DA = d (a diagonal), and its diagonals are AC = d and BD = d. Ptolemy says
$$AC \cdot BD = AB \cdot CD + BC \cdot DA \implies d \cdot d = s \cdot s + s \cdot d \implies d^2 - sd - s^2 = 0.$$
Solving for d,
$$d = \frac{s(1 + \sqrt 5)}{2} = \varphi \, s,$$
the **golden ratio** times the side. The pentagon's diagonal-to-side ratio is φ — a clean fact most people never see derived, dropping out of one theorem in two lines.

---

## Tool 5: The triangle "cheat sheet" facts

Standard trig class gives you the Law of Sines as `a/sin A = b/sin B`. Competition uses the *extended* version and a small library of area formulas that turn geometry problems into one-line computations:

- **Extended Law of Sines:** `a / sin A = 2R`, where R is the **circumradius**. This directly connects side lengths, angles, and the circumscribed circle.
- **Area = rs:** the area of a triangle equals its inradius r times its semiperimeter s = (a+b+c)/2.
- **Area = abc / (4R):** ties area to the three sides and the circumradius.
- **Heron's formula:** Area = √( s(s−a)(s−b)(s−c) ), area straight from the three sides.

Each of these is a bridge a competitor crosses without thinking. Most classrooms teach at most Heron's, and often not even that.

---

## The other route: "bashing" with algebra

Sometimes the slick synthetic insight won't come, and competitors fall back on raw computation — affectionately called **bashing**. These methods trade cleverness for grind, and knowing them means you're never truly stuck:

- **Coordinate bashing:** drop the figure onto the xy-plane, pick smart coordinates (put a right angle at the origin), and compute. You did a little of this in school; competitors do it as a deliberate strategy.
- **Trig bashing:** name the angles, unleash the Law of Sines/Cosines and angle-addition formulas, and push symbols until the claim falls out.
- **Complex numbers:** place the points on the unit circle in the complex plane. Rotations become multiplication, "these four points are concyclic" and "these three are collinear" become clean algebraic conditions. This is a genuinely college-level idea used routinely by olympiad students.
- **Barycentric coordinates:** a coordinate system built *from the triangle itself*, in which the incenter, centroid, and circumcenter have memorable addresses and cevian/concurrency problems become determinant calculations.

The mark of a strong competitor is choosing well: a one-line synthetic kill when you can see it, a reliable bash when you can't.

---

## A side-by-side summary

| | **Standard high school geometry** | **Competition geometry** |
|---|---|---|
| **Goal** | Verify a given statement | Discover what's true, then prove/compute it |
| **Proof style** | Two-column, named reasons | Paragraph proofs, or just an integer answer |
| **Core skill** | Apply the named theorem | Angle chase, build auxiliary points, spot patterns |
| **Circle tools** | Inscribed angle theorem | Power of a Point, radical axes, Ptolemy |
| **Ratio tools** | Similar triangles | Mass points, Ceva, Menelaus |
| **Triangle tools** | Pythagoras, basic trig | Extended Law of Sines, R = abc/4K, r·s area, Heron |
| **Advanced** | (none) | Spiral similarity, homothety, inversion, complex/barycentric coordinates |
| **Time per problem** | A few minutes | 3 min (AMC) → 12 min (AIME) → 1+ hour (olympiad) |

The "advanced" row hints at where this leads. **Homothety** (uniform scaling from a center) and **spiral similarity** (rotate-and-scale) explain why certain points are collinear or certain circles are tangent. **Inversion** is a transformation that turns lines and circles into each other, often converting a hideous circle problem into a trivial line problem. These are the heavy artillery of the IMO, and they're built from the very same plane geometry you started with.

---

## So how do you start?

You are not missing a math gene; you're missing a vocabulary and a set of habits. A practical on-ramp:

1. **Practice pure angle chasing** until labeling a diagram with α, β, γ is automatic.
2. **Memorize and *use* the five tools above** — Power of a Point, the arc-midpoint lemma, mass points, Ptolemy, and the extended-trig facts — on real old contest problems.
3. **Work past AMC and AIME problems** (freely available online) with full solutions, and when stuck, read the solution and ask "what would have made me see that?"
4. **Then graduate to writing proofs**, where the goal shifts from the answer to the *argument*.

The punchline: competition geometry isn't a harder, alien subject sitting on top of your high school class. It's the *same Euclidean plane*, explored with sharper tools and a more adventurous attitude. Everything above was provable with facts you already trust — congruent triangles, the inscribed angle, a circle and a few lines. The competitors just learned to *look* differently. Once you do too, the diagrams stop being intimidating and start being fun.

---

## Sources

1. [Power of a Point Theorem — Art of Problem Solving Wiki](https://artofproblemsolving.com/wiki/index.php/Power_of_a_Point_Theorem)
2. [Power of a point — Wikipedia](https://en.wikipedia.org/wiki/Power_of_a_point) (and [Cut-the-Knot](https://www.cut-the-knot.org/pythagoras/PPower.shtml))
3. [Evan Chen, "The Incenter/Excenter Lemma" (the "Fact 5" handout)](https://web.evanchen.cc/handouts/Fact5/Fact5.pdf)
4. [Incenter–excenter lemma — Wikipedia](https://en.wikipedia.org/wiki/Incenter%E2%80%93excenter_lemma) (and [AoPS Wiki](https://artofproblemsolving.com/wiki/index.php/Incenter/excenter_lemma))
5. [Tom Rike, "Mass Point Geometry" — Berkeley Math Circle](https://mathcircle.berkeley.edu/sites/default/files/archivedocs/2015/lecture/MassPointGeometry_8Sep2015.pdf) (and [UCLA ORMC AMC 10/12 handout](https://circles.math.ucla.edu/circles/lib/data/Handout-4243-4032.pdf))
6. [Mass point geometry — Wikipedia](https://en.wikipedia.org/wiki/Mass_point_geometry)
7. [Ceva's theorem — Wikipedia](https://en.wikipedia.org/wiki/Ceva's_theorem)
8. [Ptolemy's theorem — Wikipedia](https://en.wikipedia.org/wiki/Ptolemy's_theorem) (and [Cut-the-Knot](https://www.cut-the-knot.org/proofs/ptolemy.shtml))
9. [Ptolemy's theorem — Art of Problem Solving Wiki](https://artofproblemsolving.com/wiki/index.php/Ptolemy's_theorem)
10. [Evan Chen, "Lemmas in AoPS Geometry" (geometry "slang"/culture)](https://web.evanchen.cc/handouts/GeoSlang/GeoSlang.pdf) — context for the "Fact 5" naming and the directed-angles convention.
