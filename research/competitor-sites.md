# Competitor site teardown: AI eval orgs

Researched 2026-10-26 with WebFetch and WebSearch. **About the method:** WebFetch returns page text without stylesheets, so the visual-design notes come from markup, image names and copy, not from screenshots. Treat them as directional. Where a fetch failed, I say so.

---

## 1. METR (metr.org)

- **Hero:** "Model Evaluation & Threat Research" / "We inform the public about the risks and capabilities of advanced AI systems." CTAs: *Our research*, *Careers*. [metr.org](https://metr.org)
- **Section order:** nav (Our Work, About, Donate, Careers, Search) → hero → featured cards (an incident investigation dated Aug 26 2026, the Frontier Risk Report, a proposal, a Time Horizon 1.1 chart card, the paper) → Featured Research (tabs: General / Technical / Policy) → Partnerships logo row → Risk Assessment (dated list, each item tagged "Partnership" or "No company involvement") → links to the labs' Frontier AI Safety Policies → press logos with dates → Recent posts → footer (subscribe, contact emails, EN/ES/中文).
- **Leaderboard/chart:** No table. The flagship result is one chart, on the homepage and on [metr.org/time-horizons](https://metr.org/time-horizons/). It has toggles for log / log-linear / linear axes and for 50% / 80% success thresholds. A version label sits on it ("Time Horizon 1.1 (Current)" vs "1.0 (Mar 2025)"), along with "LAST UPDATED Sep 8 2026" and an honest "no longer actively updated" note. A task-level scatter has Exact/Jittered modes and filters by lab. The page says outright that the fit is shown "without bootstrapped confidence intervals."
- **Methodology:** The method is explained on the chart page itself: human-expert time sets each task's length, a logistic fit gives the 50%/80% crossing points, the task sources are named, there is an FAQ, and caveats are explicit ("Measurements above 16 hrs are unreliable"; model coverage is incomplete; some models were skipped).
- **Trust:** Raw YAML data, GitHub analysis code, the arXiv paper, a BibTeX copy button, and "does not accept compensation" for risk assessments. It also discloses which labs provided access, lists government ties (NIST consortium, UK AISI, EU AI Office), and calls itself a nonprofit.
- **Visual:** Card grid with dated cards and lab logo badges, plus diagram-style thumbnails. Restrained and editorial.
- **CTAs:** Read paper / View repo / Subscribe / Donate / Careers / press email. Nothing aimed at enterprises.

## 2. Arena, formerly LMArena (lmarena.ai → arena.ai)

- **Fetch failed:** lmarena.ai 301-redirects to arena.ai, and both arena.ai/ and arena.ai/leaderboard returned **HTTP 403** to WebFetch. I could not read the hero copy or the homepage section order. The notes below come from Arena's blog and from secondary sources.
- **Positioning:** It rebranded from LMArena to Arena in Jan 2026 and raised a $150M Series A at a reported $1.7B valuation (after a $100M seed in May 2025) ([Yahoo/Reuters](https://finance.yahoo.com/news/ai-startup-lmarena-triples-valuation-180027129.html), [Wikipedia](https://en.wikipedia.org/wiki/LMArena)). Labs reportedly pay Arena to test models before launch.
- **Leaderboard:** Rankings come from crowd pairwise votes fit with Bradley-Terry, and each rating carries a 95% CI. Secondary reporting says the site moved from a single "optimistic" rank to showing a raw rank plus a rank range derived from the CIs ([wikidocs](https://wikidocs.net/blog/@jaehong/12619/)). A style-controlled view separates formatting and length effects from capability. Older snapshots show "Rank (UB)" and "Rank (StyleCtrl)" columns.
- **Trust:** The ranking code is open-sourced as **Arena-Rank** (Apache 2.0, PyPI, GitHub), "the code that powers all of the leaderboards", with closed-form CIs and reweighting for models with few battles ([arena.ai/blog/arena-rank](https://arena.ai/blog/arena-rank), Dec 2025, updated Feb 2026).
- **Lesson:** The CI-based rank range is the industry's clearest public answer to "is #1 really better than #2?"

## 3. Scale AI SEAL / Scale Labs (scale.com/leaderboard → labs.scale.com/leaderboard)

- **Hero:** "testing the limits of AI." (lowercase) / "Benchmarks for frontier, agentic, and safety capabilities". CTA: *Start Exploring*. Two stats: "20+ benchmarks, 100+ models evaluated". [labs.scale.com/leaderboard](https://labs.scale.com/leaderboard)
- **Section order:** nav (Papers, Blog, Leaderboards, ⌘K search) → hero + stats → category tabs (All / Agentic / Safety / Frontier) → grid of about 20 leaderboard cards → three value blocks (frontier evals, human expertise, robust datasets) → "Show Deprecated Leaderboards" toggle → "Evaluate Your Model" (email) → newsletter → footer.
- **Leaderboard:** Each benchmark is a **card showing its top 3** with scores formatted like `55.40±4.20`. Some cards have no ± (for example Remote Labor Index). Cards carry "NEW" badges and some unexplained asterisks, but **no update dates on the cards**. Some cards have sub-tabs (Full/Hard, Large/Small). Each card links to "View Full Ranking →".
- **Methodology:** Humans design the tasks and rubrics, and LLMs scale the grading. The sets mix private data (against overfitting) with open data (for comparability). One integrity rule: a model is featured only the first time its organization sees the prompts.
- **Visual:** Bracketed uppercase labels (`[LEADERBOARDS]`, `[EVALUATE YOUR MODEL]`) give a terminal/technical feel. Numbered ranks. Dense but scannable.
- **CTAs:** For labs, an email-only "Evaluate Your Model". Newsletter.

## 4. Vals AI (vals.ai)

- **Hero:** eyebrow "Independent Evaluation, Unbiased Benchmarks" / H1 "Testing AI on Real-World Tasks". The sub-copy covers finance, software and higher-stakes risk areas, plus "We run all of our own evaluations and create many of our benchmarks in-house." [vals.ai](https://www.vals.ai)
- **Section order:** nav (Benchmarks, Models, Comparison, Vals Smith, App Reports, Government, News, Blog, Hackathon, About) → **dated news ticker** (Oct 21–24 2026) → hero → leaderboard card with tabs (Performance / Cost / Latency / Token Usage / Industry Breakdown) → Latest Reports feed.
- **Leaderboard:** The homepage card shows the "Vals Index", dated Oct 24 2026, with **one best model per lab** ("Showing best model from each lab"), lab icons and big percentages. The [index page](https://www.vals.ai/benchmarks/vals_index) has "Updated 10/24/2026" and "Version 2.2". Its table has Accuracy, Cost/Test, Tokens/Test and Duration/Test columns, and there is a **log-scale accuracy-vs-cost chart** with a Frontier view, an All/Open-weights filter, an "Over Time" chart, and links to versions v1 through v2.1. **No CIs or error bars**, although report prose sometimes says results are "within noise."
- **Methodology:** Inline on the benchmark page, as Motivation → Results → Methodology (GDP-weighted formula block) → Updates log → Related benchmarks. Report posts disclose the harness, sampling settings, and refusals counted as failures.
- **Trust:** Partner names (Harvey, Code for America, Anthropic for one benchmark, the Terminal-Bench team, search vendors). "Six private and two public benchmarks." No investors or testimonials on the homepage.
- **CTAs:** "View Full Results". A Government section. **No visible enterprise or lab sales CTA.**

## 5. Artificial Analysis (artificialanalysis.ai)

- **Hero:** "Independent analysis of AI" / "Understand the AI landscape to choose the best model and provider for your use case." [artificialanalysis.ai](https://artificialanalysis.ai)
- **Section order:** three "New" announcement cards → Intelligence / Speed / Cost-per-Task framing with tools (Optima, Model Recommender) → dated changelog → intelligence charts → indexes (Coding Agent, Cyber, Decision, Capability Index table) → benchmarks list (New/Updated tags) → more products → image/video/speech arenas → large footer (Explore / Products / Company incl. Methodology).
- **Leaderboard:** The most chart-heavy site in this set. Its signature view is an **Intelligence Index vs cost-per-task scatter with a Pareto line and a shaded "most attractive quadrant"**. Tabs switch between cost, time and tokens per task, and cost is split by token type. Model selection shows counts ("27 of 714 models"). Filters: open/proprietary, modality, country. A frontier-over-time chart is coloured by creator. The index is versioned (v4.3.2) and lists its components. **No CIs visible**, and dates appear in the changelog rather than on the charts.
- **Trust:** "Evaluations measured independently by Artificial Analysis." A per-eval methodology page. No partner logos or press on the homepage.
- **CTAs:** Explore models, "Build your own custom benchmark" (Optima), Vote (arenas), newsletter. The enterprise pitch is implicit in the product names.

## 6. Epoch AI (epoch.ai + Benchmarking Hub)

- **Home hero:** "Investigating the trajectory of AI for the benefit of society." [epoch.ai](https://epoch.ai)
- **Home section order:** hero → **headline stat cards, each with a 90% CI** (e.g. training compute ~5×/yr) → "Trusted by" press/government logos (NYT, Economist, FT, UK gov) → featured data/reports → newsletter → latest work → tabbed chart "snapshots" → data explorers → expert testimonials carousel → "Trusted by leaders at OpenAI, DeepMind, and governments" → *Book a consultation* → footer.
- **Hub:** H1 "AI benchmarks & capabilities" / "Our database of benchmark results, featuring the performance of leading AI models on challenging tasks." **"Updated Oct. 26, 2026" sits above the H1.** Summary cards show counts (ECI: 169 entries; 411 models; 94 benchmarks). The interactive chart has Color-by (country/org/accessibility) and a "Frontier trend only" toggle. Benchmark-set presets: Math / SWE / Epoch-administered / Custom. Views are split into "internal runs" and "external runs". Error bars are **±1 standard error**, citing an arXiv paper. [epoch.ai/benchmarks](https://epoch.ai/benchmarks)
- **Methodology:** Very concrete: Inspect framework, zero-shot CoT, empty system prompt, API-default temperature, 16 runs for GPQA/AIME. Task definitions are published as Gists, there is a per-question log viewer, and caveats cover contamination and prompt sensitivity.
- **Trust:** CSV download, a `pip install epochai` client, a **CC BY 4.0** licence, a Transparency/funding page, provenance for external data, and an FAQ. (Inconsistency spotted: the hub shows one model at ECI 169 while a dated news item says 167. Stale numbers in two places erode trust.)
- **CTAs:** Newsletter (repeated), Book a consultation, data downloads, feedback form.

## 7. Andon Labs (andonlabs.com)

- **Hero:** "Autonomous organizations without humans in the loop." A "Trusted by" row shows Anthropic, OpenAI and Google DeepMind. [andonlabs.com](https://andonlabs.com)
- **Section order:** announcement banner (Pion product) → hero + lab logos → mission → Pion promo (waitlist, screenshot) → **real-world autonomous organizations** (3 photo cards) → Evals (3 cards) → publications (6 dated) → "Join the lab" → footer (YC-backed).
- **Showcase:** The closest analogue to our showcase gallery. Photo cards name the business and its *current operator model*: Andon Market, an AI-run SF store run by "Claude Fable 5.1"; Andon Café in Stockholm, run by "GPT 6 Astra"; Andon FM, four AI-run radio stations. Each card has only a one-line tagline and no narrative or numbers.
- **Evals:** Each eval card asks a question ("Can AI agents run vending machine businesses?" for Vending-Bench) and shows a "Highest score by [model logo]". **No charts, tables, money axes, CIs or dates on the homepage.** The navigation lists Vending-Bench 2, Vending-Bench Arena, Butter-Bench, Drone-Bench and Blueprint-Bench 2.
- **Visual:** Dark and minimal, with full-bleed atmospheric photography (cables, server racks) and photo-backed cards.
- **CTAs:** Join waitlist, Apply, Store, contact email. **No lab/enterprise eval CTA.**

## 8. Terminal-Bench (tbench.ai), from Stanford and the Laude Institute

- **Hero:** "TERMINAL-BENCH 4.0" / "A benchmark to measure and evolve with the frontier of agent work." CTAs: *Run the benchmark*, *View the tasks*. [tbench.ai](https://www.tbench.ai)
- **Structure:** Hero → leaderboard → contamination notice with a canary GUID → footer ("hosted by Stanford, Harbor, Laude Institute"). That is all. The **leaderboard sits right under the hero**.
- **Leaderboard:** Columns are Rank / Model / **Agent** / Resolution Rate / **Cost** / Tokens, and the caption says the "whiskers span the 95% confidence interval." (The rows render client-side, so the fetch didn't capture them.)
- **Trust:** Open source (GitHub), the canary string, a contributors page, Discord.
- **Visual:** All-caps labels, a bold wordmark, and a technical, sparse feel.

## 9. Transluce (transluce.org)

- **Hero:** "Infrastructure for understanding AI." / "Transluce is a non-profit research lab building the public tech stack for scalable oversight of AI." [transluce.org](https://transluce.org)
- **Structure:** hero + abstract illustration → Our Work (3 typed cards) → Latest News (dated, tagged Research/Essay/News) → mission + donate → resources → footer with a **trust center and a responsible-disclosure policy**, plus 501(c)(3) status.
- **Lesson:** Its "Incident Reports" and "Behavior Reports" turn eval output into a dated, citable series. That is a good press hook.

## 10. Kaggle Game Arena (kaggle.com/game-arena)

- **Fetch failed:** The page is JavaScript-rendered, and WebFetch returned only the title "Game Arena | Kaggle". From secondary sources: it is a Google DeepMind + Kaggle platform with chess, then poker and Werewolf (Feb 2026), open-source harnesses, a technical report, and per-game leaderboards at kaggle.com/benchmarks/kaggle/chess ([Google blog](https://blog.google/innovation-and-ai/models-and-research/google-deepmind/kaggle-game-arena-updates/)). Its notable pattern is **watchable matches**: replays and livestreamed tournaments turn a benchmark into content.

---

## Cross-cutting patterns

- **CIs are inconsistent across the field.** Arena (95% CI plus rank ranges), Scale (±), Terminal-Bench (95% whiskers) and Epoch (±1 SE) show uncertainty. Vals, Artificial Analysis, METR's main chart and Andon do not. Nobody explains *in plain language* what overlapping CIs mean for the ranking.
- **Cost is now a standard axis:** Vals and Artificial Analysis have accuracy-vs-cost scatters, and Terminal-Bench has a cost column.
- **Dates and versions:** Epoch (date above the H1), Vals (date + version + changelog) and METR (version + "last updated" + "no longer updated") do this well. Scale cards and Andon cards show no dates.
- **Trust stack:** open code/data (Epoch, METR, Arena, Terminal-Bench), independence statements (Vals, AA, METR's "no compensation"), and logo rows (Andon, Epoch, METR). Funding transparency pages are rare (Epoch, Transluce).
- **Lab/enterprise CTAs are weak everywhere.** Scale's is an email, Epoch's is "Book a consultation", and Vals, Andon and AA have none on the homepage. That leaves an opening.
- **Nobody shows the artifacts.** Even Andon, the closest competitor in spirit, gives its real businesses one line and a photo, with no P&L, no website and no ads.

---

## What our site should copy / avoid / do differently

### Copy
1. **Put an "Updated {date} · Benchmark v{x.y}" stamp directly above the leaderboard H1** (Epoch), and keep a public changelog listing every model added and every rubric change (Vals, METR).
2. **Show the leaderboard right below the hero on the home page** (Terminal-Bench), as a compact top-10 with a "Full leaderboard →" link, not three scrolls down.
3. **Draw CIs as horizontal whiskers on every score and show a rank range next to each rank** (Arena, Terminal-Bench). Shade or bracket models whose intervals overlap as "statistically tied".
4. **Add a cost axis:** a "Score vs. cost to build one business" scatter with a Pareto frontier line (Artificial Analysis, Vals), and a cost column in the table.
5. **Mark each row "Run by us" or "Lab-submitted", and offer a "Best model per lab" toggle** (Epoch's internal/external split; Vals' best-per-lab view).
6. **Make the methodology page publishable:** settings disclosed (temperature, scaffold, budgets, number of runs), a caveats box near the top, a BibTeX copy button, a downloadable CSV/JSON results file, the judge prompts on GitHub, and a stated data licence such as CC BY 4.0 (Epoch, METR).
7. **Put a canary string and a contamination notice** on the methodology page and on any public task set (Terminal-Bench).
8. **Write an independence line** in the style of METR ("we do not accept payment to evaluate or rank models") and link a short Transparency/funding page from the footer (Epoch, Transluce).

### Avoid
1. **Avoid unexplained asterisks and "NEW" badges without dates** (Scale cards). Every footnote marker needs an inline tooltip.
2. **Avoid cards that show only "Highest score by [logo]"** (Andon). One winner hides the spread, and labs will contest it. Always show the top 3+ with intervals.
3. **Avoid stale or mismatched numbers.** Epoch's hub said 169 while its news item said 167. Generate every number on the site from one results file at build time.
4. **Avoid atmospheric stock imagery** (Andon's cables and server racks, Transluce's abstract AI illustration) and hero gradients. Our imagery should be real screenshots of businesses the models built.
5. **Avoid email-only lab CTAs** (Scale) and missing enterprise CTAs (Vals, AA, Andon). Use a real form with a few fields: org type, models of interest, timeline.
6. **Avoid single-number scores with no uncertainty** (Vals, AA) and charts with no date on the chart itself.
7. **Avoid nav sprawl.** Vals has 10 top-level items and AA has a mega-footer of products. Five items is enough: Leaderboard, Showcase, Methodology, For Labs, Blog.

### Do differently
1. **Lead the homepage with one surprising, concrete business a model built**: a live screenshot of its site, its brand mark, one of its ads, its price, and its judge score with CI. For example: "{Model} launched a dog-walking subscription in 6 hours for $41. Judges gave it 7.2 ± 0.6." Then show the leaderboard. Nobody else shows the artifact.
2. **Make each showcase entry a full case file, not a tagline:** product, website (live link plus a frozen snapshot), brand, ad creative and targeting, pricing, cost to build, wall-clock time, a sub-score per dimension, and two or three judge quotes (human and LLM, labelled). Andon gets one line per card. We should get a page per business.
3. **Add a "same brief, every model" comparison view:** pick one brief and see each model's landing page side by side in a uniform thumbnail grid. It makes the ranking visible and easy to share.
4. **Explain the CIs in one plain sentence above the table**, such as "Models in the same shaded band are statistically tied; ranks show the 95% range." No competitor does this.
5. **Show what human judges and LLM judges each said:** a toggle or two columns (Human score / LLM-judge score / agreement), plus the inter-rater agreement stat on the methodology page. This is our trust differentiator over pure-LLM or pure-crowd boards.
6. **Split the "For Labs & Enterprises" page into three clear offers:** pre-release private evaluation, custom brief sets for enterprises, and data/API access. Each gets a sample deliverable (redacted report PDF) and a short form. Put a "Researchers & press" strip on the same page with a press kit, citation and contact.
7. **Run the launch blog post as a dated, citable report** (Transluce's report series, METR's papers): headline finding, one chart, three example businesses, limitations, BibTeX. Version future results as "Report 02, 03…".
8. **Choose the visual tone of a technical report, not a startup page:** a serif or neutral grotesk for body text, tabular numerals for scores, a single accent colour reserved for CI bands and frontier lines, and real business screenshots as the only imagery. Make it dense where the data is and roomy everywhere else.
