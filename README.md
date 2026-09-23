# Beeline Tariff Marketing Campaigns Agent

**It 1+1** · HackAlem AI · Track 04, Telecommunications.

## 1. Problem and user

A marketing analyst must choose audiences, target tariffs, and communication channels within a limited budget. A tariff change can reduce revenue, contacts consume resources, and small pilots provide noisy evidence. This agent learns from pilots and returns a campaign plan.

All case data and financial outcomes are synthetic. They do not describe Beeline's real business.

## 2. Implemented solution

- Historical transitions rank hypotheses and provide an initial estimate; their frequencies are not treated as measured audience conversion probabilities.
- Up to 16 initial push pilots cover promising current-tariff × ARPU cells. Follow-up pilots test alternatives or confirm uncertain and unexpectedly strong results.
- Pilot size is chosen from 50–200 contacts using observed lift, uncertainty, and the value of additional evidence. Positive pilots retain larger samples because pilots themselves contribute to the score; negative evidence can reduce exposure. Audience and resource caps can reduce the actual size further, with a minimum of 10.
- Each successful pilot recalibrates reliance on history. Conflicting observations across at least three cells can trigger a limited search of historically weak alternatives, including previously untested cells. Negative history is never inverted into an assumed positive final effect.
- Early stopping uses negative observations weighted by actual contact counts. At most two new history-challenge hypotheses are attempted without a repeatedly confirmed positive alternative; repeat pilots remain possible within the total pilot budget.
- Allocation accounts for channel costs, conversion saturation, audience ordering, budget, contact limits, and campaign slots. Selected final campaigns do not repeat contacts with each other.
- The fallback retains a tested audience and reduces exposure where possible; profitability is not guaranteed.
- `Agent.decision_trace` stores observations, estimates, requested and actual pilot sizes, size-selection reasons, history calibration, and warnings in memory. This four-file package does not include a report exporter or viewer.

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

The updated package was verified on Windows with **Python 3.13.3, pandas 3.0.6, and NumPy 2.5.3**. Direct dependencies are pinned in `requirements.txt`.

The selector needs no network access, API key, or language model at runtime. It makes sequential decisions through the public environment interface. AI coding assistants supported development. The Beeline participant guide describes an LLM in the decision loop as optional; no live LLM integration is claimed here.

The event-wide rules separately require OpenAI API use. This offline package contains no OpenAI API integration and does not by itself demonstrate fulfillment of that requirement.

## 5. Architecture and repository contents

This branch contains the **minimal submission package**:

| File | Purpose |
| --- | --- |
| `agent.py` | Complete policy, including `Agent.act(env)` |
| `submission.csv` | Four final campaigns generated at seed 42 |
| `requirements.txt` | Pinned Python dependencies |
| `README.md` | Setup, verification, results, and limitations |

Inside `agent.py`, `build_prior` prepares history; `_candidates` proposes targets; `_pilot_size` chooses exposure; `_explore` runs pilots; `_calibrate_history` updates the historical weight; `_estimate` aggregates evidence; `_offers` and `_allocate` compare feasible plans; `_fallback` handles cases without a suitable regular plan.

The agent uses public environment fields and `run_pilot`. It does not import the evaluator or inspect hidden effects. The adaptive policy extends Adil Rakhaliyev's submitted implementation; allocation, fallback behavior, and dependency pins are unchanged.

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

The four submission files were copied into a separate directory with the unchanged organizer assets and checked using the versions listed above. All 30 development tests passed there, including checks of organizer-file integrity, public-interface use, adaptive decisions, and the benchmark harness. Those author-written tests and the synthetic benchmark tools are not part of this minimal package.

Two separate generator processes reproduced identical CSV bytes. The generated plan remains the same as the previous submission at seed 42; the adaptive behavior appears under different pilot observations. Its SHA-256 after normalizing line endings to LF is `318ff0ec37b05076e0e6fda84888bab69fe9815bdcc0337dad65cdcd2b4f22b1`. Hidden-environment campaigns may differ from seed 42 because pilot outcomes differ.

## 8. Data and integrations

The profile supplies current tariffs, ARPU and usage segments, and `predicted_arpu`. Historical `data/change_tariff.csv` supplies initial hypotheses. `env.tariffs` and `env.channels` define valid actions, and current effects are learned through pilot responses.

The agent does not read `traffic.csv` or `arpu_monthly.csv` directly because derived features are already in the profile. Customer data remains in the participant package and is not published here. No web service, graphical viewer, or OpenAI post-run analyst is included.

## 9. Results and comparison

The organizer command `python -X utf8 local_eval.py --runs 10` evaluates seeds **0-9**. The current package produced the following net gains, rounded to whole conventional units:

| Metric | Submitted agent |
| --- | ---: |
| Median net gain | 5,079,841 |
| Minimum | 3,841,132 |
| Maximum | 5,393,947 |
| Positive runs | 10/10 |

Different seeds change pilot randomness; they do not change the mock business-effect model. These results do not establish profit under hidden judging effects.

The policy was frozen before two additional comparisons against the previous submitted algorithm. Suite A uses pilot seeds 300–329 and synthetic-model seed 20260924; suite B uses pilot seeds 500–519 and model seed 20260925. Each suite has one effect model per scenario, with repeated pilot noise. The table reports median net gain computed by the organizer's scorer, including pilots and final campaigns.

| Scenario | A: previous | A: adaptive | B: previous | B: adaptive |
| --- | ---: | ---: | ---: | ---: |
| Official mock | 4,965,396 | 4,950,250 | 4,921,984 | 4,933,396 |
| Weak effects | 289,202 | 289,202 | 274,403 | 274,403 |
| Reversed history | -380,967 | -223,971 | -380,050 | 2,327,452 |
| Saturated conversion | 6,548,377 | 6,562,293 | 8,369,764 | 8,566,427 |
| Mixed historical transfer | 1,499,618 | 4,119,049 | 1,034,304 | 947,047 |
| Effects independent of history | 189,525 | 189,525 | 8,103,125 | 8,103,125 |
| All effects negative | -423,337 | -358,931 | -359,672 | -323,925 |

All 700 executions of these two policies returned valid plans in these normal-operation scenarios. Suite A's maximum adaptive `Agent.act` time was 0.474 seconds. Synthetic scenarios were generated for development and evaluation; they are not the hidden judging model. Their benchmark harness and raw reports are maintained outside this four-file submission, so the organizer commands above reproduce the mock results only.

The gains have material tradeoffs. In suite A, the mock median fell about 0.3%; reversed history still lost money in 26/30 runs and its worst result worsened from -953,622 to -1,056,024. Positive runs with history-independent effects fell from 25/30 to 24/30. In suite B, reversed history improved to 16/20 positive runs versus 1/20, but the mixed-transfer median fell 8.4% (19 pairs tied and one lost; mean net fell about 1.3%). All-negative median losses improved in both suites, while suite B's lower tenth percentile worsened. The policy does not dominate the previous version in every scenario or tail of the distribution.

## 10. Limitations

- Random seeds of one mock model test pilot noise, not transfer to a different effect model. Profit and leaderboard position are not guaranteed.
- Candidate search keeps up to two leading targets plus up to two historically weak alternatives per audience cell. Coverage beyond the initial cells depends on detecting conflicting history; it is not exhaustive. Allocation is greedy; global optimality is not established.
- The historical prior closely matches how the supplied mock computes effects. Strong mock results do not establish robustness when history is misleading or current effects change direction.
- Smaller pilots trade lower exposure for less precise evidence and potentially lower direct pilot earnings. Online calibration is a heuristic regression through the origin, not a correlation measure or proof that historical effects transfer.
- Uncertainty estimates and risk margins are heuristic, not calibrated confidence guarantees. Historical transitions alone do not identify causal effects.
- Pilot IDs are hidden. Final campaigns can overlap pilots, and the in-memory projected net does not subtract that overlap or represent the full realized official score.
- A fallback can lose money. If no evidence-based feasible fallback can be formed, the agent may return an empty plan, which fails the required 1–10 campaign contract. A failed or non-finite first pilot observation can trigger this behavior; automatic retry is not implemented. The ten mock runs above completed with valid final plans.
- The trace is not a complete reporting API: it has no attached official evaluation, and fallback campaigns are not fully represented in its campaign list.

## 11. Deployment and submission

This is an offline submission; no deployed URL is required. Submit `agent.py`, its generated `submission.csv`, and `requirements.txt` with this README, following the case's platform instructions. Use the separately supplied participant package for local evaluation.

Pushing a Git commit or generating a CSV does not itself complete the platform's **Submit Solution** step.
