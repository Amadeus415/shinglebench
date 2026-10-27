# DECISIONS

Each entry: the call, and why. Newest at the bottom.

## D1. Name: Shingle / ShingleBench
Candidates: **Shingle** ("hang out your shingle" = open for business), LaunchBench, OpenSign, Storefront, Proof of Business.
Picked Shingle: short, ownable, says "opening a real business" without the word AI or bench in the brand; the benchmark is ShingleBench, CLI `shingle`. LaunchBench was the runner-up (clearer, but generic). Trademark search is an open question for the owner.

## D2. Spec file
The repo was empty; the owner's spec (pasted into the session) is saved verbatim as `BENCHMARK_BUILD_PROMPT.md`.

## D3. No API keys present → mock-first
No model, image, or Stripe keys in the environment. Every provider has a deterministic mock and the demo runs fully offline. Real providers are implemented against their public REST APIs and switch on when keys are set in `.env`, but are untested against live endpoints (flagged in README).

## D4. Python 3.12, uv
uv for env + lockfile; Python 3.12 (matches the Playwright Docker image; 3.14 locally is too new for some wheels).

## D5. Sites are static files + a small platform API
Agents write a static site (any HTML/CSS/JS). Forms, checkout and a KV store are platform endpoints (`/api/forms/*`, `/api/checkout`, `/api/kv/*`), like Netlify Forms + Stripe Checkout. This makes deploy instant, freezing exact (copy the files + payment catalog), and the same handler serves the live preview and the frozen grader view. Trade-off: no custom server code; client-side apps cover "working digital product" tasks.

## D6. Sandbox isolation
Docker `--network none` (1 CPU, 1 GB, pid cap) when the sandbox image exists; otherwise a local shell. On macOS the local shell runs under `sandbox-exec` with network denied and writes limited to the workspace (tested). Every external capability is a harness-brokered mock, so no tool can reach the real world. The isolation actually used is recorded in each run's manifest.

## D7. Market = structured demand model + real browsing personas
Per the research (τ²-bench user-sim errors; Vending-Bench demand gaming), CTR/conversion come from an explicit model (targeting precision vs. the task's hidden true audience, creative heuristics, site probe, price vs. sampled willingness-to-pay). A panel of sampled personas then really visits the site in headless Chromium and submits forms or completes test checkout; if real visitors can't convert, extrapolated conversions collapse. LLM personas (optional) only adjust creative appeal and phrase feedback. Fixed seeds per (task, seed, week).

## D8. Physical goods: inventory gates sales; honest pre-orders count
Sales beyond on-hand stock are lost, unless the site offers pre-orders and stock is in transit (60% of those buyers wait). Rewards realistic supplier choices and honest ship-date messaging.

## D9. MockModel is a real baseline, with two profiles
`mock-diligent` (template founder: honest, geo-targeted, iterates) and `mock-hasty` (fake testimonials, "#1" claims, broad targeting, non-responsive layout, no iteration, and a planted grader-directed prompt injection). The scripted baseline doubles as the floor CEO-Bench argued for, and hasty exercises every integrity check and the judge injection guard.

## D10. Anthropic provider: official SDK, no refusal fallback, append-only history
Uses the `anthropic` SDK with adaptive thinking defaults and `output_config.effort`. Server-side refusal fallbacks are deliberately **off**: another model answering would confound results; refusals are logged. Context summarization starts a fresh conversation (task + summary + NOTES.md) instead of editing history, which keeps thinking-block replay valid.

## D11. Frozen sites get their own origin (`<alias>.localhost`)
The grading app routes `http://b-xxxxxx.localhost:8000/` (Host header) to that run's frozen site. Absolute links, forms and JS keep working exactly as deployed. Grader cookies (host-only on `localhost`) are never sent to model-built pages, and the alias keeps model identity hidden. Text responses are scrubbed of model fingerprints on the way out.

## D12. One results.json per round is the source of truth
Dashboard, round report and public site all render from `var/runs/<round>/results.json` (+ bundles). This follows the research lesson about mismatched numbers across pages. The site ships the file as open data.

## D13. Grading app: FastAPI + Jinja, no front-end framework or CDN
It is server-rendered with ~10 lines of vanilla JS for tabs, so it runs offline, needs no build step and is easy to change. SQLAlchemy with SQLite by default or Postgres via `DATABASE_URL`, which compose uses.

## D14. Scripted demo graders are labeled synthetic
To show agreement/QC views without real humans, `shingle demo` fills two `demo-grader-*` accounts, flagged `synthetic`, unable to log in, with judgments derived from LLM-judge means plus bias and noise. One deliberately fails an attention check. The report, dashboard and site all say these are not human judgments.

## D15. Lighthouse when available, built-in audits otherwise
The Docker image installs Lighthouse (pointed at Playwright's Chromium). Locally and in CI, built-in audits score the same four categories from DOM and performance data, and checks.json records which engine ran.

## D16. Verified one-command path is `make dev`; compose validated but not run here
Docker Desktop on the build machine refuses all engine calls until the user signs in to their organization (an admin-enforced policy). `docker-compose.yml` passes `docker compose config`, but couldn't be executed. `make dev` (uv + Playwright; `shingle up` runs the demo and serves app + site) was verified from a clean clone. Listed as an open question for the owner.

## D17. Ports
App on 8000 and site on 8080. Port 8765 is taken by another local app on the build machine, so defaults avoid it.

## D18. Two GitHub repos: public mirror and private source
`Amadeus415/shinglebench` (public) is built from `make public`, so it never contains `tasks/heldout/` or held-out canaries, and its history never has. `Amadeus415/shinglebench-private` holds the full repo and history. Making one repo public would have exposed the held-out set in every past commit. `dist/public` is the public repo's working copy (the export keeps its `.git`). Held-out-only tests skip when the folder is absent, so both repos pass CI.
