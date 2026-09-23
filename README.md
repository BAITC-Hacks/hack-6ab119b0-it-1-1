# Beeline Tariff Marketing Campaigns Agent

**It 1+1** · HackAlem AI · Track 04, Telecommunications.

## 1. Problem and user

A marketing analyst must choose audiences, target tariffs, and communication channels within a limited budget. A tariff change can reduce revenue, contacts consume resources, and small pilots provide noisy evidence. This agent learns from pilots and returns a campaign plan.

All case data and financial outcomes are synthetic. They do not describe Beeline's real business.

## 2. Implemented solution

- Historical transitions rank hypotheses and provide an initial estimate; their frequencies are not treated as measured audience conversion probabilities.
- Up to 16 initial push pilots cover promising current-tariff × ARPU cells. Follow-up pilots test alternatives or confirm uncertain and unexpectedly strong results.
- Pilot observations update estimates and reduce reliance on conflicting history. Widespread negative observations can stop further exploration.
- Allocation accounts for channel costs, conversion saturation, audience ordering, budget, contact limits, and campaign slots. Selected final campaigns do not repeat contacts with each other.
- The fallback retains a tested audience and reduces exposure where possible; profitability is not guaranteed.
- `Agent.decision_trace` stores observations, estimates, reasons, and warnings in memory. This four-file package does not include a report exporter or viewer.

## 3. Main workflow and case limits

Profile and history → candidate hypotheses → pilots → history calibration → follow-up pilots → estimated net value → constrained allocation → campaign list.

The organizer's `make_submission.py` runs this workflow at seed 42 and writes `submission.csv`.

| Constraint | Limit |
| --- | ---: |
| Final campaigns | 1–10 |
| Subscribers per final campaign | 5,000 |
| Total contacts, including pilots | 15,000 |
| Total communication cost, including pilots | 100,000 conventional units |
| Pilots | Up to 20, with 10–200 contacts each |
| Runtime | Up to 10 minutes in the participant guide |

Push pilots have no monetary contact cost, but consume contacts and can reduce revenue. Both pilots and final campaigns contribute to the official score. Each subscriber's effect is counted once by the evaluator, while all contact costs are charged.

## 4. Technology and AI use

The tested environment is **Python 3.13.3, pandas 3.0.6, and NumPy 2.5.3**. Direct dependencies are pinned in `requirements.txt`.

The selector needs no network access, API key, or language model at runtime. It makes sequential decisions through the public environment interface. AI coding assistants supported development. The Beeline participant guide describes an LLM in the decision loop as optional; no live LLM integration is claimed here.

## 5. Architecture and repository contents

This branch contains the **minimal submission package**:

| File | Purpose |
| --- | --- |
| `agent.py` | Complete policy, including `Agent.act(env)` |
| `submission.csv` | Four final campaigns generated at seed 42 |
| `requirements.txt` | Pinned Python dependencies |
| `README.md` | Setup, verification, results, and limitations |

Inside `agent.py`, `build_prior` prepares history; `_candidates` proposes targets; `_explore` runs pilots; `_estimate` aggregates evidence; `_offers` and `_allocate` compare feasible plans; `_fallback` handles cases without a suitable regular plan.

The agent uses public environment fields and `run_pilot`. It does not import the evaluator or inspect hidden effects. The policy and dependency pins were adopted unchanged from Adil Rakhaliyev's implementation.

## 6. Installation and execution

1. Obtain and extract the official Beeline participant package.
2. Copy this branch's four files into the package root. Keep the organizer's environment, scorer, evaluator, generator, dictionaries, and data unchanged.
3. Run the commands below **from that assembled package directory**.

The assembled directory must contain `environment.py`, `scoring_core.py`, `mock_environment.py`, `local_eval.py`, `make_submission.py`, `customer_profile.csv`, and the organizer's `data/` directory. The latter includes `change_tariff.csv`, `dict_tariff.csv`, `traffic.csv`, and `arpu_monthly.csv`. These organizer assets are supplied separately; they are not part of this four-file branch.

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -X utf8 local_eval.py
.venv\Scripts\python.exe -X utf8 make_submission.py
```

Linux/macOS:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -X utf8 local_eval.py
.venv/bin/python -X utf8 make_submission.py
```

UTF-8 mode supports the organizer tools' Russian output on Windows. No API keys are required.

## 7. Validation and reproduction

Use the organizer's unchanged tools in the assembled directory. In the commands below, `python` means the virtual environment's executable shown above:

```sh
python -X utf8 local_eval.py
python -X utf8 local_eval.py --runs 10
python -X utf8 make_submission.py
```

Check that evaluation completes, no campaigns are discarded, pilots are used, and resource limits hold. The reported combined campaign count includes pilots: 24 campaigns at seed 42 means 20 pilots plus 4 final campaigns, within the final-plan limit.

Recorded seed-42 evaluation:

| Metric | Result |
| --- | ---: |
| Status | PASS |
| Net gain | 4,941,070 |
| Communication cost | 97,064 / 100,000 |
| Contacts, including pilots | 11,778 / 15,000 |
| Pilots | 20 |
| Final campaigns | 4 |

Generation was verified in separate processes and in a clean export of the development commit using a fresh dependency environment. The submitted campaign content reproduced; repeated generation on the same platform was byte-identical. Windows/Linux line endings may differ. Hidden-environment campaigns may differ from seed 42 because pilot outcomes differ.

Development validation included 14 unit tests. The test suite, benchmark harness, and report-generation tools are not included in this minimal submission package.

## 8. Data and integrations

The profile supplies current tariffs, ARPU and usage segments, and `predicted_arpu`. Historical `data/change_tariff.csv` supplies initial hypotheses. `env.tariffs` and `env.channels` define valid actions, and current effects are learned through pilot responses.

The agent does not read `traffic.csv` or `arpu_monthly.csv` directly because derived features are already in the profile. Customer data remains in the participant package and is not published here. No web service, graphical viewer, or OpenAI post-run analyst is included.

## 9. Measured results and evidence

The recorded development comparison used seeds **200–219** after selecting the policy. The baseline is the earlier Claude implementation, not the organizer's starter template. Policy constants were unchanged after that evaluation.

| Metric | Earlier Claude baseline | Submitted agent |
| --- | ---: | ---: |
| Median net gain, 20 runs | 4,513,807 | **4,897,756** |
| Minimum | **4,131,959** | 3,135,746 |
| Maximum | 4,708,707 | **5,415,687** |
| Positive runs | 20/20 | 20/20 |
| Invalid plans | 0 | 0 |
| Mean repeated final contacts | 1,280.6 | **0** |

Median gain increased 8.5%, with wins in 14/20 paired runs, but the worst result deteriorated. A fixed-exploration ablation reached a higher median of 4,955,998, so the improvement cannot be attributed to adaptive exploration alone. Original holdout measurements of `Agent.act` stayed below 0.5 seconds on the development PC; runtime depends on the environment.

Authored stress fixtures also expose limitations: submitted-agent medians were 311,590 with weak effects, −238,783 with reversed historical signals, and 6,625,070 near conversion saturation. The reversed-history fixture lost money in all ten runs. These are diagnostic simulations, not the hidden judging model or real operator revenue.

## 10. Limitations

- Random seeds of one mock model test pilot noise, not transfer to a different effect model. Profit and leaderboard position are not guaranteed.
- Candidate search is restricted and allocation is greedy; global optimality is not established.
- Follow-up choice and early stopping are adaptive. Pilot size is normally 200 and decreases with eligible audience size or remaining contacts, rather than being optimized from observed uncertainty.
- Uncertainty estimates and risk margins are heuristic, not calibrated confidence guarantees. Historical transitions alone do not identify causal effects.
- Pilot IDs are hidden. Final campaigns can overlap pilots, and the in-memory projected net does not subtract that overlap or represent the full realized official score.
- A fallback can lose money. If no evidence-based feasible fallback can be formed, the agent may return an empty plan, which fails the required 1–10 campaign contract. No such invalid plan occurred in the recorded benchmark series.
- The trace is not a complete reporting API: it has no attached official evaluation, and fallback campaigns are not fully represented in its campaign list.

## 11. Deployment and submission

This is an offline submission; no deployed URL is required. Submit `agent.py`, its generated `submission.csv`, and `requirements.txt` with this README, following the case's platform instructions. Use the separately supplied participant package for local evaluation.

Pushing a Git commit or generating a CSV does not itself complete the platform's **Submit Solution** step.
