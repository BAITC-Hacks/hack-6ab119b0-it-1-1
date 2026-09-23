# Beeline execution plan

Prepared 2026-09-23. Updated after Human clarification: both teammates are available and THREE HOURS remain from that reply. Status: planned, not implemented or benchmarked. The three-hour cut below supersedes earlier five-hour schedules.

## 1. Outcome and scope

Build a reproducible marketing agent that uses pilot evidence to return 1-10 valid campaigns within all resource limits. Provide a Russian-language run viewer and an OpenAI analyst that explains the evidence behind the plan. Ship the evaluator-compatible Python submission, English README, reproducible results and a two-minute demo.

Track 04 is selected according to the Human/Lead decision in `discuss/threads/001-case-choice.md`. Team: Balgynbek owns policy/backend; frontend teammate owns viewer and README/demo. Agents assist both; humans retain individual contribution and commit ownership. Do not reopen track selection automatically if a gate fails: report the concrete blocker and salvage the selected case first.

Success has two levels:

- Submission validity: public interface, pilots actually influence decisions, valid campaigns, resource compliance, reproducible CSV, time limit and mandatory OpenAI use in the product.
- Competitive evidence: improvement over the provided template on paired local runs, bounded downside, useful pilot decisions and a clear explanation of the improvement. Local mock performance is not a prediction of hidden ranking.

Do not build authentication, a general chat product, a new database schema for every run, a generic optimizer, model training infrastructure or a new evaluator. Use the provided scoring/evaluation scripts unchanged. Deployment is optional and cannot delay submission.

## 2. Known facts and unanswered questions

Verified: complete participant ZIP downloaded and inspected; audience has 23,441 rows; historical changes have 14,823 rows; official template/evaluator/generator present. SHA-256 and sources: `discuss/beeline-pack-review.md`. Runtime and live OpenAI access are not verified by this planning work.

Latest Lead instructions allow project-local dependency installation. Global installs/settings remain out of scope. Pushing remains separately controlled by T-015. Existing approved actions need no repeated permission request. Planning does not start implementation or commit/push code.

Human answers received:

1. Both teammates available now; deadline in three hours. Treat reply time as T0, and use T0+180 minutes as the hard deadline. Do not restart this clock after planning.
2. Key supplied and saved in gitignored root `.env`, permissions 0600. Human says all models approved. `OPENAI_MODEL=gpt-5.4-mini` configured; actual API authentication/access is still untested.
3. Cache/model-selection interpretation unknown; Human asks us to plan around it. Default to a deterministic selector and a substantive live analyst over run evidence, with no submission dependence on model-output caches. Clarification can refine the design but cannot stall the baseline.

Model choice: start with `gpt-5.4-mini`, short structured output and low reasoning effort where supported by the wrapper. Official documentation lists Responses API, function calling and structured output support and positions it for efficient workloads. This is a task-fit choice, not a measured latency result. `gpt-4.1-mini` is the fallback candidate if a smoke test shows access or latency problems; otherwise use the deterministic analysis fallback visibly. References: https://developers.openai.com/api/docs/models/gpt-5.4-mini and https://developers.openai.com/api/docs/models/gpt-4.1-mini. Keep the model configurable and avoid a multi-model benchmark during the three-hour window.

Organizer facts to resolve during intake, without stalling independent work:

- Five-minute offline template guidance versus ten-minute API-enabled guide: target selector completion comfortably below five minutes until clarified.
- How net-result ranking relates to the 100-point rubric; do not assume points are automatically earned by a technique.
- Judging launch directory, allowed accompanying modules/data, environment variables and cache policy.
- Exact public pilot signal meaning, channel scaling, sampling/caps, public resource accounting and supported filters.
- If every observed option looks harmful, the requirement still says 1-10 campaigns. Clarify permitted low-exposure fallback; do not claim a guaranteed profitable action.

## 3. Owners and coordination

| Owner | Work | Files owned |
|---|---|---|
| Balgynbek with Builder/Codex | Intake, policy, constraints, evaluation, OpenAI integration, package | `beeline/`, backend AI adapter, Python checks |
| Frontend teammate with their agent | Viewer, schema fixture, user states, README/demo evidence | `frontend/`, agreed documentation |
| Lead | Resolve organizer questions, review policy changes, coordinate integration and submission | Lead-owned `sync/INBOX.md` |
| Independent Codex reviewers | Policy review and delivery review; bounded follow-ups | Review messages only unless explicitly assigned files |

One writer per implementation file. Agree the run-log contract before parallel builds. Integrate at least every 45 minutes. Use task branches and each human's own commits; do not fabricate authorship. Avoid assigning independent agents overlapping edits to policy, Makefile or API client.

The existing T-010..T-021 IDs are retained. This plan identifies corrections to their acceptance criteria; Lead should reconcile its owned inbox. Do not silently edit the inbox or overwrite another agent's status.

## 4. Architecture and reproducibility

```text
Official environment -> Agent.act(env) -> deterministic adaptive policy -> campaigns
                                    -> sanitized run log
Official evaluator -----------------> actual local result + evaluation label
Saved run log -> React viewer -> thin FastAPI analyst -> existing OpenAI client
Official submission generator ------> submission.csv
```

The judged selector must run without the web server, browser, API key or model availability. It uses public environment APIs only. It must not inspect hidden effects, closures, organizer private files or exploit mock internals.

Keep organizer files unchanged under `beeline/`, with a thin `agent.py` and small policy modules: candidates/prior, pilots/estimate, plan/validation and runlog. Resolve data paths explicitly and test the organizer's documented launch command. Do not assume the backend's `uv package=false` configuration makes `app` importable from the standalone agent.

Default OpenAI integration is a meaningful analyst workflow over a completed run: inspect candidate/pilot evidence, compare a rejected and selected alternative, and explain the final allocation with references to recorded quantities. All model calls go through `backend/app/ai/client.py`; expose analysis capabilities as typed tools. Preserve the backend wrapper rather than creating a second direct SDK client in `beeline/policy/llm.py`.

This default preserves deterministic campaign replay. If organizers require model-dependent selection, promote the hypothesis-ranking adapter only after its cache/replay rules are confirmed. Cache keys must include stable serialized inputs, prompt/model/schema/policy versions; validate responses and commit only permitted sanitized synthetic-data cache artifacts. A cache miss cannot silently create a different seed-42 submission. Temperature zero alone is not a reproducibility guarantee.

The existing wrapper has 60-second timeouts, retries and DB imports; configure bounded per-call behavior and test failures before using it in a timed selector. Structured fallback output must be validated, not assumed valid because `model_construct` succeeded. Keep secrets in environment variables and model names configurable; do not assume all models accept the same sampling parameters.

Live OpenAI use is required for the product and must be demonstrated before freeze. Missing-key/API-error behavior still works and is visibly labeled. An offline fallback alone does not satisfy the event's OpenAI requirement.

## 5. Policy, simple first and evidence-driven

### Step A: inspect the public contract and preserve baseline

Run the unmodified provided template via a copied `agent.py` in an isolated baseline workspace. Record version/hash, seed, elapsed time, pilots, campaigns, budget, contacts, net result and discarded-campaign messages. Preserve the baseline without changing official scripts.

Record pilot field semantics before calculations: whether lift includes channel effectiveness, what population it averages over, actual sample size and costs, final audience cap/order, valid filters and pilot/final overlap. Confirm semantics through public documentation and legitimate interface inspection; never infer policy constants from hidden/mock ground truth.

### Step B: deterministic candidate generation

- Begin with exact current-tariff x ARPU-segment cells; avoid pooling small tariffs with potentially different transition effects merely to meet an arbitrary size threshold.
- Precompute candidate masks, audience counts and predicted-ARPU sums. Refine using supported data/call filters only when the public contract permits it.
- Use historical relative ARPU changes as weak priors; guard zero/tiny denominators, nonfinite values and tiny samples. Estimate with robust summaries and documented shrinkage, with deterministic fallback when history is unavailable.
- Shortlist a small, diverse set of candidate families; retain some exploration outside historical winners because the target population differs. Target count is chosen to fit the 20-pilot budget, not a promise to test every tariff.

### Step C: adaptive pilots

Initial budget sketch: 8 screening pilots of roughly 40-60 customers, up to 8 confirmation pilots of 150-200, up to 4 reserved for unresolved decisions. These are initial policy settings, not validated optimal constants. Respect eligible audience size, minimum sample size and remaining resources before every call.

Prefer follow-up experiments whose results could change the selected portfolio. A large, uncertain audience may warrant more information than a tiny audience with a high observed ratio. Reserve final campaign budget/contacts before exploration. Stop when information is unlikely to change the decision or the runtime/resource reserve is reached.

Use pilot observations and their actual sample sizes. Do not use historical individual ARPU variance as if it were the noise variance of a pilot estimate. Start with transparent point estimates, repeatability and sample-size labels. Use calibrated probabilistic bounds only if the public observation model or empirical evidence supports them; otherwise call uncertainty a heuristic, not a confidence interval.

### Step D: campaign selection and safety checks

Calculate expected incremental value using actual selected-audience value and costs. Apply channel efficiency exactly once, depending on the confirmed signal units. Consider resource opportunity cost, not just the largest raw gain or highest ARPU tier.

Start with one target/channel per disjoint final cell. Final cells can still overlap pilot participants, so final disjointness is not proof of global deduplication. Model overlap only using exposed information and label unobservable parts as estimates. The official evaluator supplies realized local totals after the run.

Validate actual supported audience masks, not estimated averages. No arbitrary audience-size field exists in the documented campaign output; split with supported filters or skip a candidate that cannot fit. Respect cap and sampling semantics confirmed during intake.

Maintain the <=10 final campaigns, <=5,000 people per campaign, <=15,000 total contacts including pilots, <=100,000 cost including pilots and <=20 pilots of 10-200. Do not trust sanitization to silently repair policy output.

Handle all-nonpositive signals explicitly: reserve resources for at least one valid low-exposure campaign, choose the best defensible legal option using observed estimates, and log the unfavorable evidence. A free channel can still cause negative uplift and consumes contacts. If no representable nonempty audience is feasible, flag a contract failure rather than fabricate IDs or promise a guarantee the interface cannot support.

Use deterministic ordering, stable tie-breaks and seeded local randomness. Optional logging or model failure cannot destroy a valid plan. Keep an independent wall-clock guard with enough time reserved to validate and return.

## 6. Run-log contract and UI

Agree `runs/SCHEMA.md` and one valid fixture before independent work. Implement matching Python validation and TypeScript types; schema version 1. Suggested fields:

| Field | Purpose |
|---|---|
| `schema_version`, `run_id`, `policy_version`, `seed`, `environment` | Provenance; environment says mock, never implied live business |
| `mode`, `started_at`, `duration_ms`, `warnings` | Live-analysis/fallback/cache state, performance and limitations |
| `limits`, `resources` | Initial/current budget, contacts and pilot counts; distinguish observed from projected |
| `candidates[]` | Stable ID, supported filters, target, audience count/value, prior and evidence count |
| `pilots[]` | Candidate ID, channel, requested/actual n, cost, observed lift, estimate before/after, next-action reason |
| `campaigns[]` | Exact submitted fields, audience count, projected cost/net, selection rationale |
| `evaluation` | Nullable official local net result and validity findings, source/seed explicitly labeled |
| `analysis` | Nullable OpenAI explanation, evidence references and mode; no invented metrics |

Never invent an evaluator seed or actual net result inside `act(env)` when not exposed. Attach evaluator metadata after execution without changing the official scoring code. Avoid NaN/Infinity in JSON. IDs must remain stable across replay; timestamps/log filenames must not affect campaign selection.

Frontend starts with file import or a bundled sanitized fixture; no backend dependency for viewing saved runs. All network requests go through `frontend/src/api.ts`. Backend analyst accepts validated run summaries and returns evidence-linked analysis. Defer a browser-triggered evaluator runner until the core submission is safe.

Screens: summary metrics, pilot timeline, candidate comparison, final campaign table, warnings and analysis. Explicitly separate predicted net gain from evaluator-measured net gain. Use conventional units (`у.е.`), not the scaffold's tenge formatter. Show invalid-file, loading, empty-run, no-key, API-error and cache modes. Do not show calibrated intervals unless calibration exists.

## 7. Timeline and scope cuts

Human confirmed THREE HOURS remaining. T0 is the time of that confirmation, not the start of implementation. D = T0 + 180 minutes. Begin with simple pilot estimates; calibrated Bayesian uncertainty, generalized optimization, selection-changing LLM calls, deployment and elaborate charts are outside this timebox.

| Time from T0 | Backend/policy owner | Frontend owner | Exit condition |
|---|---|---|---|
| 0-20 min | T-010 environment, template run/CSV, public contract facts; freeze minimal schema | Setup, file import, summary/table on fixture | Runnable baseline or exact blocker; fixture agreed |
| 20-70 min | T-011 exact cells, weak historical ranking, pilot feedback, legal final plan, resource tests, run log | T-020 pilot/campaign tables, warnings and real-log integration; README skeleton | Valid deterministic agent and visible output |
| 70-100 min | T-013 one bounded OpenAI analyst call through shared client; fallback and live smoke test; three paired seeds | Analysis display, actual-versus-estimated labels, finish mandatory user states | Real API contribution and usable no-key mode |
| 100-120 min | One policy improvement only if justified; ten paired seeds only if they fit; replay tests | README factual results, screenshot, demo script | Feature freeze at T+120 |
| 120-150 min | T-014 clean install/replay, `make check`; T-015 authorized push and first submission | Clean viewer build/import, package/docs cross-check | Submission exists at least 30 minutes before deadline |
| 150-180 min | Fix submission-breaking issues only; verify final revision and platform state | Rehearse and capture backup demo | Final code and submitted artifacts agree |

At gate failure: use the first 20 minutes to expose the exact issue; do not spend an hour recreating supplied infrastructure. Report a critical environment blocker immediately and choose a minimal repair. At T+70, if v1 is not valid, stop statistical enhancements and fix validity. At T+100, if OpenAI is not working, prioritize the single live analyst path over extra experiments. Freeze by T+120. Cut charts, extensive seed sweeps, deployment, cache-based ranking and advanced priors first. Never cut valid submission generation, mandatory product API use, fallback, essential tests or README.

## 8. Tasks and acceptance

- [ ] T-010, Balgynbek/Builder: verified pack and pinned local environment; template single run and three seeds; official submission generated; public contract facts documented.
- [ ] Contract, Balgynbek + frontend: schema and fixture agreed; Python/TS validation; no fabricated actual metrics.
- [ ] T-011, Balgynbek/Codex: deterministic pilot-driven v1; all hard constraints verified; edge-case tests; exact valid campaign fields; serializable run log.
- [ ] T-020, frontend: saved-run viewer works independently, then real logs and analyst integration; Russian text and conventional units.
- [ ] T-012, Balgynbek: paired template/v1/final comparisons; median, mean, minimum, positive-run count, invalid-run count and duration; one ablation if time.
- [ ] T-013, Balgynbek: OpenAI analyst through shared client; bounded calls; evidence references; live mode verified; missing-key/error fallback; no policy drift.
- [ ] T-014, Balgynbek + frontend: reproducible package, replay, clean-machine commands, build/check coverage and artifacts.
- [ ] T-021, frontend with backend review: verified English README in 11 sections, methodology, limitations, baseline comparison, demo and disclosure.
- [ ] T-015, Human/authorized owner: approved push to platform repo and platform submission; both humans have own contributions; final revision checked.

Correct earlier acceptance wording: beating the template mean and staying positive on every seed are optimization targets, not official validity rules. Failing those goals requires investigation and honest reporting, not endless tuning against mock effects. A higher mean with severe new downside is not automatically a better policy.

## 9. Verification and command integration

Use repository commands `make setup`, `make dev`, `make test`, `make check`. Implementation must extend these existing targets to cover Beeline installation/tests/lint and the viewer. The current `make check` checks only the old backend/frontend; until updated, a green result is not proof the submission is tested. Avoid requiring unnecessary global changes or discarding backend code that still owns the OpenAI wrapper.

Official case commands are an additional required contract, run from the documented Beeline directory with its environment active:

```text
python local_eval.py
python local_eval.py --runs 3
python local_eval.py --runs 10
python make_submission.py
```

Validation order:

1. Baseline executes and generates a CSV; record any invalid/empty output honestly.
2. Unit/contract tests: valid filters/targets/channels, exact resource boundaries, minimum pilot eligibility, missing history, nonfinite priors, all-negative results, unsupported audience reduction, optional logging/API errors.
3. Semantic tests: changing supplied pilot observations changes relevant estimates/decisions; no hidden-state access; model analysis cannot modify submitted campaign fields.
4. Official evaluator: no discarded campaigns, pilots >0, all constraints respected. Run paired seeds for a descriptive comparison; reserve separate seeds for final checks after selecting logic.
5. Reproducibility: two fresh agent instances/processes generate equivalent CSVs with seed 42; timestamps/log output do not matter. Test documented cache/no-key paths separately and state which artifacts/mode reproduce the submitted CSV.
6. End-to-end: actual saved run opens in UI; evaluator result is correctly labeled; OpenAI explanation cites run facts; no-key/API-error mode remains usable.
7. Clean checkout/environment: pinned dependencies, commands from README, `make check`, official evaluator and generated submission comparison. Frontend dependencies are unnecessary for pure judge execution; document both paths.

## 10. Submission, rubric and demo

Map official requirements to evidence: task fit 25 (valid interface and hero flow), technical implementation 25 (pilot-driven logic and justified choices), README/reproducibility 25 (clean replay and exact instructions), value 15 (net-gain/resource interpretation), originality/potential 10 (demonstrated useful adaptation). These are the supplied rubric categories, not a claim about exact leaderboard weighting.

Package `agent.py`, every imported policy module, permitted supplied data/runtime files, pinned requirements, generated `submission.csv`, permitted cache if used, README and a sanitized representative run. Confirm the organizer accepts the module layout. Preserve original starter attribution. No secrets, virtual environments, private API access notes, arbitrary local logs or speculative claims.

Two-minute demo:

- 0:00-0:20: explain why a tariff change can lose money and show fixed resources.
- 0:20-0:55: inspect one actual pilot decision and how evidence changes a candidate estimate.
- 0:55-1:20: show the final valid campaign plan, resources and actual mock result, distinct from forecast.
- 1:20-1:40: OpenAI analyst explains a selected/rejected alternative using recorded evidence.
- 1:40-2:00: show baseline comparison, reproducibility and hidden-effect limitation.

If no pilot genuinely reversed a decision, do not invent one for the demo. Use a real evidence-based choice. Capture a backup recording and keep a deterministic saved-run demo. Do not claim real Beeline revenue gains from synthetic data.

## 11. Immediate next action

Begin T-010 using the supplied archive under the team's task workflow. In parallel, frontend works from the agreed fixture. Deadline duration and local key configuration are resolved; actual API access and evaluator execution remain to be tested. This planning document is ready to execute. The three-hour cut takes precedence over the larger optional design space above.
