# Tariff Campaign Planning Agent

**It 1+1** · HackAlem AI · Track 04, Telecommunications · Beeline case.

## 1. Problem and user

A marketing analyst must choose audiences, target tariffs, and communication channels under a limited budget. A tariff change can reduce revenue, contacts have costs, and small pilots give noisy estimates. This agent uses pilot feedback to produce a feasible campaign plan.

All case data and reported financial outcomes are synthetic. Results do not describe the operator's real business.

## 2. Implemented solution

- Historical transitions generate hypotheses; their frequencies are not treated as the audience's true conversion probabilities.
- Up to 12 initial push pilots cover promising cells; the remaining pilot budget goes to the adaptive follow-up loop. Remaining pilots test alternatives or repeat uncertain and unexpectedly strong results.
- Estimates combine historical signals and pilot observations. Contradictory evidence reduces reliance on history; widespread negative observations stop further exploration.
- Audience and channel selection jointly account for budget, contacts, campaign slots, customer ordering, and conversion saturation. Final campaigns do not contact the same customer twice.
- A fallback retains the tested audience filters and reduces exposure when positive effects are uncertain.
- JSON and Markdown reports explain pilot choices, estimates, uncertainty, rejected options, and planned campaigns.

## 3. Main workflow

Profile and history → candidate hypotheses → pilots → history calibration → adaptive follow-up pilots → estimated net value → constrained allocation → `submission.csv`.

The case allows at most **20 pilots**, normally **10–200 contacts per pilot**, and **1–10 final campaigns**. Limits are **5,000 contacts per final campaign**, **15,000 total contacts including pilots**, and **100,000 monetary units**. Push pilots have zero contact cost but consume contacts and may lose revenue. Pilots contribute to the final score.

## 4. Technology

Python, pandas, and NumPy. The recorded validation environment was **Python 3.13.3, pandas 3.0.6, NumPy 2.5.3**; install the versions specified in `requirements.txt`.

The judged selector requires no external API, API key, or LLM call. It makes sequential decisions through the environment's public API. AI coding assistants supported development; there is no runtime language model dependency. Any future LLM explanation layer would be optional and separate from selection.

## 5. Architecture

| Component | Responsibility |
| --- | --- |
| `agent.py: build_prior` | Prepare historical signals; tolerate missing or malformed history |
| `Agent._candidates` | Select up to two target tariffs per current-tariff × ARPU cell |
| `Agent._explore` | Initial coverage, history calibration, alternatives, and repeat pilots |
| `Agent._estimate` | Aggregate observations and estimate approximate uncertainty |
| `Agent._offers` / `_allocate` | Build audiences and compare six greedy allocation variants |
| `Agent._fallback` | Return a plan restricted to a tested audience where feasible |
| `tools/explain_plan.py` | Export explanations using public observations only |
| `tools/benchmark_agent.py` | Paired comparisons and separate synthetic stress fixtures |

The agent uses public environment fields and `run_pilot`; it does not import the evaluator or inspect hidden effects. Organizer files `environment.py`, `scoring_core.py`, `mock_environment.py`, `local_eval.py`, `make_submission.py`, and `agent_template.py` remain unchanged. Tests verify the recorded organizer-file hashes.

## 6. Installation and execution

Use Python 3.13, with 3.13.3 being the tested version. First restore `customer_profile.csv` and the organizer's `data/` directory into the repository root. The directory includes `change_tariff.csv`, `dict_tariff.csv`, `traffic.csv`, and `arpu_monthly.csv`. These input files are intentionally excluded from Git; obtain them from the participant package.

Windows PowerShell, from the repository root:

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

No API keys are required. UTF-8 mode supports the organizer tools' Russian output on Windows.

## 7. Validation and reproduction

After installing dependencies, run these commands with the virtual environment's Python executable (`.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on Linux/macOS):

```sh
python -X utf8 -m unittest discover -s tests -v
python -X utf8 tools/benchmark_agent.py --suite holdout
python -X utf8 tools/benchmark_agent.py --suite stress
python -X utf8 tools/explain_plan.py --seed 42
python -X utf8 make_submission.py
```

The existing **14 tests** cover contact allocation, limits, final-contact overlap, deterministic replay, repeated pilots, negative evidence, small audiences, missing history, fallback filters, and organizer-file integrity. They also check agent imports and prohibited environment access.

The recorded official local evaluation at **seed 42** passed: **4,869,704 net gain**, **93,440 cost**, **9,594 total contacts**, **20 pilots**, and **4 final campaigns**. The evaluator's combined campaign count includes pilots. Repeated generation of `submission.csv` at seed 42 produced identical bytes; other seeds can produce different plans.

## 8. Data and integrations

The customer profile provides current tariff, ARPU and behavioral segments, and `predicted_arpu`. `data/change_tariff.csv` supplies initial hypotheses. `env.tariffs` and `env.channels` define valid actions. Current effects are learned only through pilot responses.

`traffic.csv` and `arpu_monthly.csv` are not read directly because derived features are already available in the profile. The benchmark harness owns its evaluation models separately and never supplies hidden truth to the agent. There is no web service, live API integration, or graphical viewer in this submission.

## 9. Measured results

The final holdout comparison used **seeds 200–219**, selected after development. Policy constants were unchanged after that evaluation. The baseline is the preserved **Claude implementation**, not the organizer's `agent_template.py`.

| Metric | Claude baseline | Current adaptive agent |
| --- | ---: | ---: |
| Median net gain, 20 runs | 4,513,807 | **4,970,133** |
| Minimum | 4,131,959 | **4,710,488** |
| Maximum | 4,708,707 | **5,249,831** |
| Positive runs | 20/20 | 20/20 |
| Invalid plans | 0 | 0 |
| Mean repeated final contacts | 1,280.6 | **0** |

Median gain increased **10.1%**, with wins in **20/20 paired runs**, and the worst result improved by **14%** after shifting four pilots from fixed coverage to the adaptive loop. Recorded `Agent.act` runtime stayed below 0.5 seconds on the development PC. The fixed-exploration ablation's median, **4,955,998**, is slightly below the adaptive agent's **4,970,133**, and its minimum, 3,286,359, is far worse.

Additional authored stress scenarios used 10 seeds each:

| Scenario | Claude median | Adaptive median | Adaptive positive runs |
| --- | ---: | ---: | ---: |
| Weak effects | **611,911** | 352,225 | 10/10 |
| History points in the opposite direction | −983,819 | **−238,783** | 0/10 |
| Near-saturated conversion | 6,342,820 | **6,433,849** | 10/10 |

Conservatism costs profit under weak effects. Stopping exploration reduces losses under reversed history, but cannot undo harmful pilots. These fixtures are diagnostics, not the judges' hidden model.

Full measurements and code hashes: [holdout report](reports/benchmark_holdout.json) and [stress report](reports/benchmark_stress.json). Further explanation, in Russian: [change notes](docs/IMPROVEMENTS.md), [decision report](reports/decision_report.md), and [industry research](docs/INDUSTRY_RESEARCH.md).

## 10. Limitations

- Different seeds of one mock model test pilot noise, not generalization to a different business environment. Hidden evaluation outcomes may differ.
- Candidate selection and greedy allocation restrict the search; global optimality is not guaranteed. Excluding all final-contact overlap can also discard useful partially overlapping campaigns.
- Uncertainty estimates and risk margins are heuristic, not calibrated confidence guarantees. Historical transitions do not identify causal effects by themselves.
- Pilot sample IDs are hidden. Final campaigns may overlap pilots, and the reported projected net does not subtract those overlaps.
- A required nonempty fallback may still lose money. If evidence or limits make a plan infeasible, the agent returns an empty plan with a warning; that output is not a valid submission.
- Reports are lightweight explanation artifacts, not a versioned run-log API. The JSON does not contain an attached official evaluation, and fallback campaigns are not fully represented in its campaign trace.

The original Claude code, CSV, and README are retained in `tests/baselines/` for reproducible comparisons.

## 11. Deployment and submission

Required submission artifacts are in the repository root: **`agent.py`, `submission.csv`, and `requirements.txt`**. Organizer runtime files support local execution; restore the participant data separately as described above. Reports, tools, and tests document and verify the solution.

Submit through the selected case's button on the hackathon platform. Generating a CSV or pushing a Git branch does not itself submit the solution to the platform.
