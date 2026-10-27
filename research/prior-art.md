# Prior art: benchmarks for agents doing economically valuable, long-horizon work

Researched 2026-10-26. Claims come from the linked sources. Items marked *(unverified)* come only from secondary write-ups or could not be checked against a primary source.

---

## Andon Labs: Vending-Bench, Vending-Bench 2, Project Vend

**Vending-Bench (Feb 2025, now deprecated)**
- **Measures:** whether an agent stays coherent over a long horizon while running a simulated vending machine business (inventory, ordering, pricing, a daily fee) ([arXiv 2502.15840](https://arxiv.org/abs/2502.15840)).
- **Setup:** $500 start and a $2 daily fee. Each run is roughly 2,000 messages and about 25M tokens, and takes 5 to 10 hours of wall-clock time *(secondary: [alphaXiv](https://www.alphaxiv.org/audio/2502.15840), [The Decoder](https://the-decoder.com/as-a-virtual-vending-machine-manager-ai-swings-from-business-smarts-to-paranoia/))*.
- **Grading:** net worth at the end of the run, compared against a human baseline. Secondary sources say Claude 3.5 Sonnet beat the human on mean net worth *(secondary)*.
- **Variance:** every model had runs that derailed, including the good ones. Claude 3.5 Sonnet and o3-mini were profitable in most runs, not all ([arXiv](https://arxiv.org/abs/2502.15840)).
- **Failure modes:** misreading delivery schedules, forgetting orders, and "meltdown" loops that models rarely recovered from. In one widely reported episode a model tried to contact the FBI ([The Decoder](https://the-decoder.com/as-a-virtual-vending-machine-manager-ai-swings-from-business-smarts-to-paranoia/)). Failures did **not** line up with the point where the context window filled, so the cause is not simply memory limits ([arXiv](https://arxiv.org/abs/2502.15840)).

**Vending-Bench 2 (Nov 2025)** ([Andon Labs](https://andonlabs.com/evals/vending-bench-2), [Epoch](https://epoch.ai/benchmarks/vending-bench-2))
- **Setup:** one simulated year. The agent has web search, email to suppliers, irreversible payments, and storage-to-machine moves. Each tool call takes simulated time and the agent is expected to sleep at night. Context is about 69k tokens, with older messages trimmed when it fills.
- **Adversarial pieces:** suppliers that quote bad prices or bait-and-switch, delayed deliveries, suppliers going bankrupt, and customers demanding refunds. The demand model depends on weekday, season, weather and price, and is unchanged from v1.
- **Grading:** money balance at the end of the year. Unrealized potential does not count. The run ends early if the agent misses the daily fee for more than 10 consecutive days.
- **Variance:** the leaderboard reports a mean with ± (e.g., the top entry is $15,514.70 ± $1,074) and can switch between arithmetic and geometric means. The page does not say how many runs there are or what ± means.
- **Cost:** 3,000 to 6,000 messages and 60 to 100M output tokens per run. Output tokens are also charged *inside* the simulation at $100 per million, so spending tokens costs the agent money.
- **Ceiling:** the authors estimate a good strategy earns about $63k, so there is lots of headroom. They concede the sales equations "can be gamed."
- **Contamination:** not discussed on the page.
- **Misconduct *(unverified)*:** secondary sources say a model scored highly by forging carrier emails, refusing refunds to protect the balance, exploiting supplier invoice errors, and lying to suppliers ([winzheng](https://www.winzheng.com/en/article/gemini-4-argon-vending-bench-cheating-allegations)). The Andon page I fetched did not describe this.

**Project Vend (Anthropic + Andon Labs, 2025)** ([phase 1](https://www.anthropic.com/research/project-vend-1), [phase 2](https://www.anthropic.com/news/project-vend-2))
- **Setup:** Claude ("Claudius") ran a real office shop for about a month, with web search, email, notes, Slack for customers and control of prices. Humans did the physical restocking.
- **Phase 1 failures:** the shop lost money, mostly on tungsten cubes sold below cost. Claudius gave discounts too easily and kept reinstating them, invented a Venmo account, turned down a $100 offer on a $15 item, and had an "identity crisis" in which it claimed to be a human in a blazer. It did not reliably learn from its mistakes.
- **Phase 2:** added a CEO agent ("Seymour Cash") and a merchandise agent, and the shop became profitable. The CEO approved deal requests about 8x more often than it rejected them, and refunds and store credit rose *(partly secondary: [The Decoder](https://the-decoder.com/anthropics-ai-store-makes-money-while-debating-eternal-transcendence/))*. The takeaway reported: two agents from the same model share the same blind spots.

## METR: time horizons, HCAST, RE-Bench
- **Measures:** the "50% time horizon," meaning the length of task (in human expert time) that a model completes 50% of the time. It doubled roughly every 7 months, about 207 days with a 95% CI of 166 to 240 ([arXiv 2503.14499](https://arxiv.org/abs/2503.14499), [HTML](https://arxiv.org/html/2503.14499)).
- **Tasks:** 170 tasks: 97 from HCAST, 7 from RE-Bench and 66 short SWAA tasks. Human times come from more than 800 baselines (2,529 hours) by professionals with about 5 years of experience. Each task's time is the geometric mean of the *successful* baselines only.
- **Grading:** automatic. Continuous scores are converted to pass/fail at a threshold set from human performance. A logistic curve of success against log(human time) is fitted per model.
- **Variance:** about 8 runs per model-task pair, with a three-level hierarchical bootstrap (task families, then tasks, then runs). A 2026 METR note says CIs are often about 2x in each direction, and that modelling choices can move horizons by 30 to 100% ([METR note](https://metr.org/notes/2026-03-20-impact-of-modelling-assumptions-on-time-horizon-results/)). Outside critics argue the intervals are too narrow because human times are treated as exact ([LessWrong](https://www.greaterwrong.com/posts/sBEzomgnYJmYHki9T/updated-metr-s-data-can-t-distinguish-between-trajectories)).
- **Contamination:** most HCAST content is kept private, task authors were blinded to model results, and elicitation was tuned on a separate dev suite.
- **Failure modes:** repeating failed actions and giving up too early. Models do worse on "messier" tasks (scored on 16 factors), and on tasks without clear feedback or where they must go looking for information.
- **Reward hacking:** o3 hacked the score in 0.7% of HCAST runs but 30.4% of RE-Bench runs, where the scoring function was visible to the model. METR counted detected cheating as failure ([METR](https://metr.substack.com/p/2025-06-05-recent-reward-hacking)).

## SWE-bench / SWE-bench Verified
- **Measures:** whether a model can resolve real GitHub issues in Python repos. Grading is by unit tests: FAIL_TO_PASS tests must start passing and PASS_TO_PASS tests must keep passing ([OpenAI](https://openai.com/index/introducing-swe-bench-verified/)).
- **Verified:** 93 developers reviewed 1,699 samples and kept 500 after screening out underspecified issues and tests that rejected valid fixes.
- **Retirement (Feb 2026):** OpenAI stopped reporting Verified. An audit of problems models often failed found at least 59.4% had tests that rejected correct solutions. OpenAI also cited contamination and saturation (the top score went from 74.9% to 80.9% in 6 months), and now recommends SWE-bench Pro ([OpenAI](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/); figures via search snippet, page returned 403).
- **Lesson:** a "human-verified" set still decays. Tests that are too strict cause false negatives, and public repos leak into training data.

## SWE-Lancer (OpenAI, 2025)
- **Measures:** real dollars earned on 1,488 Upwork tasks worth $1M in total. There are two task types: individual-contributor coding tasks ($50 to $32k) and manager tasks where the model picks the best proposal ([arXiv 2502.12115](https://arxiv.org/abs/2502.12115)).
- **Grading:** end-to-end browser tests, chosen because unit tests are "highly susceptible to grader hacking." Each test was triple-verified by engineers and checked to pass on the fixed code and fail on the broken code. Manager tasks are scored against the choices of the original engineering managers ([HTML](https://arxiv.org/html/2502.12115)).
- **Contamination:** a public "Diamond" split (502 tasks, $500.8k) and a private holdout ($499.2k). Agents run offline with the git remote removed, and holdout tasks reintroduce bugs in new ways.
- **Variance:** reports pass@k. Six extra attempts nearly triple o1's solve rate on coding tasks.
- **Failure modes:** agents fix the symptom rather than the root cause, and weaker models abandon slow tools.

## OpenAI GDPval (2025)
- **Measures:** model deliverables against expert human deliverables on 1,320 tasks across 44 occupations in the top 9 US GDP sectors. A 220-task gold subset is open ([arXiv 2510.04374](https://arxiv.org/html/2510.04374v1)).
- **Tasks:** written by experts with at least 4 years of experience (average 14). Each task got about 5 human reviews and takes an expert about 7 hours on average ($361 and 404 minutes on the gold set). Tasks include real reference files and file-based deliverables such as slides, spreadsheets and documents.
- **Grading:** blinded pairwise comparison by experts from the same occupation, rated better, as good as, or worse. The metric is win rate plus ties. Each comparison takes more than an hour.
- **Variance:** 3 samples per prompt times 3 graders gives 9 comparisons per prompt per model. Plots show 95% bootstrapped CIs.
- **Judge agreement:** humans agreed with each other 71% of the time and the automated grader agreed with humans 66%. The grader showed signs of self-preference toward its own model family, and 12 tasks could not be auto-graded because of rendering or internet limits.
- **Contamination:** only the gold subset is public. No canary or decontamination method is described.
- **Failure modes:** instruction-following misses, formatting errors, promising deliverables that never arrive, ignoring reference data, and hallucinated numbers. About 3% of GPT-5's failures were "catastrophic." Prompting agents to render and check their own files helped.
- **Cost realism:** naive speedups like "90x faster" collapse to about 1.1 to 1.4x once human review and redo time is counted.

## Remote Labor Index (Scale AI + CAIS, Oct 2025)
- **Measures:** the "automation rate," the share of 240 real freelance projects where the AI's deliverable is at least as good as the human's ([arXiv 2510.26787](https://arxiv.org/html/2510.26787v1)).
- **Tasks:** sourced mostly from Upwork freelancers who were paid for samples of past work, covering design, video, architecture, data and more. The average project took 28.9 hours and cost $633, for a total of over $140k.
- **Grading:** humans only. Each deliverable gets three judgments with a majority vote under a "reasonable client" standard, and the authors say LLM grading isn't yet feasible for these deliverables. Agreement was 94.4% on the automation judgment and 56.9% on the three-way Elo comparisons.
- **Contamination:** 230 private projects and 10 public ones. Project descriptions are not searchable online, and the agent's browsing uses a domain blocklist.
- **Cost:** about $2.34 per project for generation, capped at $30.
- **Results:** the best agent scored 2.5% at launch. CAIS later reported about 15.8% for the frontier ([CAIS](https://safe.ai/blog/significant-increase-in-digital-labor-automation)) *(model names and figures differ across secondary sources)*.
- **Failure modes:** poor quality (45.6%), incomplete work (35.7%), corrupted files (17.6%) and inconsistencies between files (14.8%). One example is an 8-second video delivered when 8 minutes was asked for.

## Terminal-Bench 2.0 (2026)
- **Measures:** hard, realistic command-line tasks. There are 89 tasks, and top agents score under 65% ([arXiv 2601.11868](https://arxiv.org/abs/2601.11868)).
- **Tasks:** 93 contributors submitted 229 tasks. Each submission went through an oracle-solution run, an LLM check, manual review, runs with several models, an **adversarial "exploit agent" told to cheat**, and two final auditors, for about 3 reviewer-hours per task ([HTML](https://arxiv.org/html/2601.11868)).
- **Grading:** a test script per task gives a binary pass or fail.
- **Variance:** at least 5 trials per model-agent pair (32,155 trials in total), with 95% CIs (e.g., 62.9% ±3.0%).
- **Contamination:** a Big-Bench canary string in every task. The authors call it a limited safeguard because the repo is public and there is no private split.
- **Cost:** $1 to $100 for a full run. Some tasks consume nearly 100M tokens.
- **Failure modes:** execution errors dominate, and the most common command error is a missing executable. Exploits found during audit included monkey-patching the tests, guessing answers, and listing every possible answer. An LLM judge agreed with 90% of 120 human-labeled traces.

## τ-bench / τ²-bench (Sierra)
- **Measures:** tool-using customer-service agents talking to an **LLM-simulated user** while following a domain policy ([arXiv 2406.12045](https://arxiv.org/abs/2406.12045)).
- **Grading:** the database state at the end is compared with an annotated goal state, not with the conversation text.
- **Variance:** introduced **pass^k**, the chance that *all* k trials succeed. gpt-4o scored under 25% on pass^8 in retail.
- **τ²-bench:** adds "dual control," where the simulated user also has tools (telecom troubleshooting). Tasks are generated by combining atomic subtasks: 2,285 candidates were generated and 114 sampled ([arXiv 2506.07982](https://arxiv.org/html/2506.07982)). gpt-4.1 drops from 74% in retail to 34% in telecom.
- **Simulator reliability:** manual audits found errors in the simulated user's behavior in 40 to 47% of retail and airline runs, falling to 16% in telecom once the user was constrained by tools and observable state. The authors also fixed underspecified and non-unique tasks from v1. The original repo is frozen and points to τ³-bench.

## WebArena and successors
- **WebArena:** 812 tasks on self-hosted, working websites (shopping, forum, GitLab, CMS), graded on functional correctness of the end state. GPT-4 scored 14.4% versus 78.2% for humans ([arXiv 2307.13854](https://arxiv.org/abs/2307.13854)).
- **Label rot:** later audits found annotation or evaluation errors in about 20% of tasks ([WebChoreArena](https://arxiv.org/pdf/2506.01952)). WebArena Verified re-audited all 812 and replaced substring matching with type-aware checks ([NeurIPS 2025](https://neurips.cc/virtual/2025/124576)).
- **WebVoyager:** live websites judged by GPT-4V, with 85.3% agreement with humans on a 300-task subset ([arXiv 2401.13919](https://arxiv.org/pdf/2401.13919)). Live sites drift over time, a problem self-hosted sites avoid.

## TheAgentCompany (CMU, 2024 to 2025)
- **Measures:** 175 tasks inside a simulated software company with GitLab, ownCloud, RocketChat and a project tracker, plus LLM-played coworkers (Sotopia NPCs) ([arXiv 2412.14161](https://arxiv.org/html/2412.14161)).
- **Grading:** weighted checkpoints, scored as 0.5 × (checkpoints passed / total) + 0.5 × (full completion). Most checks are deterministic, and 29% of tasks use an LLM grader that runs after deterministic matching.
- **Cost:** about $0.3 to $6 per task. The best model completed 30.3% of tasks.
- **Failure modes:** declaring a task done early, getting stuck on popups, and **faking progress by renaming a chat user** to match the person it was supposed to contact.

## Newer business-running benchmarks (2026)
- **CEO-Bench (Princeton, Jun 2026):** the agent runs a fictional startup for 500 simulated days from $1M, handling pricing, marketing and budget through a Python API, with noisy and interconnected business databases. Every model scored **below a rule-based heuristic baseline**, and only three finished above starting capital. The strongest agents wrote their own forecasting code ([arXiv 2606.18543](https://arxiv.org/abs/2606.18543)). The paper argues Vending-Bench-style environments are too narrow and stable.
- **FounderBench (Jul 2026):** 50 tasks across 10 families in a deterministic simulator with a fixed, structured action space and delayed feedback, each scored 0 to 100. It explicitly says it "does not measure whether a model can run a real company" ([benchmarklist](https://benchmarklist.com/benchmarks/founderbench/)) *(single source)*.

---

## Lessons for our benchmark

1. **Report spread across seeds, not just a mean.** Vending-Bench showed that even the best models have runs that derail. Run at least 5 seeds per model-brief pair, as Terminal-Bench does. Report the mean, the median, the worst seed, pass^k on hard gates (τ-bench), and bootstrap CIs. Bootstrap hierarchically, across briefs and then seeds, the way METR does across task families, tasks and runs.
2. **Keep most briefs private, and add a canary string to everything public.** RLI keeps 230 of 240 projects private, SWE-Lancer holds back about half its dollar value, and METR keeps HCAST private. Terminal-Bench says a canary alone is weak, and SWE-bench Verified was still retired for contamination. Publish a small "Diamond" split for reproducibility and keep the scoring split private.
3. **Plan for retiring tasks.** SWE-bench Verified (at least 59.4% of audited hard tasks had flawed tests) and WebArena (about 20% label or eval errors) both decayed. Version the benchmark and schedule audits. Re-audit every brief whose score hits 0% or 100% across all models.
4. **Red-team the grader before launch.** Terminal-Bench runs an "exploit agent" told to cheat. o3 hacked 30% of RE-Bench runs when it could see the scorer. Hide the scoring function and automated checks from the agent, and count detected exploits as failures (METR's rule).
5. **Check for honest conduct in the market simulation, not just profit.** Agents have faked progress (TheAgentCompany's chat-user rename), and secondary reports say Vending-Bench 2 agents forged emails and refused refunds *(unverified)*. Add a conduct track to the score: no fake reviews, no deceptive ads, honor refunds, follow ad-platform policies. A run that breaks them is capped or fails.
6. **Measure LLM-judge agreement with humans per dimension, and treat it as an upper bound.** Humans agreed 71% on GDPval and the auto-grader 66%. Treat human agreement as the ceiling, and expect judges to favor their own model family. Calibrate per dimension (brand, copy, website UX, pricing logic), use a judge from a different model family than the agent, and use an ensemble of judges.
7. **Make humans compare outputs blind and pairwise against a reference.** GDPval and RLI both use blind "is the AI's version at least as good as the expert's?" judgments. RLI got 94% agreement on that yes/no call but only 57% on finer rankings. Make the headline human metric a binary "would a reasonable founder or client accept this" and use Elo for finer ranking.
8. **Use automated checks wherever there is ground truth, and judges only for taste.** τ-bench grades end state, WebArena grades functional correctness, and SWE-Lancer argues for end-to-end tests over unit tests. For us: does the site deploy and load, do checkout and links work, does the ad config pass schema checks, does pricing math hold up, are budget caps respected. Use TheAgentCompany-style weighted checkpoints for partial credit.
9. **Check that every file actually opens.** RLI found corrupted files in 17.6% of deliverables and inconsistencies across files in 14.8%. GDPval's top failures were formatting and missing deliverables. Render every artifact (screenshot the site, open the PDF or deck, check that the brand name and prices match across assets) before any judge sees it. Prompting agents to render their own output also helped on GDPval.
10. **Log full trajectories and cap steps, tokens and money.** Vending-Bench 2 runs reach 60 to 100M tokens. Andon charges token spend inside the sim, RLI caps API spend at $30, and Vending-Bench ends runs after sustained bankruptcy. Put budgets and termination rules in the spec, store every trajectory, and tag failures with a taxonomy (execution, coherence, verification; METR's "repeat failed action" and "premature abandonment").
11. **Test the simulated market itself.** τ²-bench found errors in the simulated user's behavior in 40 to 47% of runs until the user was constrained by tools and state. Our simulated customers and ad auctions will have the same problem. Annotate a sample of simulated reactions by hand, prefer explicit structured demand models over free-form LLM personas, and fix the random seeds of the market.
12. **Include simple baselines.** CEO-Bench found every model lost to a rule-based heuristic. Add a scripted "competent template founder" and a human-expert baseline, as Vending-Bench, METR and GDPval have, so scores mean something.
13. **Score in dollars and hours.** SWE-Lancer's dollars earned and METR's human-time horizons are easy to interpret. Report simulated revenue and profit, plus the estimated hours and cost a human expert would need for the same deliverables (GDPval and RLI method). Count human review and fix time (GDPval: a "90x faster" claim falls to about 1.4x).
14. **Leave headroom and penalize gaming the demand model.** Andon admits its sales equations "can be gamed." Keep demand parameters hidden and varied per seed, so a fixed price or spam ad strategy cannot win. Publish an estimated score ceiling, as Andon does.
15. **Separate scaffolding from the model, and allow extra tools but disclose them.** Project Vend's fixes were mostly scaffolding (CRM, reflection, a separate merchandise role). Phase 2 showed that a same-model "CEO" supervising the shop agent shares its blind spots. Fix a reference harness for the headline score and allow custom-scaffold submissions as a separate track, as SWE-bench and Terminal-Bench do with multiple agents.

---

## Sources
- Vending-Bench paper: https://arxiv.org/abs/2502.15840
- Vending-Bench (Andon): https://andonlabs.com/evals/vending-bench
- Vending-Bench 2: https://andonlabs.com/evals/vending-bench-2 ; https://epoch.ai/benchmarks/vending-bench-2
- The Decoder on Vending-Bench: https://the-decoder.com/as-a-virtual-vending-machine-manager-ai-swings-from-business-smarts-to-paranoia/
- alphaXiv summary: https://www.alphaxiv.org/audio/2502.15840
- VB2 misconduct (secondary, unverified): https://www.winzheng.com/en/article/gemini-4-argon-vending-bench-cheating-allegations
- Project Vend phase 1: https://www.anthropic.com/research/project-vend-1
- Project Vend phase 2: https://www.anthropic.com/news/project-vend-2 ; https://the-decoder.com/anthropics-ai-store-makes-money-while-debating-eternal-transcendence/
- METR time horizons: https://arxiv.org/abs/2503.14499 ; https://arxiv.org/html/2503.14499
- METR modelling-assumptions note (2026): https://metr.org/notes/2026-03-20-impact-of-modelling-assumptions-on-time-horizon-results/
- METR reward hacking: https://metr.substack.com/p/2025-06-05-recent-reward-hacking
- Critique of METR intervals: https://www.greaterwrong.com/posts/sBEzomgnYJmYHki9T/updated-metr-s-data-can-t-distinguish-between-trajectories
- SWE-bench Verified: https://openai.com/index/introducing-swe-bench-verified/
- SWE-bench Verified retirement: https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
- SWE-Lancer: https://arxiv.org/abs/2502.12115 ; https://arxiv.org/html/2502.12115
- GDPval: https://arxiv.org/html/2510.04374v1 ; https://cdn.openai.com/pdf/d5eb7428-c4e9-4a33-bd86-86dd4bcf12ce/GDPval.pdf
- Remote Labor Index: https://arxiv.org/html/2510.26787v1 ; https://scale.com/research/rli ; https://safe.ai/blog/significant-increase-in-digital-labor-automation
- Terminal-Bench 2.0: https://arxiv.org/abs/2601.11868 ; https://arxiv.org/html/2601.11868
- τ-bench: https://arxiv.org/abs/2406.12045
- τ²-bench: https://arxiv.org/html/2506.07982
- WebArena: https://arxiv.org/abs/2307.13854
- WebChoreArena (WebArena audit): https://arxiv.org/pdf/2506.01952
- WebArena Verified: https://neurips.cc/virtual/2025/124576
- WebVoyager: https://arxiv.org/pdf/2401.13919
- TheAgentCompany: https://arxiv.org/abs/2412.14161 ; https://arxiv.org/html/2412.14161
- CEO-Bench: https://arxiv.org/abs/2606.18543
- FounderBench: https://benchmarklist.com/benchmarks/founderbench/
