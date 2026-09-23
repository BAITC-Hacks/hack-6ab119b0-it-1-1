"""Pilot-driven tariff planner. Only the documented public agent API is used.

History ranks experiments; pilots estimate current-audience effects. Allocation
accounts for ID-ordered contacts, budget, slots and overlapping final audiences.
No organizer model, private state, evaluator or network API is accessed.
"""
from pathlib import Path
import math

import numpy as np
import pandas as pd

PER_CUSTOMER_STD = 0.804
MAX_CAMPAIGNS = 10
MAX_CUSTOMERS_PER_CAMPAIGN = 5000
PILOT_SIZE = 200
FIRST_PASS_CELLS = 12
MIN_CELL = 50
PRIOR_SD = 0.10
HISTORY_WEIGHT = 1.0
RISK_MARGIN = 0.5
ARPU_BINS = [-np.inf, 1000, 5000, np.inf]
ARPU_LABELS = ["LOW", "MID", "HIGH"]
PRIOR_COLUMNS = ["tariff_plan_code_from", "tariff_plan_code_to", "arpu_segment",
                 "arpu_change_pct", "transition_share", "count"]


def build_prior(path=None):
    """Historical ranking signal. Transition share is NOT audience conversion."""
    empty = pd.DataFrame(columns=PRIOR_COLUMNS)
    source = Path(path) if path is not None else Path(__file__).resolve().parent / "data/change_tariff.csv"
    try:
        df = pd.read_csv(source)
        required = ["AVG_ARPU_PREV_3M", "AVG_ARPU_NEXT_3M", "tariff_plan_code_from",
                    "tariff_plan_code_to", "ID_NUMBER"]
        if not set(required).issubset(df):
            return empty
        for col in required[:2]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
        df = df[df["AVG_ARPU_PREV_3M"] >= 100].copy()
        if df.empty:
            return empty
        df["arpu_segment"] = pd.cut(df["AVG_ARPU_PREV_3M"], ARPU_BINS, labels=ARPU_LABELS)
        df["arpu_change_pct"] = ((df["AVG_ARPU_NEXT_3M"] - df["AVG_ARPU_PREV_3M"])
                                  / df["AVG_ARPU_PREV_3M"]).clip(-1, 3)
        grouped = (df.groupby(["tariff_plan_code_from", "tariff_plan_code_to", "arpu_segment"], observed=True)
                     .agg(arpu_change_pct=("arpu_change_pct", "mean"), count=("ID_NUMBER", "size"))
                     .reset_index())
        total = grouped.groupby(["tariff_plan_code_from", "arpu_segment"], observed=True)["count"].transform("sum")
        grouped["transition_share"] = grouped["count"] / total
        return grouped[PRIOR_COLUMNS]
    except (OSError, ValueError, KeyError):
        return empty


class Agent:
    def __init__(self, adaptive=True, history_weight=HISTORY_WEIGHT):
        self.adaptive = adaptive
        self.history_weight = float(history_weight)
        self.decision_trace = {}
        self._evidence = {}
        self._history_scale = 1.0
        self._stop_exploration = False

    def act(self, env):
        self._evidence = {}
        self._history_scale = 1.0
        self._stop_exploration = False
        self.decision_trace = {"policy": "adaptive-pilots/contact-aware-allocation",
            "pilots": [], "estimates": [], "campaigns": [], "rejected": [], "warnings": []}
        try:
            self._profile = env.customer_profile.sort_values("ID_NUMBER").reset_index(drop=True).copy()
            self._profile["predicted_arpu"] = (pd.to_numeric(self._profile["predicted_arpu"], errors="coerce")
                .replace([np.inf, -np.inf], np.nan).fillna(0).clip(lower=0))
            candidates = self._candidates(env, build_prior())
            self._explore(env, candidates)
            estimates = [self._estimate(e) for e in self._evidence.values()]
            self.decision_trace["estimates"] = [self._public_estimate(e) for e in estimates]
            for e in estimates:
                if e["mean"] - self._risk_margin() * e["sd"] <= 0:
                    self.decision_trace["rejected"].append({"current_tariff": e["current_tariff"],
                        "arpu_segment": e["arpu_segment"], "target_tariff": e["target_tariff"],
                        "reason": "insufficient_lift_after_uncertainty_margin", "mean": e["mean"], "sd": e["sd"]})
            return self._allocate(env, estimates) or self._fallback(env)
        except Exception as exc:
            self.decision_trace["warnings"].append(f"planner_error: {type(exc).__name__}: {exc}")
            return self._fallback(env)

    def _candidates(self, env, prior):
        cells = (self._profile.groupby(["current_tariff", "arpu_segment"], observed=True)
                 .agg(n=("ID_NUMBER", "size"), arpu=("predicted_arpu", "mean")).reset_index())
        substantial = cells[cells["n"] >= MIN_CELL]
        cells = substantial if len(substantial) else cells[cells["n"] >= 10]
        known = sorted(env.tariffs["tariff_plan_code"].dropna().unique())
        candidates = []
        for cell in cells.to_dict("records"):
            hist = prior[(prior["tariff_plan_code_from"] == cell["current_tariff"])
                         & (prior["arpu_segment"] == cell["arpu_segment"])]
            options = []
            for r in hist.to_dict("records"):
                target = r["tariff_plan_code_to"]
                if target == cell["current_tariff"] or target not in known:
                    continue
                signal = float(r["arpu_change_pct"] * r["transition_share"] * 0.5)
                options.append((signal, target))
            if not options:
                options = [(0.0, t) for t in known if t != cell["current_tariff"]]
            elif any(signal > 0 for signal, _ in options):
                options = [(signal, target) for signal, target in options if signal > 0]
            options.sort(key=lambda v: (-v[0], v[1]))
            for rank, (signal, target) in enumerate(options[:2]):
                c = {**cell, "current_tariff": str(cell["current_tariff"]),
                     "arpu_segment": str(cell["arpu_segment"]), "target_tariff": str(target),
                     "prior": signal, "rank": rank}
                c["value"] = max(signal, 0.0001) * float(c["arpu"]) * min(int(c["n"]), 5000)
                candidates.append(c)
        return sorted(candidates, key=lambda c: (-c["value"], c["current_tariff"], c["target_tariff"]))

    @staticmethod
    def _key(c):
        return c["current_tariff"], c["arpu_segment"], c["target_tariff"]

    def _risk_margin(self):
        # Require stronger evidence when current pilots fail to confirm history.
        return RISK_MARGIN + (1. - self._history_scale)

    def _estimate(self, evidence):
        n = evidence["sample_n"]
        variance = PER_CUSTOMER_STD ** 2
        prior_mean = self.history_weight * self._history_scale * evidence["prior"]
        observed = evidence["weighted_lift"] / max(n, 1)
        # Contradictory pilot evidence weakens the prior for this particular cell.
        prior_variance = PRIOR_SD ** 2 + max(0., (observed - prior_mean) ** 2 - variance / max(n, 1))
        precision = 1 / prior_variance + n / variance
        mean = (prior_mean / prior_variance + evidence["weighted_lift"] / variance) / precision
        return {**evidence, "mean": float(mean), "sd": float(math.sqrt(1 / precision))}

    @staticmethod
    def _public_estimate(e):
        return {k: e[k] for k in ("current_tariff", "arpu_segment", "target_tariff", "prior",
                                  "sample_n", "repeats", "mean", "sd")}

    def _pilot(self, env, c, reason):
        # Keep a feasible contact for the required final plan on small fixtures.
        n = min(PILOT_SIZE, int(c["n"]), max(0, int(env.remaining_contacts) - 1))
        if self._stop_exploration or env.pilots_left <= 0 or n < 10:
            return False
        try:
            res = env.run_pilot(target_tariff=c["target_tariff"], channel="push", n_customers=n,
                                filter_current_tariff=c["current_tariff"],
                                filter_arpu_segment=c["arpu_segment"])
        except (RuntimeError, ValueError) as exc:
            self.decision_trace["warnings"].append(f"pilot_failed: {exc}")
            return False
        observed, actual_n = float(res["observed_lift_ratio"]), int(res["n_customers"])
        if not math.isfinite(observed) or actual_n <= 0:
            self.decision_trace["warnings"].append("invalid_pilot_observation")
            return False
        key = self._key(c)
        e = self._evidence.setdefault(key, {**c, "sample_n": 0, "weighted_lift": 0., "repeats": 0})
        e["sample_n"] += actual_n
        e["weighted_lift"] += actual_n * observed
        e["repeats"] += 1
        est = self._estimate(e)
        self.decision_trace["pilots"].append({"current_tariff": c["current_tariff"],
            "arpu_segment": c["arpu_segment"], "target_tariff": c["target_tariff"],
            "n": actual_n, "observed_lift": observed, "posterior_mean": est["mean"],
            "posterior_sd": est["sd"], "reason": reason})
        pilots = self.decision_trace["pilots"]
        if self.adaptive and len(pilots) >= 6:
            total_n = sum(p["n"] for p in pilots)
            average = sum(p["n"] * p["observed_lift"] for p in pilots) / total_n
            negative_share = sum(p["observed_lift"] < 0 for p in pilots) / len(pilots)
            if negative_share >= .8 and average < -2 * PER_CUSTOMER_STD / math.sqrt(total_n):
                self._stop_exploration = True
                self.decision_trace["warnings"].append("stopped_exploration_after_widespread_negative_pilots")
        return True

    def _explore(self, env, candidates):
        first = [c for c in candidates if c["rank"] == 0]
        first_count = min(FIRST_PASS_CELLS if self.adaptive else 16, int(env.pilots_left))
        for c in first[:first_count]:
            if not self._pilot(env, c, "initial_coverage"):
                break
        # Calibrate historical strength using current-audience observations only.
        numerator = sum(e["prior"] * e["weighted_lift"] for e in self._evidence.values())
        denominator = sum(e["prior"] ** 2 * e["sample_n"] for e in self._evidence.values())
        self._history_scale = float(np.clip(numerator / denominator, 0., 1.)) if denominator > 0 else 0.
        self.decision_trace["history_scale"] = self._history_scale
        if not self.adaptive:
            for c in [c for c in candidates if c["rank"] == 1] + first[first_count:]:
                if not self._pilot(env, c, "fixed_second_pass"):
                    break
            return
        # Approximate value of information: uncertain, valuable decisions close
        # to the best alternative or to the no-contact boundary get priority.
        while not self._stop_exploration and env.pilots_left > 0 and env.remaining_contacts >= 10:
            ests = {key: self._estimate(e) for key, e in self._evidence.items()}
            options = []
            for c in candidates:
                key = self._key(c)
                e = ests.get(key)
                alternatives = [v["mean"] for k, v in ests.items() if k[:2] == key[:2] and k != key]
                best_other = max([0.] + alternatives)
                if e is None:
                    if not alternatives:
                        continue
                    mean, sd = self.history_weight * self._history_scale * c["prior"], PRIOR_SD
                    priority = max(0., mean + sd - best_other)
                    reason = "test_alternative" if alternatives else "expand_coverage"
                else:
                    if e["repeats"] >= 3:
                        continue
                    mean, sd = e["mean"], e["sd"]
                    uncertainty = math.exp(-0.5 * ((mean - best_other) / max(sd, 1e-9)) ** 2)
                    # Large, unexpectedly good pilot results can be selection
                    # noise. Confirm these before exposing a valuable audience.
                    surprise = min(1., max(0., (mean - self._history_scale * c["prior"]) / max(sd, 1e-9) - 1.))
                    uncertainty = max(uncertainty, surprise)
                    next_n = min(PILOT_SIZE, int(c["n"]))
                    next_sd = math.sqrt(1 / (1 / sd ** 2 + next_n / PER_CUSTOMER_STD ** 2))
                    priority = (sd - next_sd) * uncertainty
                    # Confirmation gate: a surprising, positive estimate below
                    # two standard errors must compete at its deployment value,
                    # not just at the small reduction in measurement variance.
                    if surprise > 0 and 0 < mean < 2 * sd:
                        priority = max(priority, mean)
                    reason = "confirm_surprising_winner" if surprise > 0 else "confirm_uncertain_choice"
                priority *= float(c["arpu"]) * min(int(c["n"]), int(env.remaining_contacts), 5000)
                priority /= min(PILOT_SIZE, int(c["n"]))
                options.append((priority, key, c, reason))
            if not options:
                break
            options.sort(key=lambda x: (-x[0], x[1]))
            if options[0][0] <= 0 or not self._pilot(env, options[0][2], options[0][3]):
                break

    def _offers(self, env, estimates):
        profile, offers, group_parts = self._profile, [], {}
        for e in estimates:
            conservative_lift = e["mean"] - self._risk_margin() * e["sd"]
            if conservative_lift <= 0:
                continue
            mask = ((profile["current_tariff"] == e["current_tariff"])
                    & (profile["arpu_segment"] == e["arpu_segment"]))
            indices = np.flatnonzero(mask.to_numpy())
            filters = {"filter_current_tariff": e["current_tariff"], "filter_arpu_segment": e["arpu_segment"]}
            self._add_offers(env, offers, indices, np.full(len(indices), conservative_lift), filters, e["target_tariff"])
            for field in ("data_segment", "call_segment"):
                if field not in profile:
                    continue
                for label in sorted(profile.loc[indices, field].dropna().unique()):
                    sub = indices[(profile.loc[indices, field] == label).to_numpy()]
                    if len(sub) >= 10 and len(sub) < len(indices):
                        self._add_offers(env, offers, sub, np.full(len(sub), conservative_lift),
                                         {**filters, f"filter_{field}": str(label)}, e["target_tariff"])
            group_parts.setdefault((e["arpu_segment"], e["target_tariff"]), []).append((indices, {**e, "mean": conservative_lift}))
        # Unions share one campaign slot while preserving per-cell estimates.
        for (segment, target), parts in group_parts.items():
            parts.sort(key=lambda p: (-p[1]["mean"] * p[1]["arpu"], p[1]["current_tariff"]))
            for count in range(2, len(parts) + 1):
                subset = parts[:count]
                indices = np.concatenate([p[0] for p in subset])
                lifts = np.concatenate([np.full(len(p[0]), p[1]["mean"]) for p in subset])
                order = np.argsort(indices, kind="stable")
                filters = {"filter_arpu_segment": str(segment), "filter_current_tariff": ";".join(
                    sorted(p[1]["current_tariff"] for p in subset))}
                self._add_offers(env, offers, indices[order], lifts[order], filters, target)
        return offers

    def _add_offers(self, env, offers, indices, lifts, filters, target):
        indices, lifts = indices[:5000], lifts[:5000]
        if not len(indices):
            return
        arpu = self._profile.loc[indices, "predicted_arpu"].to_numpy(dtype=float)
        push_mult = float(env.channels["push"]["conversion_multiplier"])
        for channel, spec in sorted(env.channels.items()):
            multiplier = float(spec["conversion_multiplier"])
            # Push alone cannot identify conversion. Use a conservative channel
            # ratio valid for conversion in [0,1], including call saturation.
            ratio = min(multiplier, 1.) / push_mult
            cost = float(spec["cost_per_contact"])
            gross = lifts * ratio * arpu
            offers.append({"filters": filters, "target_tariff": target, "channel": channel,
                "indices": indices, "gross_cumsum": np.cumsum(gross), "cost": cost})

    def _allocate(self, env, estimates):
        offers = self._offers(env, estimates)
        best = (0., [], [])
        # Deterministic resource-price search. Select using estimated feasible
        # net, never organizer outcomes. Two rankings trade slot value vs reach.
        for money_price in (0., 1., 4.):
            for density in (False, True):
                contacts, budget = int(env.remaining_contacts), max(float(env.remaining_budget), 0.)
                used = np.zeros(len(self._profile), dtype=bool)
                chosen, records, value = [], [], 0.
                for _ in range(MAX_CAMPAIGNS):
                    winner = None
                    for index, offer in enumerate(offers):
                        cost = offer["cost"]
                        n = min(len(offer["indices"]), contacts)
                        if cost > 0:
                            n = min(n, int(budget // cost))
                        if n <= 0 or used[offer["indices"][:n]].any():
                            continue
                        net = float(offer["gross_cumsum"][n - 1] - n * cost)
                        if net <= 0:
                            continue
                        utility = (net - money_price * cost * n) / (n if density else 1)
                        if utility <= 0:
                            continue
                        proposal = (utility, net, -index, n, offer)
                        if winner is None or proposal[:3] > winner[:3]:
                            winner = proposal
                    if winner is None:
                        break
                    _, net, _, n, offer = winner
                    used[offer["indices"][:n]] = True
                    contacts -= n
                    spent = n * offer["cost"]
                    budget -= spent
                    value += net
                    campaign = {"campaign_name": f"plan_{len(chosen) + 1}_{offer['channel']}_{offer['target_tariff']}",
                        **offer["filters"], "target_tariff": offer["target_tariff"], "channel": offer["channel"]}
                    chosen.append(campaign)
                    records.append({**campaign, "planned_contacts": n, "planned_cost": spent,
                        "estimated_net": net, "reason": "positive_incremental_net_no_final_overlap",
                        "capped_by_remaining_resources": n < len(offer["indices"])})
                if value > best[0]:
                    best = (value, chosen, records)
        self.decision_trace["campaigns"] = best[2]
        self.decision_trace["estimated_final_net_before_pilot_dedup"] = best[0]
        return best[1]

    def _fallback(self, env):
        """Keep pilot provenance. This limits exposure, not the possible loss."""
        if not self._evidence or env.remaining_contacts <= 0:
            self.decision_trace["warnings"].append("no_feasible_evidence_based_fallback")
            return []
        try:
            options = [self._estimate(e) for e in self._evidence.values()]
            e = max(options, key=lambda r: (r["mean"] - r["sd"], self._key(r)))
            filters = {"filter_current_tariff": e["current_tariff"], "filter_arpu_segment": e["arpu_segment"]}
            cell = self._profile[(self._profile["current_tariff"] == e["current_tariff"])
                                & (self._profile["arpu_segment"] == e["arpu_segment"])]
            extra = {}
            if e["mean"] <= self._risk_margin() * e["sd"] and {"data_segment", "call_segment"}.issubset(cell):
                sizes = cell.groupby(["data_segment", "call_segment"], observed=True).size()
                if len(sizes):
                    data, call = sizes.sort_values(kind="stable").index[0]
                    extra = {"filter_data_segment": str(data), "filter_call_segment": str(call)}
            self.decision_trace["warnings"].append("used_tested_audience_fallback_profit_not_guaranteed")
            return [{"campaign_name": "fallback_tested_audience", **filters, **extra,
                     "target_tariff": e["target_tariff"], "channel": "push"}]
        except Exception as exc:
            self.decision_trace["warnings"].append(f"fallback_error: {type(exc).__name__}")
            return []
