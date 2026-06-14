# Three AI startup ideas that ride the capability curve

*Brainstormed in the taste of [Cal AI](https://techcrunch.com/2026/03/02/myfitnesspal-has-acquired-cal-ai-the-viral-calorie-app-built-by-teens/) (photo → calories, ~$40M ARR, acquired by MyFitnessPal) and [Boardy](https://techcrunch.com/2024/10/24/ai-networking-startup-boardy-raises-3m-pre-seed/) (a voice agent that networks for you, which famously [orchestrated its own $8M round](https://americanbazaaronline.com/2025/01/15/ai-networking-agent-boardy-secures-8-million-investment-all-on-its-own458350/)).*

## The selection rule I used

Your hard constraint — *"a technical advantage from AI features only enabled now that will improve as foundational models get better"* — is the whole game. The best version of that bet is to build on a capability that is **already shipping but still visibly bad**, so every model release upgrades your product for free. I picked three ideas, each on a *different* such curve:

| Idea | Capability curve it rides | What gets better every model release |
|---|---|---|
| **1. Mise** — real-time cooking coach | Streaming multimodal (live video+voice in, voice out) | Latency, hands/ingredient recognition, interrupt handling |
| **2. Owed** — proactive money-recovery agent | Agentic execution (computer-use + voice phone calls + tools) | Task success rate on messy web forms & call trees |
| **3. Dry Run** — high-stakes conversation rehearsal | Real-time expressive voice + emotional prosody | Realism of the simulated counterparty, quality of live coaching |

I deliberately **avoided** the spaces that are already crowded in mid-2026 — DTC health/longevity ([Superpower, Function Health, One Twenty](https://fitnessdrum.com/function-health-vs-insidetracker-vs-outlive-biology-vs-superpower/)) and AI wardrobe styling ([Whering, Indyx, Acloset](https://www.myindyx.com/blog/the-best-wardrobe-apps)) — and steered toward lanes with a clearer wedge. One of the three (Owed) *is* in a contested space; I kept it because the wedge is real and I'd rather be honest than pretend the field is empty.

---

## Idea 1 — **Mise**: a real-time AI sous-chef that watches you cook

**One-liner:** Prop your phone against the backsplash; an AI watches your hands and the pan in real time and talks you through the recipe — adjusting to what you're *actually* doing, not what the recipe assumed.

### The problem
Recipes are static, but cooking is a live, hands-busy, eyes-busy activity. You can't scroll a greasy phone mid-sear, you don't know if your onions are "translucent" yet, you dumped in too much salt, or your pan is the wrong size. Every home cook hits the same failure modes — bad timing, ambiguous doneness, no recovery when something goes wrong. Cal AI proved consumers will point a camera at food daily and pay for it; cooking is the same camera, pointed 20 minutes earlier.

### How it works (technically)
- **Core loop:** a streaming multimodal session — continuous video frames + microphone in, spoken guidance out — built on a **real-time multimodal model** like [Gemini 3.1 Flash Live](https://www.marktechpost.com/2026/03/26/google-releases-gemini-3-1-flash-live-a-real-time-multimodal-voice-model-for-low-latency-audio-video-and-tool-use-for-ai-agents/), which streams video at ~1 fps, returns raw PCM audio (no separate TTS hop), holds session memory, and supports tool calls — or the OpenAI Realtime API as a second provider. ([Live API docs](https://ai.google.dev/gemini-api/docs/live-api).)
- **State machine over the model:** the recipe is a graph of steps with entry/exit conditions ("onions translucent", "internal temp 63°C"). A lightweight orchestrator keeps the model anchored to the current step, fires timers, and interrupts you ("kill the heat — it's about to catch") rather than free-associating. The model is the perception+language layer; *you* own the control logic, which is what makes it not a thin wrapper.
- **Vision specialization:** fine-tune / few-shot a doneness + ingredient-state classifier (sear color, sauce reduction, dough windowpane) layered on the foundation model's general vision, so the product is sharper than raw GPT-vision and improves as you collect data.
- **APIs/integrations:** recipe corpora and nutrition via **Spoonacular / Edamam**; grocery checkout via **Instacart Developer Platform**; **smart-thermometer BLE** (Combustion/Meater) and **smart-plug/oven** APIs for closed-loop "I'll turn the burner down for you"; **HealthKit/Cal AI-style** logging so a cooked meal auto-logs macros.
- **Stack:** Swift/Kotlin native (camera + on-device VAD for barge-in), WebRTC/WebSocket transport to the model, a Python/TypeScript orchestrator, Postgres for recipe graphs + user skill profile.

### Why people want it & the viral hook
It's a *demo that sells itself* on TikTok ("AI saved my risotto" / "watch it catch my burning garlic"). The retention hook is a **skill graph**: it remembers you over-salt and under-rest meat, and coaches you out of it — so it gets more valuable the more you cook, like a personal trainer for the kitchen.

### Why it gets better automatically
Today's ceiling is latency and fine-grained visual state ("is *this* specific sauce reduced?"). Both are exactly what each realtime-multimodal release improves. You ship the product mediocre, and Google/OpenAI hand you upgrades every quarter.

### Competitors (who's already here)
- **Hardware robots, not software:** [Posha](https://en.wikipedia.org/wiki/Posha_(company)) (countertop cooking robot with overhead camera + CV, $8M Series A), Moley Robotics, June ovens — all expensive appliances, not a free app on the phone you own.
- **Recipe/UX apps:** SideChef, Whisk/Samsung Food, Tasty — step-by-step and some voice, but **scripted, not perceptive**; they don't watch your pan.
- **Wedge:** nobody owns the software-only, *perceptual, real-time* coach. That lane is open.

---

## Idea 2 — **Owed**: an agent that gets back money you're passively owed

**One-liner:** Connect your email, bank, and calendar once; an always-on agent finds the refunds, rebates, and compensation you're entitled to but never claim — then actually files them via web forms, emails, and phone calls.

### The problem
Consumers leak money constantly and never recover it: price-drop refunds, late-delivery and missing-item refunds, **flight/train delay compensation** (EU261/UK), unredeemed rebates and class-action settlements, duplicate/erroneous subscription charges, medical-bill coding errors, and bank fees. The reason nobody claims it isn't laziness — it's that each claim is a 25-minute slog through a different portal or hold queue. That friction is precisely what agents now dissolve.

### How it works (technically)
- **Sensing layer:** read-only connectors — **Gmail/Outlook APIs** (receipts, shipping notices, "your flight is delayed"), **Plaid** for transactions ([Plaid PFM](https://plaid.com/solutions/personal-financial-management/)), calendar for travel. A classifier continuously scans for *claimable events* and estimates expected recovery + deadline.
- **Acting layer (the hard, defensible part):** an **agentic executor** that completes the claim end-to-end — a **computer-use / browser agent** to navigate merchant and airline portals and fill forms, an **email agent** to send templated disputes, and a **voice agent** (Vapi/Bland/Twilio + a realtime voice model) to sit on hold and talk to support lines. Same primitives proven by [Pine AI](https://siliconangle.com/2026/05/06/pine-ai-aims-consumer-ai-agent-complex-customer-service-interactions/), which already makes calls, sends emails and navigates UIs.
- **Trust & control:** human-in-the-loop approval for anything that moves money or signs a claim; a per-merchant "playbook" memory so each successful claim makes the next one cheaper and more reliable (your moat is the **playbook + success-rate dataset**, not the model).
- **Business model:** success-based — take 15–25% of money recovered, mirroring the "only pay if it works" pricing already normal in this category. Zero recovery, zero charge → trivial to try.
- **Stack:** TypeScript orchestrator, a computer-use model (Claude/Gemini computer-use) in a sandboxed headless browser, Temporal for long-running/retryable claim workflows, Plaid + Gmail + Twilio, encrypted secrets vault, Postgres + a vector store of merchant playbooks.

### Why people want it & the viral hook
The hook is a number: *"Owed found me $312 you didn't know you were owed."* That's a screenshot people post. It's the Cal AI dopamine loop (a satisfying number, repeatedly) applied to your bank account, and it runs while you sleep.

### Why it gets better automatically
The bottleneck is **agent reliability on messy, hostile web flows and phone trees** — the single most-invested capability in the industry right now. Every jump in computer-use success rate directly raises your recovery rate and margin. You're literally short-volatility on "agents getting more reliable."

### Competitors (this space is contested — be honest)
- **[Pine AI](https://www.19pine.ai/blog/best-management-and-subscription-cancellation-apps):** the strongest — autonomous calls/emails/UI navigation, ~$400 avg saved, claims 93% success on complex negotiations. Reactive: *you* ask it to negotiate a specific bill.
- **[Vibrato](https://www.getvibrato.com/):** AI calls to negotiate bills / cancel subscriptions.
- **[Rocket Money](https://www.cnbc.com/select/rocket-money-review/):** bank-linked subscription cancelation + spend tracking (Plaid), but human-assisted and narrow.
- **Platform risk:** [OpenAI shipped Plaid-powered finance in ChatGPT](https://www.americanbanker.com/news/openai-launches-personal-finance-tools-for-chatgpt-pro-users) and [Claude got bank connectivity via Era (May 2026)](https://www.mindstudio.ai/blog/ai-personal-finance-chatgpt-plaid-claude-agents) — the assistants themselves are creeping in.
- **Wedge:** everyone above is **reactive** (negotiate *this* bill, cancel *this* sub). Owed is **proactive money-*recovery*** — it discovers entitlements you never knew existed and chases them autonomously. Different verb, different trigger, and a defensible per-merchant playbook dataset. The old reactive players (Paribus, Sift) died pre-agent; the *autonomous* recovery version is newly buildable.

---

## Idea 3 — **Dry Run**: rehearse the scary conversation before it happens

**One-liner:** Practice your salary negotiation, your "I need to break up with this client," your visa interview, or your hard talk with a parent — out loud, against a realistic AI that plays the *other person* and coaches you on what you actually said.

### The problem
The highest-stakes moments of work and life are conversations you get exactly one shot at, with no safe place to practice. Books and ChatGPT give you *advice*; they don't let you **rehearse the live, emotional, interrupt-y reality** of the thing — the pushback, the awkward silence, the moment your voice shakes. People rehearse in the shower against an imaginary opponent. Now the opponent can talk back.

### How it works (technically)
- **The counterparty:** a **real-time expressive voice model** (Gemini Live / OpenAI Realtime, again on the [low-latency realtime curve](https://ai.google.dev/gemini-api/docs/live-api)) role-plays a persona you configure — "skeptical hiring manager," "your cost-cutting CFO," "defensive teenager." Optional **voice cloning** (ElevenLabs) of a known counterparty's vocal style, with consent, for verisimilitude.
- **The coach:** a second model analyzes the transcript *and prosody* — filler words, pace, hedging, who-talked-more, whether you anchored first in the negotiation — and gives both **live in-ear nudges** ("ask for the number") and a structured **after-action report** with a replayable timeline and "try this line instead."
- **Adaptive difficulty:** the persona escalates pushback as you improve; a scenario library (negotiation, layoffs, dating, medical advocacy, founder–investor, language practice) seeds cold-start, and a calendar integration can *detect an upcoming real meeting* and proactively offer a rehearsal.
- **Stack:** mobile native + WebRTC to the realtime model, a prosody/pace analyzer (on-device VAD + acoustic features), an LLM judge for content scoring, calendar API, ElevenLabs, Postgres for scenario graphs + progress.

### Why people want it & the viral hook
Everyone has one terrifying conversation on the calendar. The shareable artifact is the **glow-up**: "I practiced my raise ask 6 times with an AI and walked in and got 18%." High intent → high willingness to pay (a single successful raise pays for years of subscription), and it's gift-able ("send your nervous friend a rehearsal").

### Why it gets better automatically
The product is only as good as how *real and emotionally responsive* the simulated human feels — exactly the axis expressive-voice models improve on every release. Better turn-taking, interruption, and emotional range = a more useful rehearsal, with zero work from you.

### Competitors (partially crowded — differentiate on domain)
- **[Yoodli](https://yoodli.ai/):** the leader — AI roleplay personas, plus live in-call nudges on Zoom/Meet/Teams; strong in **sales, interviews, presentations, enterprise**.
- **Final Round AI:** interview prep, feature-rich but pricey; **Poised / Speakio:** delivery/speech coaching.
- **Wedge:** the incumbents own *professional* talk (sales decks, interviews). The open lane is **personal and relational high-stakes conversations** — money talks with a partner, medical self-advocacy, family conflict, immigration interviews — sold consumer (not enterprise seats), with a **counterparty-cloned** opponent and emotional-prosody coaching the work tools don't emphasize. Adjacent to Boardy's "voice agent for a human moment" insight, pointed at *preparation* instead of networking.

---

## How to choose between them

- **Fastest to a viral moment / lowest build risk → Mise.** Single clear demo, consumer camera behavior already proven by Cal AI, and the competition is $30k robots, not apps. Best "teenagers-could-ship-it, compounds-with-Gemini" bet.
- **Biggest market & clearest willingness-to-pay, but a real fight → Owed.** Money-back is the most universal value prop here; success-based pricing makes trial frictionless. But you're against funded players (Pine) and the platform owners (OpenAI/Claude) — win on the *proactive recovery* wedge and the per-merchant playbook dataset, or don't enter.
- **Highest margin & intent, narrowest-but-deep → Dry Run.** Software-only, no integrations needed to start, and people pay a lot to not bomb a one-shot moment. Avoid Yoodli's professional turf; own the personal/relational lane.

**My pick as a technical founder: Mise.** It has the cleanest "the model upgrade *is* my roadmap" story, the most defensible-yet-open competitive lane, a Cal-AI-grade viral surface, and a natural platform expansion — the same realtime-perception-coach engine generalizes to **any hands-busy physical skill** (home repair, instrument practice, physio/rehab, lab work). Build the live-multimodal coaching infrastructure once for the kitchen, then franchise it across the physical world as the models get good enough to support each new vertical.

---

### Sources
- Cal AI revenue & MyFitnessPal acquisition: [TechCrunch](https://techcrunch.com/2026/03/02/myfitnesspal-has-acquired-cal-ai-the-viral-calorie-app-built-by-teens/), [Inc.](https://www.inc.com/ben-sherry/he-built-an-ai-app-in-high-school-made-40m-and-sold-to-myfitnesspal-now-hes-aiming-even-bigger/91307748), [CNBC](https://www.cnbc.com/2025/09/06/cal-ai-how-a-teenage-ceo-built-a-fast-growing-calorie-tracking-app)
- Boardy funding (incl. AI-orchestrated round): [TechCrunch](https://techcrunch.com/2024/10/24/ai-networking-startup-boardy-raises-3m-pre-seed/), [American Bazaar](https://americanbazaaronline.com/2025/01/15/ai-networking-agent-boardy-secures-8-million-investment-all-on-its-own458350/)
- Real-time multimodal capability: [Gemini 3.1 Flash Live (MarkTechPost)](https://www.marktechpost.com/2026/03/26/google-releases-gemini-3-1-flash-live-a-real-time-multimodal-voice-model-for-low-latency-audio-video-and-tool-use-for-ai-agents/), [Gemini Live API docs](https://ai.google.dev/gemini-api/docs/live-api)
- Cooking robots: [Posha (Wikipedia)](https://en.wikipedia.org/wiki/Posha_(company))
- Money-recovery / life-admin agents: [Pine AI (SiliconANGLE)](https://siliconangle.com/2026/05/06/pine-ai-aims-consumer-ai-agent-complex-customer-service-interactions/), [Pine AI / subscription apps](https://www.19pine.ai/blog/best-management-and-subscription-cancellation-apps), [Vibrato](https://www.getvibrato.com/), [Rocket Money](https://www.cnbc.com/select/rocket-money-review/), [Plaid PFM](https://plaid.com/solutions/personal-financial-management/)
- Assistant platform creep into finance: [OpenAI + Plaid (American Banker)](https://www.americanbanker.com/news/openai-launches-personal-finance-tools-for-chatgpt-pro-users), [Claude + Era / MCP (MindStudio)](https://www.mindstudio.ai/blog/ai-personal-finance-chatgpt-plaid-claude-agents)
- Conversation coaching: [Yoodli](https://yoodli.ai/), [AI speech coaching roundup (Speakio)](https://www.speakio.ai/blog/7-best-ai-speech-coaching-apps-in-2026)
- Crowded spaces avoided: [DTC health/longevity comparison](https://fitnessdrum.com/function-health-vs-insidetracker-vs-outlive-biology-vs-superpower/), [wardrobe apps](https://www.myindyx.com/blog/the-best-wardrobe-apps)
