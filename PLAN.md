# PLAN

Spec: `BENCHMARK_BUILD_PROMPT.md`. Name: **Shingle** (company) / **ShingleBench** (benchmark), CLI `shingle`.
Working docs: `PROGRESS.md` (append-only log), `DECISIONS.md` (choices + why).

## Milestones

- [x] **M1 Research + design + plan**: `research/prior-art.md`, `research/competitor-sites.md`, `research/benchmark-design.md`; finalize this plan.
- [x] **M2 Tasks**: Pydantic task schema (versioned, JSON Schema export), loader/validator CLI, 24+ tasks across 6 categories × 3 tiers, dev/held-out split with canary strings and public-export script.
- [x] **M3 Sandbox + mock services**: workspace + shell (Docker `--network none`, local fallback), preview hosting with platform API (forms, checkout, KV) + freeze, image gen (mock + OpenAI), ad platform with real-platform validation, payments (mock + Stripe test-mode), supplier catalog, logged web research (offline corpus).
- [x] **M4 Harness**: provider interface (Anthropic, OpenAI, Google, OpenAI-compatible, MockModel), tool registry, versioned system prompt, notes file + summarization, caps, retries, checkpoint/resume, cost tracking. One full episode end to end on MockModel.
- [x] **M5 Market + iteration**: persona panel per task market, mock feed, headless-browser browsing + purchase/inquiry attempts, weekly funnel report fed back to the agent; deterministic mock simulator + LLM simulator.
- [x] **M6 Bundles + checks**: run bundle (frozen site, source, screenshots desktop/mobile, brand, creatives, campaigns, plan, market weeks, trajectory, usage, checks), export; automated checks (load/links/console, Lighthouse or lite audits, mobile, forms, checkout, product QA agent, ad compliance, integrity flags).
- [x] **M7 Judges + aggregation**: rubric v1 (anchored 1–7), LLM judges (absolute + pairwise with position swap, family flag, injection guard), mock judge; Bradley–Terry/Elo, bootstrap CIs, breakdowns, human/LLM/combined weights, LLM–human agreement.
- [x] **M8 Human grading app**: accounts, queue, blind scrubbing, absolute + pairwise modes, embedded frozen site, QC (gold, attention checks, time-on-task, Krippendorff α), admin views + export.
- [x] **M9 Dashboard + reports**: leaderboard, run explorer → bundle → trajectory, breakdowns, seed variance, cost; per-round markdown/HTML report.
- [x] **M10 Company website**: static site (home, leaderboard, showcase, methodology, for-labs + contact, launch post), Playwright screenshots reviewed.
- [x] **M11 Hardening + demo**: `docker compose up` from clean clone, demo eval (2 models × 3 tasks × 2 seeds), CI, README (setup, add model, add task, run eval, grade, open questions).

## Definition of done
See `BENCHMARK_BUILD_PROMPT.md` §14; each item verified by running it.
