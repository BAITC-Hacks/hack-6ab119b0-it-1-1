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
FIRST_PASS_CELLS = 16
MAX_HISTORY_CHALLENGES = 2
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
        self._history_conflict = False
        self._transfer_slope = 1.0

    def act(self, env):
        self._evidence = {}
        self._history_scale = 1.0
        self._stop_exploration = False
        self._history_conflict = False
        self._transfer_slope = 1.0
        self.decision_trace = {"policy": "adaptive-size/online-history/contact-aware-allocation",
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
            contrary = sorted(options, key=lambda v: (v[0], v[1]))[:2]
            if not options:
                options = [(0.0, t) for t in known if t != cell["current_tariff"]]
            elif any(signal > 0 for signal, _ in options):
                options = [(signal, target) for signal, target in options if signal > 0]
            options.sort(key=lambda v: (-v[0], v[1]))
            selected = [(rank, signal, target) for rank, (signal, target) in enumerate(options[:2])]
            selected_targets = {target for _, _, target in selected}
            selected.extend((2, signal, target) for signal, target in contrary if target not in selected_targets)
            for rank, signal, target in selected:
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

    def _pilot_size(self, candidate):
        """Choose exposure from observations; pilot profit also enters the score."""
        if not self.adaptive:
            return PILOT_SIZE, "fixed_size_ablation"
        evidence = self._evidence.get(self._key(candidate))
        if evidence is not None:
            count = evidence["sample_n"]
            mean = evidence["weighted_lift"] / count
            se = PER_CUSTOMER_STD / math.sqrt(count)
            if mean - se > 0:
                return PILOT_SIZE, "positive_pilot_has_direct_value"
            if mean + se < 0:
                return 50, "limit_negative_exposure"
            alternatives = [e["weighted_lift"] / e["sample_n"]
                for key, e in self._evidence.items()
                if key[:2] == self._key(candidate)[:2] and key != self._key(candidate)]
            gap = abs(mean - max([0.] + alternatives))
            # One noise SE of separation is a precision target, not a guarantee.
            if gap <= PER_CUSTOMER_STD / math.sqrt(count + PILOT_SIZE):
                return PILOT_SIZE, "resolve_uncertain_decision"
            required = math.ceil((PER_CUSTOMER_STD / gap) ** 2)
            additional = 25 * math.ceil(max(0, required - count) / 25)
            return min(PILOT_SIZE, max(50, additional)), "resolve_uncertain_decision"
        if self._history_conflict:
            return 50, "small_challenge_after_history_conflict"
        pilots = self.decision_trace["pilots"]
        if len(pilots) >= 3:
            count = sum(p["n"] for p in pilots)
            mean = sum(p["n"] * p["observed_lift"] for p in pilots) / count
            negative_share = sum(p["n"] for p in pilots if p["observed_lift"] < 0) / count
            if negative_share >= .8 and mean + 2 * PER_CUSTOMER_STD / math.sqrt(count) < 0:
                return 50, "smaller_screen_after_negative_evidence"
        return PILOT_SIZE, "initial_or_mixed_evidence"

    def _calibrate_history(self):
        evidence = list(self._evidence.values())
        numerator = sum(e["prior"] * e["weighted_lift"] for e in evidence)
        denominator = sum(e["prior"] ** 2 * e["sample_n"] for e in evidence)
        slope = numerator / denominator if denominator > 0 else 0.
        noise_se = PER_CUSTOMER_STD / math.sqrt(denominator) if denominator > 0 else math.inf
        self._transfer_slope = float(np.clip(slope, -1., 1.))
        self._history_scale = max(0., self._transfer_slope)
        # A through-origin fit diagnoses failed transfer, not negative correlation.
        # Its noise margin ignores effect heterogeneity: this remains a heuristic.
        cells = {(e["current_tariff"], e["arpu_segment"]) for e in evidence}
        self._history_conflict = len(cells) >= 3 and slope + 3 * noise_se < 0
        self.decision_trace.update(history_scale=self._history_scale,
            transfer_slope=self._transfer_slope, history_conflict=self._history_conflict)

    def _pilot(self, env, c, reason):
        # Keep a feasible contact for the required final plan on small fixtures.
        requested_n, size_reason = self._pilot_size(c)
        n = min(requested_n, int(c["n"]), max(0, int(env.remaining_contacts) - 1))
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
        self._calibrate_history()
        est = self._estimate(e)
        self.decision_trace["pilots"].append({"current_tariff": c["current_tariff"],
            "arpu_segment": c["arpu_segment"], "target_tariff": c["target_tariff"],
            "n": actual_n, "observed_lift": observed, "posterior_mean": est["mean"],
            "posterior_sd": est["sd"], "reason": reason,
            "requested_n": requested_n, "sample_size_reason": size_reason,
            "history_scale": self._history_scale, "history_conflict": self._history_conflict})
        pilots = self.decision_trace["pilots"]
        if self.adaptive and len(pilots) >= 6:
            total_n = sum(p["n"] for p in pilots)
            average = sum(p["n"] * p["observed_lift"] for p in pilots) / total_n
            negative_share = sum(p["n"] for p in pilots if p["observed_lift"] < 0) / total_n
            if negative_share >= .8 and average < -2 * PER_CUSTOMER_STD / math.sqrt(total_n):
                self._stop_exploration = True
                warning = ("bounded_history_challenges_after_negative_pilots" if self._history_conflict
                           else "stopped_exploration_after_widespread_negative_pilots")
                if warning not in self.decision_trace["warnings"]:
                    self.decision_trace["warnings"].append(warning)
        # The exploration loop permits only a bounded set of contrary probes
        # without a pilot-supported profitable alternative.
        if self.adaptive and self._history_conflict:
            self._stop_exploration = False
        return True

    def _explore(self, env, candidates):
        first = [c for c in candidates if c["rank"] == 0]
        first_count = min(FIRST_PASS_CELLS if self.adaptive else 16, int(env.pilots_left))
        for c in first[:first_count]:
            if not self._pilot(env, c, "initial_coverage"):
                break
            if self.adaptive and self._history_conflict:
                break
        # Calibrate historical strength using current-audience observations only.
        self._calibrate_history()
        if not self.adaptive:
            for c in [c for c in candidates if c["rank"] == 1] + first[first_count:]:
                if not self._pilot(env, c, "fixed_second_pass"):
                    break
            return
        # Approximate value of information: uncertain, valuable decisions close
        # to the best alternative or to the no-contact boundary get priority.
        while not self._stop_exploration and env.pilots_left > 0 and env.remaining_contacts >= 10:
            ests = {key: self._estimate(e) for key, e in self._evidence.items()}
            challenges = sum(p["reason"] == "challenge_history" for p in self.decision_trace["pilots"])
            supported = any(e["repeats"] >= 2 and e["mean"] > self._risk_margin() * e["sd"]
                            for e in ests.values())
            options = []
            for c in candidates:
                key = self._key(c)
                e = ests.get(key)
                alternatives = [v["mean"] for k, v in ests.items() if k[:2] == key[:2] and k != key]
                best_other = max([0.] + alternatives)
                next_n = min(self._pilot_size(c)[0], int(c["n"]), max(0, int(env.remaining_contacts) - 1))
                if next_n < 10:
                    continue
                if e is None:
                    if self._history_conflict:
                        if challenges >= MAX_HISTORY_CHALLENGES and not supported:
                            continue
                        # Reverse order only proposes an experiment. The final
                        # estimate never uses an inverted historical prior.
                        mean, sd = self._transfer_slope * c["prior"], PRIOR_SD
                    elif c["rank"] < 2 and alternatives:
                        mean, sd = self.history_weight * self._history_scale * c["prior"], PRIOR_SD
                    else:
                        continue
                    priority = max(0., mean + sd - best_other)
                    reason = "challenge_history" if self._history_conflict else "test_alternative"
                else:
                    if e["repeats"] >= 3:
                        continue
                    mean, sd = e["mean"], e["sd"]
                    if self._history_conflict and challenges >= MAX_HISTORY_CHALLENGES and not supported and mean <= 0:
                        continue
                    uncertainty = math.exp(-0.5 * ((mean - best_other) / max(sd, 1e-9)) ** 2)
                    # Large, unexpectedly good pilot results can be selection
                    # noise. Confirm these before exposing a valuable audience.
                    surprise = min(1., max(0., (mean - self._history_scale * c["prior"]) / max(sd, 1e-9) - 1.))
                    uncertainty = max(uncertainty, surprise)
                    next_sd = math.sqrt(1 / (1 / sd ** 2 + next_n / PER_CUSTOMER_STD ** 2))
                    priority = (sd - next_sd) * uncertainty
                    # Confirmation gate: a surprising, positive estimate below
                    # two standard errors must compete at its deployment value,
                    # not just at the small reduction in measurement variance.
                    if surprise > 0 and 0 < mean < 2 * sd:
                        priority = max(priority, mean)
                    reason = "confirm_surprising_winner" if surprise > 0 else "confirm_uncertain_choice"
                priority *= float(c["arpu"]) * min(int(c["n"]), int(env.remaining_contacts), 5000)
                # A small pilot still consumes one of only 20 experiment slots.
                # Price both resources instead of rewarding tiny noisy repeats.
                slot_contacts = env.remaining_contacts / max(env.pilots_left, 1)
                priority /= next_n + slot_contacts
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
