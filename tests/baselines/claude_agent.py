"""
Агент управления тарифными маркетинговыми кампаниями — трек 04, HackAlem AI.

Стратегия в одну строку: бесплатно разведать push-пилотами, сжать оценки к
априору по их погрешности и потратить деньги только там, где доплата за более
сильный канал окупается на дорогом абоненте.

Почему так, по пунктам.

1. РАЗВЕДКА БЕСПЛАТНА. Эффект кампании в среде считается как
       arpu_change_pct * clip(conversion_rate * множитель_канала, 1.0),
   то есть канал влияет только множителем. Значит push (множитель 0.50,
   стоимость контакта 0) меряет ту же величину, что и call (1.20, 160 у.е.),
   просто в другом масштабе. Разведка через push не тратит бюджет вообще —
   расходуется только лимит охвата, а контакты при этом приносят реальный
   прирост, если связка удачная.

2. ПИЛОТУ НЕЛЬЗЯ ВЕРИТЬ НАПРЯМУЮ. Наблюдение = истина + шум, где
   шум ~ N(0, 0.804/sqrt(n)). При n=200 это 0.057 при типичных эффектах
   0.2–0.45: убыточная связка легко покажется прибыльной. Поэтому наблюдение
   смешивается с априором из истории смен тарифов (байесовское сжатие), а в
   кампании идут только связки, у которых нижняя доверительная граница выше
   нуля. Именно на этом разоряется шаблонный агент: он верит пилоту как есть.

3. ДВА ДЕФИЦИТНЫХ РЕСУРСА, А НЕ ОДИН. Бюджет 100 000 у.е. и охват 15 000
   контактов расходуются независимо. push бесплатен, поэтому базовый план —
   накрыть им всё, что в плюсе, а деньги пустить на «апгрейд» канала там, где
   прибавка к эффекту на рубль максимальна. Абонент засчитывается один раз по
   лучшей для него кампании, поэтому каждый сегмент получает ровно один канал —
   иначе одни и те же люди съедают лимит охвата дважды.

Решение детерминировано: своей случайности у агента нет, вся случайность живёт
в среде и управляется её seed. Это требование воспроизводимости submission.csv.
LLM в контур принятия решений намеренно не заведён (см. README).
"""

import os

import numpy as np
import pandas as pd

# --- константы среды, задокументированные организаторами ---
PER_CUSTOMER_STD = 0.804       # разброс эффекта на одного абонента (environment.py)
MAX_CAMPAIGNS = 10
MAX_CUSTOMERS_PER_CAMPAIGN = 5000
ARPU_BINS = [-np.inf, 1000, 5000, np.inf]
ARPU_LABELS = ["LOW", "MID", "HIGH"]

# --- настройки стратегии ---
PRIOR_SD = 0.10                # априорный разброс истинного эффекта между связками
PILOT_SIZE = 200               # максимум на пилот: шум 0.804/sqrt(200) = 0.057
MIN_CELL = 150                 # сегменты мельче не пилотируем: кампания не окупит слот
PILOT_CHANNEL = "push"         # разведка бесплатным каналом
TARGETS_PER_CELL = 2           # сколько целевых тарифов проверяем на один сегмент
FIRST_PASS_CELLS = 16          # сегментов в первом проходе; остальные пилоты — на вторые гипотезы

# Запас прочности сверх сжатой оценки. Измерено на 20 прогонах: 0.0 даёт и
# лучшую медиану, и лучший худший случай, и наименьший разброс (4 475 754 /
# 3 949 462 / 228 569 против 4 350 344 / 3 489 222 / 330 281 при 0.5). Сжатие к
# априору уже гасит шум пилота, а дополнительная маржа выбрасывает прибыльные
# сегменты. Параметр оставлен: если на судействе эффекты окажутся ближе к нулю,
# поднять его — самый быстрый способ сделать агента осторожнее.
Z_SAFETY = 0.0


def build_prior(path="data/change_tariff.csv"):
    """
    Априорная оценка эффекта по истории смен тарифов.

    Для связки (откуда, ARPU-сегмент, куда) считаем среднее относительное
    изменение ARPU и долю переходов в этот тариф. История описывает ДРУГУЮ
    выборку абонентов, чем та, на которой считается результат, поэтому априор
    используется только для ранжирования кандидатов и как точка сжатия — но
    никогда как готовый ответ.
    """
    empty = pd.DataFrame(columns=["tariff_plan_code_from", "tariff_plan_code_to",
                                  "arpu_segment", "arpu_change_pct", "conversion_rate"])
    if not os.path.exists(path):
        return empty
    try:
        df = pd.read_csv(path)
    except Exception:
        return empty

    df = df[df["AVG_ARPU_PREV_3M"] >= 100].copy()
    if df.empty:
        return empty
    df["arpu_segment"] = pd.cut(df["AVG_ARPU_PREV_3M"], bins=ARPU_BINS, labels=ARPU_LABELS)
    df["arpu_change_pct"] = ((df["AVG_ARPU_NEXT_3M"] - df["AVG_ARPU_PREV_3M"])
                             / df["AVG_ARPU_PREV_3M"]).clip(-1, 3)

    grouped = (df.groupby(["tariff_plan_code_from", "tariff_plan_code_to", "arpu_segment"],
                          observed=True)
                 .agg(arpu_change_pct=("arpu_change_pct", "mean"), count=("ID_NUMBER", "size"))
                 .reset_index())
    totals = (grouped.groupby(["tariff_plan_code_from", "arpu_segment"], observed=True)["count"]
                     .sum().rename("total").reset_index())
    grouped = grouped.merge(totals, on=["tariff_plan_code_from", "arpu_segment"])
    grouped["conversion_rate"] = grouped["count"] / grouped["total"]
    return grouped.drop(columns=["total"])


class Agent:
    """Интерфейс задан организаторами: класс Agent с методом act(env)."""

    def act(self, env):
        try:
            return self._plan(env)
        except Exception:
            # Падать нельзя: проведённые пилоты уже пошли в зачёт, и пустой план
            # оставит их без компенсирующих кампаний.
            return self._fallback(env)

    # ------------------------------------------------------------------ план

    def _plan(self, env):
        prior = build_prior()
        candidates = self._candidates(env, prior)
        if candidates.empty:
            return []

        observations = self._explore(env, candidates)
        if observations.empty:
            return []

        plan = self._allocate(env, observations)
        if plan.empty:
            return []

        return self._assemble(plan)

    def _candidates(self, env, prior):
        """Ячейки аудитории (текущий тариф × ARPU-сегмент) и лучшая цель для каждой."""
        if prior.empty:
            return prior

        profile = env.customer_profile
        cells = (profile.groupby(["current_tariff", "arpu_segment"], observed=True)
                        .agg(n=("ID_NUMBER", "size"), arpu=("predicted_arpu", "mean"))
                        .reset_index())
        cells = cells[cells["n"] >= MIN_CELL]
        if cells.empty:
            return cells

        push_mult = env.channels[PILOT_CHANNEL]["conversion_multiplier"]
        cand = cells.merge(prior, left_on=["current_tariff", "arpu_segment"],
                           right_on=["tariff_plan_code_from", "arpu_segment"], how="inner")
        cand = cand[cand["tariff_plan_code_to"] != cand["current_tariff"]]
        if cand.empty:
            return cand

        cand["eff_push"] = np.minimum(cand["conversion_rate"] * push_mult, 1.0)
        cand["prior_ratio"] = cand["arpu_change_pct"] * cand["eff_push"]
        # чего стоит связка, если априор не врёт: эффект × ценность × размер
        cand["prior_value"] = (cand["prior_ratio"] * cand["arpu"]
                               * cand["n"].clip(upper=MAX_CUSTOMERS_PER_CAMPAIGN))
        cand = cand[cand["prior_ratio"] > 0]
        if cand.empty:
            return cand

        # Пилотов 20, крупных ячеек примерно столько же — но ценность ячеек
        # различается на порядок. Поэтому сначала по одной лучшей гипотезе на
        # каждую ячейку в порядке убывания ценности, а оставшиеся пилоты уходят
        # на вторую гипотезу для самых крупных ячеек: если лучшая по априору
        # цель окажется убыточной, у большой ячейки остаётся второй шанс.
        cand = cand.sort_values(["prior_value", "current_tariff", "tariff_plan_code_to"],
                                ascending=[False, True, True])
        cand["rank_in_cell"] = cand.groupby(["current_tariff", "arpu_segment"],
                                            observed=True).cumcount()
        cand = cand[cand["rank_in_cell"] < TARGETS_PER_CELL]

        budget_pilots = max(env.pilots_left, 0)
        first = cand[cand["rank_in_cell"] == 0].head(min(FIRST_PASS_CELLS, budget_pilots))
        second = cand[cand["rank_in_cell"] == 1].head(max(budget_pilots - len(first), 0))
        order = pd.concat([first, second], ignore_index=True)
        return order.head(budget_pilots)

    def _explore(self, env, candidates):
        """Пилотируем кандидатов бесплатным каналом и сжимаем оценки к априору."""
        rows = []
        for _, cand in candidates.iterrows():
            if env.pilots_left <= 0 or env.remaining_contacts < PILOT_SIZE:
                break
            try:
                res = env.run_pilot(target_tariff=cand["tariff_plan_code_to"],
                                    channel=PILOT_CHANNEL,
                                    n_customers=PILOT_SIZE,
                                    filter_arpu_segment=cand["arpu_segment"],
                                    filter_current_tariff=cand["current_tariff"])
            except (RuntimeError, ValueError):
                break

            n = max(int(res.get("n_customers", PILOT_SIZE)), 1)
            noise_var = (PER_CUSTOMER_STD ** 2) / n
            weight = PRIOR_SD ** 2 / (PRIOR_SD ** 2 + noise_var)
            posterior = weight * res["observed_lift_ratio"] + (1 - weight) * cand["prior_ratio"]
            posterior_sd = float(np.sqrt(weight * noise_var))

            rows.append({
                "current_tariff": cand["current_tariff"],
                "arpu_segment": cand["arpu_segment"],
                "target_tariff": cand["tariff_plan_code_to"],
                "conversion_rate": cand["conversion_rate"],
                "arpu": cand["arpu"],
                "n": int(cand["n"]),
                "posterior": posterior,
                "lcb": posterior - Z_SAFETY * posterior_sd,
            })

        obs = pd.DataFrame(rows)
        return obs[obs["lcb"] > 0] if not obs.empty else obs

    def _allocate(self, env, obs):
        """
        Выбор канала для каждого сегмента при двух ограничениях.

        Сначала все сегменты получают push (бесплатно). Затем бюджет тратится
        жадно: на каждом шаге апгрейдится тот сегмент, где прибавка к эффекту на
        один потраченный рубль максимальна. Канал у сегмента ровно один, чтобы
        одни и те же абоненты не расходовали лимит охвата дважды.
        """
        channels = env.channels
        push_mult = channels[PILOT_CHANNEL]["conversion_multiplier"]

        rows = []
        for _, o in obs.iterrows():
            eff_push = min(o["conversion_rate"] * push_mult, 1.0)
            if eff_push <= 0:
                continue
            # снимаем множитель канала и получаем «сырой» процент изменения ARPU
            raw_pct = o["lcb"] / eff_push
            push_value = raw_pct * eff_push * o["arpu"]      # ценность контакта через push
            if push_value <= 0:
                continue

            reach = int(min(o["n"], MAX_CUSTOMERS_PER_CAMPAIGN))
            options = []
            for name, spec in channels.items():
                eff = min(o["conversion_rate"] * spec["conversion_multiplier"], 1.0)
                value = raw_pct * eff * o["arpu"] - spec["cost_per_contact"]
                options.append((name, value, spec["cost_per_contact"]))

            rows.append({
                "current_tariff": o["current_tariff"],
                "arpu_segment": o["arpu_segment"],
                "target_tariff": o["target_tariff"],
                "reach": reach,
                "push_value": push_value,
                "channel": PILOT_CHANNEL,
                "value": push_value,
                "_options": options,
            })

        if not rows:
            return pd.DataFrame()

        budget = float(getattr(env, "remaining_budget", 0.0))
        # Жадный апгрейд по отдаче на рубль. Кампанию, которая дороже остатка
        # бюджета, всё равно берём: скоринг обрежет её по деньгам сам, а отдача
        # на контакт от обрезки не меняется. Просто перестаём апгрейдить дальше.
        upgrades = []
        for idx, r in enumerate(rows):
            for name, value, cost in r["_options"]:
                if cost <= 0 or value <= r["push_value"]:
                    continue
                gain_per_money = (value - r["push_value"]) / cost
                upgrades.append((gain_per_money, idx, name, value, cost * r["reach"]))
        upgrades.sort(key=lambda u: (-u[0], u[1], u[2]))

        upgraded = set()
        for gain_per_money, idx, name, value, total_cost in upgrades:
            if budget <= 0:
                break
            if idx in upgraded:
                continue
            rows[idx]["channel"] = name
            rows[idx]["value"] = value
            budget -= min(total_cost, budget)
            upgraded.add(idx)

        plan = pd.DataFrame([{k: v for k, v in r.items() if k != "_options"} for r in rows])
        return plan.sort_values(["value", "current_tariff"], ascending=[False, True])

    def _assemble(self, plan):
        """
        Сборка кампаний. Сегменты с одинаковыми (ARPU-сегмент, цель, канал)
        объединяются в одну кампанию через список текущих тарифов — слотов всего
        десять, и тратить их по одному на сегмент расточительно. Платные
        кампании идут первыми: скоринг расходует бюджет и охват по порядку.
        """
        campaigns = []
        for (segment, target, channel), grp in plan.groupby(
                ["arpu_segment", "target_tariff", "channel"], sort=False):
            campaigns.append({
                "campaign_name": f"{channel}_{segment}_{target}",
                "filter_arpu_segment": segment,
                "filter_current_tariff": ";".join(sorted(grp["current_tariff"].unique())),
                "target_tariff": target,
                "channel": channel,
                "_value": float(grp["value"].max()),
                "_paid": channel != PILOT_CHANNEL,
            })

        campaigns.sort(key=lambda c: (not c["_paid"], -c["_value"]))
        for c in campaigns:
            c.pop("_value")
            c.pop("_paid")
        return campaigns[:MAX_CAMPAIGNS]

    # -------------------------------------------------------------- страховка

    @staticmethod
    def _fallback(env):
        """
        Если основная логика по какой-то причине упала — вернуть безопасный
        минимум: один бесплатный канал на самый крупный сегмент. Хуже нуля это
        сделать не может только при положительном эффекте, поэтому кампания
        возвращается лишь при наличии хотя бы одного удачного пилота.
        """
        try:
            history = [p for p in getattr(env, "pilot_history", [])
                       if p.get("observed_lift_ratio", 0) > 0]
            if not history:
                return []
            best = max(history, key=lambda p: p["observed_lift_ratio"])
            return [{
                "campaign_name": "fallback",
                "target_tariff": best["target_tariff"],
                "channel": PILOT_CHANNEL,
            }]
        except Exception:
            return []
