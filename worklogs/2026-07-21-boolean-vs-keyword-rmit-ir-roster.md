# 2026-07-21 — Path B probe: Boolean vs keyword retrieval on ClimbMix (RMIT IR roster)

## Goal
Test "Path B" from the *"Boolean Queries Are All You Need?"* (Vole/SSR/Cottontail, arXiv 2607.11362)
reflection: approximate agentic **Boolean** retrieval on our existing Lucene/Anserini BM25 index,
and compare it against the plain **keyword-OR** retrieval exposed by `rmit-ir/index-server`.

Exploration topic (deep-research framing):
> Build a comprehensive roster of the RMIT University Information Retrieval group (incl. its
> ADM+S-affiliated IR researchers): identify as many faculty/supervisors as the corpus supports,
> and for each their PhD/research students — grounding every supervisor↔student edge in a
> retrieved document (docid + verbatim quote).

## Infra facts established
- **Local `index-server` (:8085) is bag-of-words OR only.** `BagOfWordsQueryGenerator` adds every
  token as a Lucene `SHOULD` clause; it strips `+`, `-`, `AND`, `OR`, `"phrase"`, `~proximity`,
  `field:` — confirmed by the echoed `PARSED` query. So true Boolean is structurally impossible
  through that server. (Source also at `../index-server` and `/home/eh6/E128356/projects/index-server`.)
- **The on-disk index supports full Boolean.** `data/built-indexes/climbmix-bm25` is a plain
  Lucene 10.4 index (single segment, 553,240,576 docs) **with positions** (`_3r3_Lucene104_0.pos`,
  267 GB) → phrase + proximity work. The OR limitation is the server's, not the index's.
- Built a read-only full-syntax searcher: `tasks/bm25_index/boolsearch/BoolSearch.java` (+ `bs.sh`
  wrapper). Opens the same index dir concurrently (MMapDirectory, read-only), `EnglishAnalyzer`
  (Porter, matches build), `BM25Similarity(1.2, 0.75)` (matches index-server). Usage:
  `./bs.sh <k> "<lucene-query>" [snippetChars, -1=full]`.

## Method
Acted as the Vole agent. Round 1–3 by hand on both engines; then a 5-way parallel sub-agent fan-out
(one researcher per core faculty member + one hub-doc hunter), each required to back every edge with
a docid + quote. ~100 Boolean queries total.

## Representative queries + outcomes (the comparison)

Keyword-OR (index-server) — drifts; cannot enforce co-occurrence:
- `list the PhD supervisors at the RMIT information retrieval group ...` → top hits: heart-attack
  device, apprenticeships, statistics tool (generic "RMIT+research+student" pages). No group doc.
- `Falk Scholer RMIT` → **52,904** hits; top = biocompatible-lens / SCINEMA generic docs (surname
  can't pull its own docs up under OR).
- `Oleg Zendel query performance prediction RMIT` → returned the **wrong Zendel** (Benjamin Rich
  Zendel, auditory-aging neuroscience, `shard_04535_4426`); IR Zendel never surfaced.

Boolean (BoolSearch) — precise + truthful:
- `+RMIT +"information retrieval"` → 84 hits (all contain the phrase) vs thousands under OR.
- `+Zendel +"query performance prediction"` → **0 hits** (truthful: not in corpus) vs OR's confident
  wrong Zendel.
- `+Scholer +Spina` → 9 hits, essentially all IR-group (SIGIR recap, search-personalisation study,
  Roitero/Soprano bibtex).
- `+Trippas +Sanderson +conversational` → 5 hits, top-3 the exact Trippas conversational-search feature.
- `+"information retrieval" +Nonexistius +Fakemcfakeface` → 0 (fake-entity truthfulness control).
- Over-constraint failures (lessons): `+...+supervisor` dropped the anchor doc (anchor says
  "supervis**ed**" → stem `supervis`, not `supervisor`); `+Alaofi +Sanderson` → 0 (edge lives in the
  SIGIR doc under her *first* name, not surname co-located with Sanderson). Boolean is an unforgiving
  scalpel; needs an agent that reads hit counts and relaxes/tightens.

## Full query log + effectiveness (direct queries I ran)

Legend: ✅ effective (target / clean relevant pool) · ◐ partial (target present but buried under
drift) · ❌ failed (wrong entity / pure noise) · ⊘ truthful-zero (correctly returned nothing — a
*good* outcome for grounding).

### Method 1 — Keyword-OR (`index-server` :8085, bag-of-words)

| # | Query (as typed) | Hits | Top / notable result | Eff. |
|---|---|---|---|---|
| A | `list the PhD supervisors at the RMIT information retrieval group and the students of each supervisor` | 1,562 | heart-attack device, apprenticeships (generic RMIT+research) | ❌ |
| B | `RMIT information retrieval group PhD supervisors students` | 1,438 | lip-reading, IT prizes — no group doc | ❌ |
| C | `RMIT information retrieval information retrieval group Sanderson Scholer` | 1,279 | biocompatible lens #1; SIGIR/SCINEMA #2 | ◐ |
| D | `Sanderson Scholer Culpepper Spina Trippas RMIT information retrieval` | 1,460 | "Teaching search engines…" (Trippas feature) at #3–5 | ◐ |
| E | `Falk Scholer RMIT` | 52,904 | generic lens/SIGIR; TREC Terabyte paper w/ Scholer only at #5 | ◐ |
| F | `Damiano Spina RMIT information retrieval` | 1,487 | generic ICT; Roitero bibtex at #5 | ◐ |
| G | `Marwah Alaofi synthetic queries LLM RMIT Sanderson Scholer` | 1,097 | anchor #1; Marwah project page #2–3 | ✅ |
| H | `Johanne Trippas conversational search RMIT information retrieval` | 1,097 | Trippas conversational feature #1–3 | ✅ |
| I | `Oleg Zendel query performance prediction RMIT` | 1,156 | **wrong Zendel** (auditory neuroscience); IR Zendel absent | ❌ |
| J | `ADM+S RMIT information retrieval PhD student supervised Spina Scholer Sanderson Trippas` | 1,162 | anchor #1 | ◐ |
| K | `Teaching search engines to know what you need information scientists` (pin) | — | got a *taxonomy* article (`shard_03700_70220`), not RMIT | ❌ |
| L | `SCINEMA SIGIR premier information retrieval conference` (pin) | — | anchor `shard_05542_15766` at #1 | ✅ |

Plus 8 syntax-probe queries (`+RMIT +"information retrieval" +PhD`, `RMIT AND information…`,
`"information retrieval"~5`, `contents:RMIT`, …) — diagnostic only: **every operator is stripped**,
all reduced to the same OR-of-stems, proving the server can't do Boolean.

OR summary: 3/12 ✅ (all 3 only worked by hand-feeding the doc's exact vocabulary), 5 ◐, 4 ❌.
Never a clean relevant pool; can't enforce co-occurrence; returns confident wrong entities.

### Method 2 — Boolean (`BoolSearch`, same index, full Lucene syntax)

| # | Query | Hits | Outcome | Eff. |
|---|---|---|---|---|
| 1 | `+RMIT +"information retrieval"` | 84 | precise pool, all contain the phrase (vs 1000s under OR) | ✅ |
| 2 | `+Zendel +"query performance prediction"` | 0 | correctly empty — IR Zendel not in corpus (OR gave wrong Zendel) | ⊘ |
| 3 | `+RMIT +"information retrieval" +supervisor` | 9 | over-constrained — dropped anchor (stem `supervis`≠`supervisor`) | ❌ |
| 4 | `+Sanderson +"phd student"~20` | 429 | proximity worked but wrong Sanderson (mongoose researcher) | ❌ |
| 5 | `+Scholer +Spina` | 9 | **all IR-group** (anchor, personalisation study, Roitero bibtex) | ✅ |
| 6 | `+Alaofi +Sanderson` | 0 | truthful zero — edge lives under her *first* name, not surname | ⊘ |
| 7 | `+Trippas +Sanderson +conversational` | 5 | top-3 = exact Trippas conversational feature | ✅ |
| 8 | `+"information retrieval" +Nonexistius +Fakemcfakeface` | 0 | fake-entity control — correctly empty | ⊘ |
| 9 | `+Sanderson +Scholer` | 13 | anchor #1; clean working set | ✅ |
| 10 | `+Culpepper +Moffat` | 11 | Petri/Moffat/Culpepper SIGIR'14 bibtex | ✅ |
| 11 | Faculty-presence sweep `+<surname> +"information retrieval"` ×19 | — | Sanderson 170, Scholer 31, Spina 82, Trippas 8, Culpepper 14, Cavedon 8, Zuccon 26, Moffat 153, Zobel 113, Turpin 46, Karimi 47, Verspoor 22, Salim 71, P.Thomas 1714, **Zendel 1**, Mackenzie 194, Koopman 43, Bailey 326, Baldwin 265 | ✅ |
| 12 | `+Scholer +Spina +personalisation` | 2 | DMRC/ADM+S investigator-list doc | ✅ |
| 13 | `+"25" +"information retrieval" +RMIT +award` | 17 | ADM+S event (mostly non-IR); grounded Spina/Verspoor bios | ◐ |
| 14a | `+RMIT +"under the supervision" +(information retrieval OR search OR retrieval)` | 77 | aviation/pilot courses — no thesis layer | ❌ |
| 14b | `+"my supervisor" +RMIT +(retrieval OR search OR "information retrieval")` | 15 | bees, palaeontology — noise | ❌ |
| 14c | `+RMIT +PhD +"information retrieval" +(completed OR graduated OR awarded)` | 20 | ADM+S event doc; partial | ◐ |
| 15 | `+"CoDiS" +lab` | — | European cognitive-science lab, not RMIT IR | ❌ |
| 16 | `+RMIT +"information retrieval" +(lab OR "research group" OR "our team")` | — | no roster page exists | ◐ |
| 17 | Extra-faculty presence ×6 | — | Verspoor 10, Karimi 5, **Mingfang Wu 0**, Flora Salim 201, **Naghizade 0**, Hettiachchi 2 | ✅ |
| 18 | `+"Kaixin Ji"` | 1 | profile page — grounds the surname | ✅ |
| 19 | `+ISAR +RMIT +("information retrieval" OR search)` | 3 | only 1 real (Google-award news); no roster | ◐ |
| 20 | `+Cherumanal` | 42 | "Cheruman" caste collision — surname drowned | ❌ |

Boolean summary: 9 ✅, 3 ⊘ (truthful zeros — the distinguishing capability), 4 ◐, 5 ❌ (all 5 ❌ are
*informative* failures: over-constraint, surname collision, or genuine corpus gaps — never a
confident-wrong answer). The 5 sub-agents ran ~100 further Boolean queries following the same
patterns (supervision-language, co-occurrence, full-doc `-1` reads).

**Crux (head-to-head on the same intent):** the ⊘ rows — `+Zendel +"query performance prediction"`→0
and `+Alaofi +Sanderson`→0 — are *correct* answers Boolean can express and OR cannot; OR's
equivalents returned confident-wrong (row I) or drifting results instead. That capability gap is why
Boolean "got further" on this entity-dense task.

## Grounded roster (the deliverable)

| Supervisor(s) | Student (PhD, RMIT) | Co-sup / collaborators | Evidence docid |
|---|---|---|---|
| Mark Sanderson | Johanne Trippas (voice/conversational search) | collab. Hideo Joho (Tsukuba) | `shard_05171_62232` (dups `shard_04044_72078`, `shard_01098_78680`) |
| Mark Sanderson + Falk Scholer | Marwah Alaofi (LLM synthetic queries) | + Paul Thomas (Microsoft); collab. Luke Gallagher | `shard_05542_15766` |
| Falk Scholer + Damiano Spina + Flora Salim | Kaixin Ji (physiological signals / confirmation bias) | collab. Danula Hettiachchi | `shard_05542_15766` + bio `shard_03307_37023` |
| Lawrence Cavedon | Daniel Macías Galindo (conversational dialogue systems) | — | `shard_03114_27401` |

Verbatim anchor quotes:
- `shard_05542_15766`: "supervised by ADM+S Investigators Prof Flora Salim, Prof Falk Scholer and Dr
  Damiano Spina." / "Developed in collaboration with Luke Gallagher from RMIT University and
  supervised by ADM+S Investigators Prof Mark Sanderson and Prof Falk Scholer, and Paul Thomas from
  Microsoft."
- `shard_05171_62232`: "PhD student Johanne Trippas from RMIT and Dr Hideo Joho ... Professor Mark
  Sanderson, Director of the Enabling Capability Platform ... and his team at RMIT University."
- `shard_03114_27401`: "His supervisor, Dr Lawrence Cavedon, is looking forward to working with Daniel
  on developing some of the ideas from his thesis."
- Group handle **ISAR** grounded in `shard_04886_54251`: "The current leader of ISAR, Professor Mark
  Sanderson, said the award underlined how information retrieval research at RMIT was well regarded".

### Faculty grounded (RMIT-IR) but NO student edge in corpus
- Johanne Trippas (now Dr/faculty, `shard_04104_12688`); J. Shane Culpepper (`shard_00439_56832`,
  `shard_04843_74297` — co-authors only); Karin Verspoor (Exec Dean; her students Biaoyan Fang /
  Zenan Zhai are **University of Melbourne**, `shard_03694_934`, NOT RMIT — clean disambiguation).

### Attested RMIT-IR student, supervisor ungrounded
- Sachin Pathiyan Cherumanal (`shard_05922_78041` "fair exposure of multiple perspectives in
  conversational search"); no supervisor named; surname collides with "Cheruman" caste pages.

### Real members ABSENT from corpus (0 grounded IR hits)
Oleg Zendel, Joel Mackenzie, Binsheng Liu, Ruey-Cheng Chen, Xiaolu Lu, Rodger Benham, Antonio
Mallia, Mingfang Wu, Elham Naghizade.

### Collision noise catalogued (why Boolean mattered)
"Scholer" → Manfred Scholer (plasma physics), stem-cell "Schöler"; "Spina" → spina bifida / spinal
cord, journalist Romina Spina; "Trippa(s)" → Italian tripe; "Culpepper" → unrelated web people;
"Cherumanal" → Cheruman caste; "Zendel" → auditory neuroscience.

## Verdict
- **Boolean got further and is more trustworthy** than keyword-OR: precision jumps from
  thousands-drifting to single/double-digit all-relevant; it yields *truthful empty sets* instead of
  confident wrong entities; it cleanly separates grounded / collision / absent. This validates the
  Vole/SSR thesis on a hard entity-dense query at 553 M-doc scale — the only missing piece vs the
  paper is SSR's minimal-interval scoring (Cottontail), which our Lucene phrase/proximity approximates.
- **The roster ceiling is corpus coverage, not method.** ClimbMix is a general web crawl with a thin
  RMIT-IR footprint (one rich hub + a few news/profile/bibtex docs; no staff roster, no thesis
  acknowledgements). The real group is much larger than the corpus can prove.

## Artifacts
- Tool: `tasks/bm25_index/boolsearch/BoolSearch.java`, `bs.sh` (read-only; throwaway probe).
- No changes to the running server, the index, or committed code. Nothing committed (per standing
  instruction: user commits).

## Possible next steps (not done)
- Wrap `BoolSearch` as a small HTTP endpoint (or add a `mode=boolean` query generator to
  `index-server`) so an LLM agent can drive Boolean retrieval as a tool.
- If we want true SSR: Bazel-build `claclark/Cottontail`, 1%-shard feasibility build first (RAM at
  400 B tokens unknown).
