import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import agent
from agent import Agent, PRIOR_COLUMNS
from environment import make_environment
from make_submission import build_submission
from scoring_core import CHANNELS, apply_filters, validate_strategy

ROOT = Path(__file__).resolve().parents[1]


def small_env(lift=.3, n=120, contacts=15000, seed=7):
    profile = pd.DataFrame({"ID_NUMBER": range(n), "current_tariff": ["a"] * n,
        "arpu_segment": ["HIGH"] * n, "predicted_arpu": np.linspace(6000, 20000, n),
        "data_segment": ["LITE" if i % 3 else "HEAVY" for i in range(n)],
        "call_segment": ["LOW" if i % 2 else "HIGH" for i in range(n)]})
    tariffs = pd.DataFrame({"tariff_plan_code": ["a", "b", "c"], "price_tariff": [100, 200, 300]})
    model = pd.DataFrame([{"tariff_plan_code_from": "a", "arpu_segment": "HIGH",
        "tariff_plan_code_to": t, "arpu_change_pct": lift, "conversion_rate": .5} for t in ["b", "c"]])
    return make_environment(profile, model, tariffs, CHANNELS, 100000, contacts, lambda *a: (0., 0.), seed=seed)


class AgentTests(unittest.TestCase):
    def test_organizer_files_unchanged(self):
        for record in json.loads((ROOT / "tests/baselines/organizer_hashes.json").read_text(encoding="utf-8-sig")):
            normalized = (ROOT / record["file"]).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(normalized).hexdigest().upper(), record["sha256_lf"])

    def test_no_private_environment_access_or_evaluator_import(self):
        tree = ast.parse((ROOT / "agent.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(a.name in {"math", "numpy", "pandas"} for a in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.module, "pathlib")
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"__closure__", "__globals__", "__dict__", "executed_pilot_campaigns"})

    def test_missing_history_still_uses_pilots_and_returns_scoped_plan(self):
        env, _ = small_env()
        with patch("agent.build_prior", return_value=pd.DataFrame(columns=PRIOR_COLUMNS)):
            a = Agent()
            plan = a.act(env)
        self.assertGreater(len(a.decision_trace["pilots"]), 0)
        self.assertGreaterEqual(len(plan), 1)
        validate_strategy(pd.DataFrame(plan), env.tariffs)
        self.assertTrue(all(c["filter_current_tariff"] == "a" for c in plan))
        self.assertFalse(any("error" in w for w in a.decision_trace["warnings"]))

    def test_error_fallback_retains_tested_population(self):
        env, _ = small_env()
        a = Agent()
        with patch("agent.build_prior", return_value=pd.DataFrame(columns=PRIOR_COLUMNS)), \
                patch.object(a, "_allocate", side_effect=ValueError("injected allocation failure")):
            plan = a.act(env)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["filter_current_tariff"], "a")
        self.assertEqual(plan[0]["filter_arpu_segment"], "HIGH")
        self.assertEqual(plan[0]["channel"], "push")

    def test_negative_evidence_fallback_does_not_expand_audience(self):
        env, _ = small_env(lift=-1.)
        a = Agent()
        with patch("agent.build_prior", return_value=pd.DataFrame(columns=PRIOR_COLUMNS)):
            plan = a.act(env)
        self.assertEqual(len(plan), 1)
        audience = apply_filters(env.customer_profile, pd.Series(plan[0]))
        self.assertLess(len(audience), len(env.customer_profile))
        self.assertIn("profit_not_guaranteed", " ".join(a.decision_trace["warnings"]))

    def test_repeated_pilots_reduce_uncertainty(self):
        a = Agent()
        e = {"sample_n": 200, "weighted_lift": 20., "prior": .1}
        before = a._estimate(e)
        after = a._estimate({**e, "sample_n": 400, "weighted_lift": 40.})
        self.assertLess(after["sd"], before["sd"])

    def test_widespread_harm_stops_further_exploration(self):
        env, _ = small_env(lift=-1.)
        a = Agent()
        a.decision_trace = {"pilots": [], "warnings": []}
        candidate = {"current_tariff": "a", "arpu_segment": "HIGH", "target_tariff": "b", "n": 120, "prior": .3}
        for _ in range(6):
            self.assertTrue(a._pilot(env, candidate, "test"))
        self.assertTrue(a._stop_exploration)
        before = env.pilots_left
        self.assertFalse(a._pilot(env, candidate, "test"))
        self.assertEqual(env.pilots_left, before)

    def test_failed_history_transfer_increases_caution(self):
        a = Agent()
        initial = a._risk_margin()
        a._history_scale = 0.
        self.assertGreater(a._risk_margin(), initial)

    def test_small_contact_budget_keeps_room_for_final_plan(self):
        env, _ = small_env(contacts=100)
        with patch("agent.build_prior", return_value=pd.DataFrame(columns=PRIOR_COLUMNS)):
            plan = Agent().act(env)
        self.assertGreaterEqual(env.remaining_contacts, 1)
        self.assertTrue(plan)

    def test_small_cells_are_supported_without_history(self):
        env, _ = small_env(n=30)
        with patch("agent.build_prior", return_value=pd.DataFrame(columns=PRIOR_COLUMNS)):
            plan = Agent().act(env)
        self.assertTrue(plan)
        self.assertLess(env.pilots_left, 20)

    def test_contradictory_evidence_overrides_historical_prior(self):
        a = Agent()
        estimate = a._estimate({"sample_n": 400, "weighted_lift": -80., "prior": .8})
        self.assertLess(estimate["mean"], 0)

    def test_contact_planner_matches_scoring_order_without_overlap(self):
        env, _ = small_env(n=240, contacts=150)
        a = Agent()
        a._profile = env.customer_profile.sort_values("ID_NUMBER").reset_index(drop=True)
        a.decision_trace = {}
        estimates = [{"current_tariff": "a", "arpu_segment": "HIGH", "target_tariff": t,
                       "mean": .4, "sd": .01, "arpu": 13000.} for t in ["b", "c"]]
        env.remaining_budget = 600
        plan = a._allocate(env, estimates)
        seen = set()
        remaining, money = 150, 600
        for c, trace in zip(plan, a.decision_trace["campaigns"]):
            raw = apply_filters(env.customer_profile, pd.Series(c)).sort_values("ID_NUMBER").head(5000)
            cost = CHANNELS[c["channel"]]["cost_per_contact"]
            n = min(len(raw), remaining, int(money // cost) if cost else remaining)
            ids = set(raw.head(n)["ID_NUMBER"])
            self.assertFalse(ids & seen)
            self.assertEqual(n, trace["planned_contacts"])
            seen.update(ids)
            remaining -= n
            money -= cost * n
        self.assertGreater(len(plan), 0)
        self.assertGreaterEqual(money, 0)
        self.assertGreaterEqual(remaining, 0)

    def test_submission_is_deterministic_even_on_reused_agent(self):
        a = Agent()
        first = build_submission(a, seed=42)
        second = build_submission(a, seed=42)
        pd.testing.assert_frame_equal(first, second)
        self.assertTrue(1 <= len(first) <= 10)

    def test_malformed_history_is_ignored(self):
        with patch("agent.pd.read_csv", return_value=pd.DataFrame({"bad": [1]})):
            self.assertTrue(agent.build_prior("unused.csv").empty)


if __name__ == "__main__":
    unittest.main()
