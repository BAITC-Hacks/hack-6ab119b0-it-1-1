"""LLM in the decision loop: ranks which candidate cells get first-pass pilots.

Safety contract (case section 9): key only from os.environ, every call wrapped
in try/except, bounded timeout, and any failure falls back to the deterministic
order - a model outage can never invalidate the plan. A committed JSON cache
keyed by the exact candidate payload (model-independent) makes the seed-42
submission replay reproducible without network access.
"""
from pathlib import Path
import hashlib
import json
import os
import time

CACHE_PATH = Path(__file__).resolve().parent / "llm_cache.json"
TIMEOUT_S = 20
TOTAL_BUDGET_S = 45  # hard wall-clock ceiling across all attempts
PROMPT = (
    "You allocate the next pilot experiments for a telecom tariff-change campaign under a "
    "20-pilot budget. Input JSON: candidate cells {id, customers, avg_arpu, history_signal, "
    "evidence?: {mean, sd, n}} (evidence comes from pilots already run on THIS audience; "
    "history_signal is a weak prior from a different population) and resource state. "
    "Choose up to k cells where one more pilot is most likely to change the final plan: "
    "large audiences whose estimate is uncertain and near a decision boundary, or valuable "
    "untested cells the current evidence cannot rule in or out. Reply with ONLY JSON: "
    '{"priority": [id, ...], "rationale": "<=40 words"}.'
)


def _payload(candidates, k, state=None):
    cells = []
    for c in candidates:
        cell = {"id": c["id"], "customers": int(c["n"]), "avg_arpu": round(float(c["arpu"]), 2),
                "history_signal": round(float(c["prior"]), 5)}
        if c.get("evidence"):
            cell["evidence"] = c["evidence"]
        cells.append(cell)
    return {"v": 2, "k": k, "state": state or {}, "cells": cells}


def _validate(raw, ids):
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("priority"), list):
        raise ValueError("response must be a JSON object with a priority list")
    order, seen = [], set()
    for i in data["priority"][:20]:
        if isinstance(i, str) and i in ids and i not in seen:
            seen.add(i)
            order.append(i)
    if not order:
        raise ValueError("empty or invalid priority list")
    return {"priority": order, "rationale": str(data.get("rationale", ""))[:400]}


def _call_model(payload):
    from openai import OpenAI

    deadline = time.monotonic() + TOTAL_BUDGET_S
    models = list(dict.fromkeys(
        m for m in (os.environ.get("OPENAI_MODEL"), "gpt-5.4-mini", "gpt-4.1-mini") if m))
    last = None
    for model in models[:2]:
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            break
        # key from OPENAI_API_KEY env only; no SDK retries - the model list is the retry
        client = OpenAI(timeout=min(TIMEOUT_S, remaining), max_retries=0)
        try:
            resp = client.responses.create(model=model, instructions=PROMPT,
                                           input=json.dumps(payload, sort_keys=True))
            text = (resp.output_text or "").strip()
            if text.startswith("```"):
                text = text.strip("`\n")
                text = text[text.find("{"):text.rfind("}") + 1]
            return text
        except Exception as exc:  # model missing, auth, network - try next then give up
            last = exc
    raise last if last else RuntimeError("no model configured")


def advise_pilot_order(candidates, k, state=None):
    """Returns {"order": [id,...]|None, "mode": str, "rationale": str}. Never raises."""
    try:
        cells = [{**c, "id": f'{c["current_tariff"]}|{c["arpu_segment"]}|{c["target_tariff"]}'}
                 for c in candidates]
        payload = _payload(cells, int(k), state)
        # Prompt hash in the key: editing the prompt invalidates old cached advice.
        key = hashlib.sha256((hashlib.sha256(PROMPT.encode()).hexdigest()[:12]
                              + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
        cache = {}
        try:
            cache = json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
        ids = {c["id"] for c in cells}
        if key in cache:
            v = _validate(json.dumps(cache[key]), ids)
            return {"order": v["priority"], "mode": "llm_cache", "rationale": v["rationale"]}
        if not os.environ.get("OPENAI_API_KEY"):
            return {"order": None, "mode": "fallback_no_key", "rationale": ""}
        v = _validate(_call_model(payload), ids)
        try:
            cache[key] = v
            CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))
        except Exception:
            pass  # read-only judging dir must not break the run
        return {"order": v["priority"], "mode": "llm_live", "rationale": v["rationale"]}
    except Exception as exc:
        return {"order": None, "mode": f"fallback_error:{type(exc).__name__}", "rationale": ""}
