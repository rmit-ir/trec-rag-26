# Same Triangles, Different Game: How Competition Geometry Diverges from the Geometry You Learned in High School

If you took geometry in an American high school, you learned a real and beautiful subject: parallel lines, congruent triangles, the Pythagorean theorem, circles, and the ritual of the two-column proof. Then you may have heard that kids do "geometry" at competitions like the [AMC, AIME, and USAMO](https://en.wikipedia.org/wiki/American_Invitational_Mathematics_Examination) — and that it's somehow a different beast. They're working with the *same* points, lines, and circles you know. So why does a contest geometry problem look like it's written in a foreign language?

The short answer: the **objects** are identical, but the **toolbox** and the **goal** are not. School geometry hands you a modest set of tools and mostly asks you to *verify* facts that are already laid out for you. Competition geometry hands you a much larger toolbox — and then hides the key fact you need behind three layers of structure you have to *discover* yourself.

This post is a tour of that gap, with worked examples of the specific theorems and techniques that contest students lean on constantly but that almost never appear in a standard classroom.

---

## Two different jobs

Start with what the standard curriculum actually covers. The [Common Core High School Geometry standards](https://www.thecorestandards.org/Math/Content/HSG/) — the backbone of most US courses — are built around: congruence via rigid motions, similarity, right-triangle trigonometry (SOHCAHTOA), circle theorems, coordinate geometry, and geometric constructions, all wrapped in the practice of writing proofs. It's a coherent, foundational toolkit.

Notice what the job *is* in that setting. A typical problem says: "Given that ABCD is a parallelogram, prove that the diagonals bisect each other," or "Find x," where x is one unknown in a figure that's mostly handed to you. The figure is cooperative. The path is usually a short chain of definitions and a couple of named theorems. Success means producing a tidy, valid justification.

Competition geometry keeps the axioms but changes the job. As problem-solving guides note, contest geometry deliberately reaches for "much more advanced and varied techniques" than the classroom — power of a point, trigonometric identities, ratio theorems, and at the high end inversion, projective methods, and barycentric coordinates — none of which are part of the standard curriculum ([Art of Problem Solving overview](https://artofproblemsolving.com/wiki/index.php/Ptolemy's_theorem); [AlphaStar / Think Academy contest guides](https://www.thethinkacademy.com/blog/all-about-aime-qualification-competition-difficulty-and-key-knowledge-points/)). And the job is no longer "verify the obvious step." It's: *the answer depends on a relationship that isn't drawn in the figure, and your task is to summon it.* Often that means literally adding a line, point, or circle that wasn't there — the famous "auxiliary construction" — and the whole problem collapses the moment you find the right one.

Here's the contrast in one table:

| | Standard high-school geometry | Competition geometry |
|---|---|---|
| **Objects** | Points, lines, triangles, circles | Identical |
| **Core tools** | Congruence, similarity, Pythagoras, SOHCAHTOA, basic circle theorems | All of those, *plus* power of a point, Ptolemy, Ceva/Menelaus, mass points, directed angles, extended law of sines, inversion… |
| **Typical task** | Verify a stated fact; solve for one unknown | Discover a hidden relationship; find a clever construction |
| **Proof style** | Two-column, definition-driven | Free-form synthesis; many valid paths |
| **What's rewarded** | Correctness and rigor | Correctness *and* insight/economy |
| **Calculators / formulas** | Often allowed/encouraged | Banned; everything is exact and by hand |

Let's make the "bigger toolbox" concrete. Below are four tools — each one a workhorse of contest geometry, each one essentially absent from the standard course.

---

## Tool 1: Power of a Point — the circle theorem the curriculum stops just short of

You learned the [inscribed angle theorem](https://www.thecorestandards.org/Math/Content/HSG/C/) and maybe that two chords can be related. Competition students use a sharper, unified version called the **Power of a Point**.

**The theorem.** Fix a point $P$ and a circle. Draw *any* line through $P$ that meets the circle at two points, $X$ and $Y$. Then the product $PX \cdot PY$ is the *same* for every such line — it's an invariant of the point and circle, called the power of the point ([AoPS Wiki: Power of a Point](https://artofproblemsolving.com/wiki/index.php/Power_of_a_Point_Theorem)). Three flavors:

- **Two chords** crossing inside the circle at $P$: $PX \cdot PY = PZ \cdot PW$.
- **Two secants** from an external point $P$: $PA \cdot PB = PC \cdot PD$ (each product uses the near and far intersection).
- **Tangent–secant**: if $PT$ is tangent, $PT^2 = PA \cdot PB$.

That last identity — *tangent squared equals near times far* — is the one classrooms almost never give you, and it trivializes a whole genre of problems.

**Worked example.** From an external point $P$, a tangent touches a circle at $T$ with $PT = 6$. A secant from $P$ passes through the circle, hitting it first at $A$ with $PA = 4$, then exiting at $B$. Find $AB$.

By power of a point, $PT^2 = PA \cdot PB$, so
$$36 = 4 \cdot PB \implies PB = 9, \qquad AB = PB - PA = 9 - 4 = 5.$$

No coordinates, no trig, no calculator — one line. In the standard curriculum you'd likely be reaching for the Pythagorean theorem and the radius, setting up a messier system. The contest tool sees straight through it. *(Verified numerically.)*

---

## Tool 2: Ptolemy's Theorem — and why the golden ratio falls out of a pentagon

**The theorem.** If a quadrilateral $ABCD$ is **cyclic** (all four vertices lie on one circle), then the product of its diagonals equals the sum of the products of opposite sides ([AoPS Wiki](https://artofproblemsolving.com/wiki/index.php/Ptolemy's_theorem); [Wikipedia](https://en.wikipedia.org/wiki/Ptolemy%27s_theorem)):
$$AC \cdot BD = AB \cdot CD + BC \cdot DA.$$

Most high-school courses never mention this, yet it's one of the most useful metric relations in all of contest geometry — and the related **Ptolemy's inequality** (with "$\le$" for *any* quadrilateral, equality exactly when cyclic) is a Swiss-army knife for olympiad bounds.

**Worked example — the regular pentagon.** Take a regular pentagon $ABCDE$. Every vertex lies on the circumscribed circle, so any four of them form a cyclic quadrilateral. Let the side length be $s$ and the diagonal length be $d$. Look at the cyclic quadrilateral $ABCD$:

- sides: $AB = BC = CD = s$, and $DA$ is a diagonal, so $DA = d$;
- diagonals of this quadrilateral: $AC = d$ and $BD = d$.

Ptolemy says $AC \cdot BD = AB \cdot CD + BC \cdot DA$:
$$d \cdot d = s \cdot s + s \cdot d \implies d^2 - s\,d - s^2 = 0.$$

Solve for the ratio $\varphi = d/s$ (divide by $s^2$): $\varphi^2 - \varphi - 1 = 0$, giving
$$\frac{d}{s} = \frac{1 + \sqrt{5}}{2} \approx 1.618 — \text{the golden ratio.}$$

The diagonal-to-side ratio of a regular pentagon *is* the golden ratio, and Ptolemy delivers it in three lines with no trigonometry. *(Verified numerically: a unit-circle pentagon gives ratio 1.6180339887…)* This is the flavor of competition geometry — a famous constant materializing out of a single, well-chosen application of a tool the classroom never handed you.

---

## Tool 3: Mass Points — borrowing physics to crush ratio problems

Here's a classic setup. In triangle $ABC$, a **cevian** is a segment from a vertex to the opposite side. Two cevians cross inside the triangle, and you're asked for the ratio in which they cut each other. In school you might grind through similar triangles or set up coordinates. Competition students often reach for **mass point geometry**: pretend the vertices are physical masses, and use the lever principle (torque balance) to read off ratios almost instantly. It's the same answer area-ratio and Ceva-style arguments give, repackaged as statics.

**The rule.** Place a mass at each vertex so that every cevian balances at the point where masses on either side are inversely proportional to their distances. On a segment, $\text{mass}_X \cdot (\text{length from } X) = \text{mass}_Y \cdot (\text{length from } Y)$. A balance point carries the *sum* of the two masses.

**Worked example.** In triangle $ABC$, point $D$ lies on $BC$ with $BD:DC = 2:3$, and point $E$ lies on $AB$ with $AE:EB = 3:4$. Cevians $AD$ and $CE$ meet at $P$. Find $AP:PD$.

Assign masses so each cevian balances:

- On $BC$: balance at $D$ needs $\text{mass}_B \cdot BD = \text{mass}_C \cdot DC$, i.e. $\dfrac{\text{mass}_B}{\text{mass}_C} = \dfrac{DC}{BD} = \dfrac{3}{2}$. Take $\text{mass}_B = 3,\ \text{mass}_C = 2$.
- On $AB$: balance at $E$ needs $\dfrac{\text{mass}_A}{\text{mass}_B} = \dfrac{EB}{AE} = \dfrac{4}{3}$. With $\text{mass}_B = 3$, that gives $\text{mass}_A = 4$.

Now $D$ carries $\text{mass}_B + \text{mass}_C = 5$. The cevian $AD$ balances at $P$, so
$$AP:PD = \text{mass}_D : \text{mass}_A = 5 : 4.$$

One pass of bookkeeping, no equations of lines. *(Verified numerically by intersecting the cevians in coordinates: the ratio comes out exactly 1.25 = 5/4.)* Mass points are pure competition culture — enormously practical, and entirely outside the standard syllabus.

This tool is the friendly cousin of two named theorems contest students also learn — **Ceva's theorem** (a clean criterion for when three cevians are *concurrent*, i.e. meet at one point) and **Menelaus's theorem** (the analog for when three points are *collinear*) ([Brilliant: Ceva](https://brilliant.org/wiki/cevas-theorem/); [AoPS: Menelaus](https://artofproblemsolving.com/wiki/index.php/Menelaus%27_theorem)). All three answer questions — "do these three lines meet at a point?", "do these three points lie on a line?" — that the standard course rarely even poses.

---

## Tool 4: Angle Chasing and the "directed angle" mindset

The previous three were *metric* tools (they compute lengths and ratios). The fourth is a *mindset* shift, and it's maybe the most important one.

You know the inscribed angle theorem: an angle inscribed in a circle is half its central angle, so all angles subtending the same arc are equal. In school this is one fact among many. In competition geometry, **angle chasing** — relentlessly propagating equal angles around a figure until two points are forced to lie on a common circle, or three points are forced onto a line — is a primary mode of attack.

The key reframing is the **cyclic quadrilateral test**: four points lie on a circle **if and only if** a pair of opposite angles sums to $180^\circ$ (or, equivalently, two points see a segment at equal angles from the same side). Contest students use this in *reverse*: they angle-chase to *prove* a quadrilateral is cyclic, which then unlocks Ptolemy, power of a point, and more. The figure becomes a web of "this circle exists because these angles match," and discovering a hidden circle is often the entire problem.

Experts even adopt **directed angles** (angles taken modulo $180^\circ$) so that a single argument covers every possible diagram configuration at once — sparing them the case-by-case "but what if the point is on the other side?" bookkeeping that bogs down a naive two-column proof. There is no analog of this in the standard curriculum; it's a technical convention invented precisely because contest figures are not handed to you in a fixed, cooperative position.

---

## So what's *really* different?

Step back and the pattern is clear. It isn't that competition geometry uses different axioms or some secret non-Euclidean rules — it's the same Euclidean plane the whole way down. The differences are:

1. **A bigger toolbox.** Power of a point, Ptolemy, Ceva/Menelaus, mass points, the extended law of sines ($\frac{a}{\sin A} = 2R$, tying side lengths to the circumradius), and — at the olympiad summit — inversion and projective methods. Each is a lens that makes some configurations transparent.

2. **A different goal.** School geometry mostly asks you to *justify a given step*. Contest geometry asks you to *find the step* — usually a hidden circle, a magic auxiliary line, or an invariant that nobody drew for you.

3. **Economy and exactness over machinery.** No calculators, no decimal approximations, no calculus. A golden ratio must emerge as $\frac{1+\sqrt5}{2}$, not "≈ 1.618," and the prized solution is the short, surprising one, not the brute-force coordinate slog (though "bashing" with coordinates or trig is a legitimate backup when elegance runs out).

4. **Construction as creativity.** The single most characteristic move — adding a point, line, or circle that transforms an opaque problem into an obvious one — has no real counterpart in a curriculum where the figure is always already complete.

If you found high-school geometry satisfying, the good news is that nothing you learned is wasted — inscribed angles, similar triangles, and Pythagoras are the literal foundation everything above is built on. Competition geometry just keeps building. It treats the figure not as something to verify, but as a puzzle box with a hidden mechanism, and it hands you a much larger set of keys. The fun is in finding which key turns it.

---

## Where to go next

If you want to actually pick these up, the [Art of Problem Solving wiki](https://artofproblemsolving.com/wiki/) has accessible pages on every tool above, [Brilliant](https://brilliant.org/wiki/ptolemys-theorem/) and [cut-the-knot](https://www.cut-the-knot.org/proofs/ptolemy.shtml) have interactive proofs, and past [AMC/AIME](https://en.wikipedia.org/wiki/American_Invitational_Mathematics_Examination) problems (freely archived on AoPS) let you see the tools in their natural habitat. Start by re-deriving the four examples here yourself — then go find a problem where a hidden circle is waiting to be discovered.

---

### Sources
- Common Core State Standards Initiative — *High School: Geometry*: https://www.thecorestandards.org/Math/Content/HSG/
- Art of Problem Solving Wiki — *Ptolemy's theorem*: https://artofproblemsolving.com/wiki/index.php/Ptolemy's_theorem
- Art of Problem Solving Wiki — *Power of a Point Theorem*: https://artofproblemsolving.com/wiki/index.php/Power_of_a_Point_Theorem
- Art of Problem Solving Wiki — *Menelaus' theorem*: https://artofproblemsolving.com/wiki/index.php/Menelaus%27_theorem
- Wikipedia — *Ptolemy's theorem*: https://en.wikipedia.org/wiki/Ptolemy%27s_theorem
- Wikipedia — *Menelaus's theorem*: https://en.wikipedia.org/wiki/Menelaus%27s_theorem
- Wikipedia — *American Invitational Mathematics Examination*: https://en.wikipedia.org/wiki/American_Invitational_Mathematics_Examination
- Brilliant — *Ceva's theorem*: https://brilliant.org/wiki/cevas-theorem/
- Brilliant — *Ptolemy's theorem*: https://brilliant.org/wiki/ptolemys-theorem/
- cut-the-knot — *Ptolemy's Theorem*: https://www.cut-the-knot.org/proofs/ptolemy.shtml
- Think Academy — *All About AIME* (contest scope/knowledge points): https://www.thethinkacademy.com/blog/all-about-aime-qualification-competition-difficulty-and-key-knowledge-points/

*All four worked examples in this post were verified numerically before publication.*
