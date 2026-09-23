"""Adaptive pilots with channel-specific estimates and explicit resource accounting.

Historical changes rank experiments only. Estimates use the documented standard
deviation of pilot noise, not variance estimated from a different population.
"""

import math
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

NOISE_STD = 0.804
VERSION = "adaptive-channel-v1"
FILTERS = {
    "arpu_segment": "filter_arpu_segment",
    "current_tariff": "filter_current_tariff",
    "data_segment": "filter_data_segment",
    "call_segment": "filter_call_segment",
}


def history_ranks(warnings, history_path=None):
    path = (
        Path(history_path)
        if history_path is not None
        else Path(__file__).resolve().parent / "data" / "change_tariff.csv"
    )
    try:
        data = pd.read_csv(path)
        before = pd.to_numeric(data["AVG_ARPU_PREV_3M"], errors="coerce")
        after = pd.to_numeric(data["AVG_ARPU_NEXT_3M"], errors="coerce")
        data = data.loc[(before > 0) & before.notna() & after.notna()].copy()
        data["ratio"] = (after / before - 1).loc[data.index]
        data = data.loc[data["ratio"].map(math.isfinite)]
        data["segment"] = before.loc[data.index].map(
            lambda x: "LOW" if x < 1000 else ("MID" if x <= 5000 else "HIGH")
        )
        groups = data.groupby(["tariff_plan_code_from", "segment", "tariff_plan_code_to"])
        return {tuple(str(x) for x in key): float(group["ratio"].median()) for key, group in groups}
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append("Historical data unavailable or invalid; using diverse tariff exploration.")
        return {}


def make_cells(profile):
    """Partition with supported filters; never invent an arbitrary size argument."""
    cells = []

    def split(frame, filters, remaining):
        if len(frame) <= 5000:
            if len(frame):
                cells.append(
                    {
                        "filters": filters,
                        "frame": frame.sort_values("ID_NUMBER"),
                        "id": "|".join(f"{k}={v}" for k, v in sorted(filters.items())),
                    }
                )
            return
        if not remaining:
            return
        column, *rest = remaining
        if column not in frame.columns:
            split(frame, filters, rest)
            return
        for key, group in frame.groupby(column, observed=True, sort=True):
            split(group, {**filters, FILTERS[column]: str(key)}, rest)

    for (tariff, segment), group in profile.groupby(
        ["current_tariff", "arpu_segment"], observed=True, sort=True
    ):
        split(
            group,
            {"filter_current_tariff": str(tariff), "filter_arpu_segment": str(segment)},
            ["data_segment", "call_segment"],
        )
    return cells


def run_policy(env, history_path=None):
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat()
    warnings = [
        "Projected campaign gain excludes unknown pilot/final overlap; use official evaluation for actual net."
    ]
    initial_budget = float(env.remaining_budget)
    initial_contacts = int(env.remaining_contacts)
    initial_pilots = int(env.pilots_left)
    ranks = history_ranks(warnings, history_path)
    cells = make_cells(env.customer_profile)
    tariffs = sorted(str(t) for t in env.tariffs["tariff_plan_code"].unique())
    channels = env.channels
    cheapest = min(channels, key=lambda c: (channels[c]["cost_per_contact"], c))
    screen_channel = "sms" if "sms" in channels and initial_budget >= 400 else cheapest
    candidates = []
    by_id = {}
    pilot_log = []

    def candidate(cell, target, channel):
        cid = f"{cell['id']}|to={target}|via={channel}"
        if cid in by_id:
            return by_id[cid]
        frame = cell["frame"]
        row = {
            "id": cid,
            "cell": cell,
            "filters": cell["filters"],
            "target_tariff": target,
            "channel": channel,
            "audience_count": len(frame),
            "audience_value": float(frame["predicted_arpu"].sum()),
            "prior": ranks.get(
                (cell["filters"]["filter_current_tariff"], cell["filters"]["filter_arpu_segment"], target),
                0.0,
            ),
            "evidence_count": 0,
            "estimate": None,
            "standard_error": None,
            "lower_bound": None,
            "selected": False,
            "weighted_sum": 0.0,
        }
        candidates.append(row)
        by_id[cid] = row
        return row

    # Keep one representable final audience affordable even if every signal is negative.
    reserve_cell = min(cells, key=lambda c: (len(c["frame"]), c["id"])) if cells else None
    reserve_contacts = len(reserve_cell["frame"]) if reserve_cell else 0
    reserve_cost = reserve_contacts * float(channels[cheapest]["cost_per_contact"])

    def pilot(row, requested, reason):
        if time.monotonic() - started > 230 or env.pilots_left <= 0:
            return False
        cost = float(channels[row["channel"]]["cost_per_contact"])
        available = int(env.remaining_contacts) - reserve_contacts
        if cost > 0:
            available = min(available, int(max(0, env.remaining_budget - reserve_cost) // cost))
        n = min(requested, 200, row["audience_count"], available)
        if n < 10:
            return False
        before = row["estimate"]
        try:
            result = env.run_pilot(
                target_tariff=row["target_tariff"], channel=row["channel"], n_customers=n, **row["filters"]
            )
        except (RuntimeError, ValueError) as error:
            warnings.append(f"Pilot stopped: {error}")
            return False
        actual = int(result["n_customers"])
        observation = float(result["observed_lift_ratio"])
        if actual <= 0 or not math.isfinite(observation):
            warnings.append("Pilot returned unusable evidence; resource expenditure remains accounted.")
            return False
        row["weighted_sum"] += observation * actual
        row["evidence_count"] += actual
        row["estimate"] = row["weighted_sum"] / row["evidence_count"]
        row["standard_error"] = NOISE_STD / math.sqrt(row["evidence_count"])
        row["lower_bound"] = row["estimate"] - row["standard_error"]
        pilot_log.append(
            {
                "id": f"pilot-{len(pilot_log) + 1}",
                "candidate_id": row["id"],
                "channel": row["channel"],
                "requested_n": n,
                "n_customers": actual,
                "cost": float(result["cost"]),
                "observed_lift_ratio": observation,
                "estimate_before": before,
                "estimate_after": row["estimate"],
                "standard_error": row["standard_error"],
                "reason": reason,
            }
        )
        return True

    ordered_cells = sorted(cells, key=lambda c: (-float(c["frame"]["predicted_arpu"].sum()), c["id"]))
    shortlist = []
    for cell in ordered_cells:
        current = cell["filters"]["filter_current_tariff"]
        segment = cell["filters"]["filter_arpu_segment"]
        targets = sorted(
            (t for t in tariffs if t != current), key=lambda t: (-ranks.get((current, segment, t), 0.0), t)
        )
        if targets:
            shortlist.append([candidate(cell, t, screen_channel) for t in targets[:2]])
    # First cover valuable distinct cells, then a second hypothesis in the best cells.
    screening = [rows[0] for rows in shortlist[:6]]
    screening += [rows[1] for rows in shortlist[:4] if len(rows) > 1]
    for row in screening:
        pilot(row, 80, "Screen a historically ranked hypothesis in a distinct audience.")

    observed = [r for r in candidates if r["evidence_count"]]
    promising = sorted(observed, key=lambda r: (-r["estimate"] * r["audience_value"], r["id"]))
    # Test alternative channels directly: clipped conversion invalidates naive rescaling.
    for row in promising[:3]:
        if row["estimate"] <= 0:
            continue
        alternate = "digital_ads" if "digital_ads" in channels else cheapest
        if alternate != row["channel"]:
            pilot(
                candidate(row["cell"], row["target_tariff"], alternate),
                100,
                "Measure a channel alternative directly; no multiplier extrapolation.",
            )

    while env.pilots_left > 0 and time.monotonic() - started < 230:
        observed = [r for r in candidates if r["evidence_count"]]
        if not observed:
            break
        eligible = []
        for row in observed:
            upper_net = (row["estimate"] + row["standard_error"]) * row["audience_value"]
            upper_net -= row["audience_count"] * channels[row["channel"]]["cost_per_contact"]
            if upper_net > 0 and row["evidence_count"] < 600:
                uncertainty = row["standard_error"] * row["audience_value"]
                eligible.append((uncertainty, row))
        if not eligible:
            break
        eligible.sort(key=lambda item: (-item[0], item[1]["id"]))
        if not any(
            pilot(row, 200, "Confirm an uncertain candidate with meaningful portfolio value.")
            for _, row in eligible
        ):
            break

    budget, contacts = float(env.remaining_budget), int(env.remaining_contacts)
    selected, final_log, used_cells = [], [], set()

    def add(row, rationale):
        nonlocal budget, contacts
        count = row["audience_count"]
        cost = count * float(channels[row["channel"]]["cost_per_contact"])
        if count <= 0 or count > 5000 or count > contacts or cost > budget or len(selected) >= 10:
            return False
        if row["cell"]["id"] in used_cells:
            return False
        campaign = {
            "campaign_name": f"plan_{len(selected) + 1}",
            **row["filters"],
            "target_tariff": row["target_tariff"],
            "channel": row["channel"],
        }
        selected.append(campaign)
        used_cells.add(row["cell"]["id"])
        row["selected"] = True
        budget -= cost
        contacts -= count
        estimate = row["estimate"]
        final_log.append(
            {
                "candidate_id": row["id"],
                "campaign": campaign,
                "audience_count": count,
                "audience_value": row["audience_value"],
                "projected_cost": cost,
                "projected_net": estimate * row["audience_value"] - cost if estimate is not None else None,
                "estimate": estimate,
                "standard_error": row["standard_error"],
                "rationale": rationale,
            }
        )
        return True

    def conservative_net(row):
        return (
            row["lower_bound"] * row["audience_value"]
            - row["audience_count"] * channels[row["channel"]]["cost_per_contact"]
        )

    observed = [r for r in candidates if r["evidence_count"]]
    for row in sorted(observed, key=lambda r: (-conservative_net(r), r["id"])):
        if conservative_net(row) > 0:
            add(row, "Positive net estimate after a one-standard-error uncertainty discount.")
    if not selected:
        warnings.append("No confidently profitable feasible plan; using a minimum-exposure legal fallback.")
        for row in sorted(observed, key=lambda r: (r["audience_count"], -conservative_net(r), r["id"])):
            if add(row, "Smallest feasible observed audience; profitability is not established."):
                break
    if not selected and reserve_cell and tariffs:
        current = reserve_cell["filters"]["filter_current_tariff"]
        target = next((t for t in tariffs if t != current), tariffs[0])
        row = candidate(reserve_cell, target, cheapest)
        pilot(row, 10, "Obtain evidence for the low-exposure fallback.")
        budget, contacts = float(env.remaining_budget), int(env.remaining_contacts)
        add(row, "Smallest representable audience on the cheapest channel; effect may be negative.")
    if not selected:
        warnings.append("No nonempty campaign is representable within the exposed remaining resources.")

    final_cost = sum(r["projected_cost"] for r in final_log)
    final_contacts = sum(r["audience_count"] for r in final_log)
    pilot_cost = initial_budget - float(env.remaining_budget)
    pilot_contacts = initial_contacts - int(env.remaining_contacts)
    trace = {
        "schema_version": 1,
        "run_id": timestamp,
        "policy_version": VERSION,
        "seed": None,
        "environment": "mock-unverified",
        "mode": "deterministic",
        "started_at": timestamp,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "limits": {
            "budget": initial_budget,
            "contacts": initial_contacts,
            "pilots": initial_pilots,
            "max_campaigns": 10,
            "max_customers_per_campaign": 5000,
        },
        "resources": {
            "initial_budget": initial_budget,
            "initial_contacts": initial_contacts,
            "remaining_budget": budget,
            "remaining_contacts": contacts,
            "pilots_used": initial_pilots - int(env.pilots_left),
            "pilot_cost": pilot_cost,
            "pilot_contacts": pilot_contacts,
            "final_cost": final_cost,
            "final_contacts": final_contacts,
            "total_cost": pilot_cost + final_cost,
            "total_contacts": pilot_contacts + final_contacts,
            "projected_net": sum(r["projected_net"] for r in final_log if r["projected_net"] is not None),
        },
        "candidates": [{k: v for k, v in r.items() if k not in {"cell", "weighted_sum"}} for r in candidates],
        "pilots": pilot_log,
        "campaigns": final_log,
        "warnings": warnings,
        "evaluation": None,
        "analysis": None,
    }
    return selected, trace


class Agent:
    def __init__(self, history_path=None):
        self.history_path = history_path
        self.last_run = None

    def act(self, env):
        campaigns, self.last_run = run_policy(env, history_path=self.history_path)
        return campaigns
