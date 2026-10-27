# PROGRESS (append-only)

## 2026-10-26
- Repo was empty; saved the owner's full spec as `BENCHMARK_BUILD_PROMPT.md`.
- Scaffolded uv Python project (`shingle`), verified Playwright Chromium runs headless.
- Launched two research subagents (prior art, competitor sites). Next: task schema + seed tasks while research runs.
- M1 done: research/prior-art.md, competitor-sites.md, benchmark-design.md (subagents for the first two).
- M2 done: schema + 26 tasks (12 dev / 14 held-out; subagent authored 23), export script, tests.
- M3–M5 done: sandbox services, harness, providers, MockModel (diligent/hasty), market simulator with real browsing personas. Fixed a Playwright navigation race that made simulated checkouts fail. 14 tests pass. Next: M6 bundles + automated checks + QA agent.
- M6 done: bundles (frozen site, screenshots, ad previews, docs, commerce, market, trajectory) + checks + probe/LLM QA agent; runner; caught a real mock bug (final-week price retire -> dead checkout).
- M7 done: rubric v1, blinding/evidence packets, absolute + position-swapped pairwise judges (mock + real), stats (Krippendorff verified vs published example), aggregation -> results.json.
- M8/M9 done: grading app (blind absolute/pairwise, QC, admin, export), dashboard, run explorer, trajectories, round report; Playwright-driven UI smoke test grades through the UI.
- M10 done: company site (home specimen plate, leaderboard, showcase + case files, methodology, labs + working contact form, Report 01); screenshots reviewed at desktop and mobile; fixed duplicate-id bug in contact form.
- M11: `make dev` / `shingle up`, Dockerfile + compose (validated; Docker Desktop sign-in blocks running it here), CI, README, 28 tests passing.
