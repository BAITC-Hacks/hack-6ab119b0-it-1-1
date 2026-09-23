"""Paired evaluation. Synthetic stress truth stays in this harness, never in agents."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import Agent, build_prior
from environment import make_environment
from mock_environment import make_mock_env
from scoring_core import CHANNELS, apply_filters, score_campaigns, validate_strategy


def baseline_class():
    spec = importlib.util.spec_from_file_location("claude_baseline", ROOT / "tests/baselines/claude_agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Agent


def stress_model(profile, tariffs, scenario):
    """Authored scenarios, not guesses about or access to judge effects."""
    rng = np.random.default_rng(20260923)
    prior = build_prior().set_index(["tariff_plan_code_from", "arpu_segment", "tariff_plan_code_to"])
    rows = []
    cells = profile[["current_tariff", "arpu_segment"]].drop_duplicates().sort_values(["current_tariff", "arpu_segment"])
    for source, segment in cells.itertuples(index=False, name=None):
        for target in sorted(tariffs["tariff_plan_code"]):
            key = (source, segment, target)
            hist = float(prior.loc[key, "arpu_change_pct"]) if key in prior.index else 0.
            if scenario == "weak_signal":
                effect = 0.10 * hist + float(rng.normal(0, 0.06))
                conversion = float(rng.uniform(0.15, 0.6))
            elif scenario == "reversed_history":
                effect = -0.4 * hist + float(rng.normal(0, 0.10))
                conversion = float(rng.uniform(0.15, 0.6))
            elif scenario == "saturated_conversion":
                effect = 0.4 * hist + float(rng.normal(0, 0.08))
                conversion = float(rng.uniform(0.90, 1.0))
            else:
                raise ValueError(scenario)
            rows.append({"tariff_plan_code_from": source, "arpu_segment": segment,
                         "tariff_plan_code_to": target, "arpu_change_pct": float(np.clip(effect, -.9, 2)),
                         "conversion_rate": conversion})
    return pd.DataFrame(rows)


def score_instance(agent, seed, scenario="mock", fixture=None):
    if scenario == "mock":
        # Only the evaluator knows this model. Agent receives the public env only.
        from mock_environment import _mock_impact_model, _mock_fallback
        env, internals = make_mock_env(seed=seed)
        model = _mock_impact_model(pd.read_csv(ROOT / "data/change_tariff.csv"))
        fallback = _mock_fallback
    else:
        profile, tariffs, model = fixture
        fallback = lambda *args: (0., 0.)
        env, internals = make_environment(profile.copy(), model, tariffs, CHANNELS,
                                          100000, 15000, fallback, seed=seed)
    started = time.perf_counter()
    final = agent.act(env)
    elapsed = time.perf_counter() - started
    frame = pd.DataFrame(final)
    errors = []
    try:
        validate_strategy(frame, env.tariffs)
    except (ValueError, KeyError) as exc:
        errors.append(str(exc))
    if not 1 <= len(final) <= 10:
        errors.append("final_campaign_count")
    pilots = internals.executed_pilot_campaigns()
    if not 1 <= len(pilots) <= 20:
        errors.append("pilot_count")
    remaining_contacts = int(env.remaining_contacts)
    remaining_budget = float(env.remaining_budget)
    seen, duplicate_contacts = set(), 0
    for c in final:
        audience = apply_filters(env.customer_profile, pd.Series(c)).sort_values("ID_NUMBER").head(5000)
        n = min(len(audience), remaining_contacts)
        cost = CHANNELS[c["channel"]]["cost_per_contact"]
        if cost:
            n = min(n, int(remaining_budget // cost))
        ids = set(audience.head(n)["ID_NUMBER"])
        duplicate_contacts += len(ids & seen)
        seen.update(ids)
        remaining_contacts -= n
        remaining_budget -= n * cost
    all_campaigns = pd.DataFrame(pilots + final)
    for col in ("filter_arpu_segment", "filter_data_segment", "filter_call_segment", "filter_current_tariff", "explicit_ids"):
        if col not in all_campaigns:
            all_campaigns[col] = None
    result = score_campaigns(all_campaigns, env.customer_profile, model, env.tariffs,
                             env.customer_profile["predicted_arpu"].sum(), fallback)
    if result["total_contacts"] > 15000 or result["total_cost"] > 100000:
        errors.append("resource_limit")
    trace = getattr(agent, "decision_trace", {})
    return {"scenario": scenario, "seed": seed, "net": result["net_arpu_gain"],
            "contacts": result["total_contacts"], "cost": result["total_cost"],
            "final_campaigns": len(final), "pilots": len(pilots), "seconds": elapsed,
            "duplicate_final_contacts": duplicate_contacts, "errors": errors,
            "repeated_pilots": sum(e.get("repeats", 1) - 1 for e in trace.get("estimates", [])),
            "warnings": trace.get("warnings", [])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["development", "holdout", "stress"], default="development")
    parser.add_argument("--start-seed", type=int)
    args = parser.parse_args()
    start = args.start_seed if args.start_seed is not None else (200 if args.suite == "holdout" else 0)
    seeds = range(start, start + (20 if args.suite == "holdout" else 10))
    scenarios = ["weak_signal", "reversed_history", "saturated_conversion"] if args.suite == "stress" else ["mock"]
    agents = {"claude_baseline": baseline_class(), "adaptive": Agent,
              "fixed_exploration": lambda: Agent(adaptive=False)}
    records, summaries = [], []
    for scenario in scenarios:
        fixture = None
        if scenario != "mock":
            profile = pd.read_csv(ROOT / "customer_profile.csv")
            tariffs = pd.read_csv(ROOT / "data/dict_tariff.csv")
            fixture = (profile, tariffs, stress_model(profile, tariffs, scenario))
        for name, factory in agents.items():
            group = []
            for seed in seeds:
                row = {"agent": name, **score_instance(factory(), seed, scenario, fixture)}
                group.append(row)
                records.append(row)
            values = [r["net"] for r in group]
            summary = {"scenario": scenario, "agent": name, "runs": len(group),
                       "median": statistics.median(values), "min": min(values), "max": max(values),
                       "positive": sum(v > 0 for v in values), "invalid": sum(bool(r["errors"]) for r in group),
                       "max_seconds": max(r["seconds"] for r in group),
                       "mean_duplicate_final_contacts": statistics.mean(r["duplicate_final_contacts"] for r in group),
                       "mean_repeated_pilots": statistics.mean(r["repeated_pilots"] for r in group)}
            summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
    path = ROOT / "reports" / f"benchmark_{args.suite}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"suite": args.suite, "start_seed": start,
                               "agent_sha256": hashlib.sha256((ROOT / "agent.py").read_bytes()).hexdigest(),
                               "summaries": summaries, "runs": records},
                               ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
