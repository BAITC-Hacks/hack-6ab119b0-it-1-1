"""Export a public-evidence decision log; no LLM or access to effect truth."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import Agent
from mock_environment import make_mock_env

REASONS = {"initial_coverage": "Первичная проверка гипотезы",
           "test_alternative": "Проверка другого целевого тарифа",
           "confirm_uncertain_choice": "Уточнение неуверенного решения",
           "confirm_surprising_winner": "Перепроверка неожиданно хорошего результата"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    env, _ = make_mock_env(seed=args.seed)
    planner = Agent()
    campaigns = planner.act(env)
    trace = planner.decision_trace
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "decision_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Почему агент выбрал эти кампании", "",
        f"Локальная мок-среда, seed {args.seed}. Пилотов: {len(trace['pilots'])}; финальных кампаний: {len(campaigns)}.", "",
        "Этот отчёт содержит доступные агенту наблюдения и расчётные оценки. Он не читает истинные эффекты.",
        "Прогнозы не равны результатам скоринга. Пересечения с пилотами не вычтены из прогноза финального прироста: состав пилотных выборок агенту не раскрывается.", "",
        f"Коэффициент доверия к историческому сигналу после первой серии пилотов: {trace.get('history_scale', 0):.3f}.", "",
        "## Эксперименты", "",
        "| № | Аудитория | Цель | Человек | Наблюдаемый эффект | Зачем |",
        "| --- | --- | --- | ---: | ---: | --- |"]
    for i, p in enumerate(trace["pilots"], 1):
        lines.append(f"| {i} | {p['current_tariff']} / {p['arpu_segment']} | {p['target_tariff']} | {p['n']} | {p['observed_lift']:+.2%} | {REASONS.get(p['reason'], p['reason'])} |")
    lines += ["", "## Оценки после всех пилотов", "",
        "Погрешность — приближённое стандартное отклонение оценки; это не гарантия результата или откалиброванный доверительный интервал.", "",
        "| Аудитория | Цель | Пилотов | Наблюдений всего | Оценка эффекта push | Погрешность |",
        "| --- | --- | ---: | ---: | ---: | ---: |"]
    for e in trace["estimates"]:
        lines.append(f"| {e['current_tariff']} / {e['arpu_segment']} | {e['target_tariff']} | {e['repeats']} | {e['sample_n']} | {e['mean']:+.2%} | {e['sd']:.2%} |")
    lines += ["", "## Финальный план", "",
        "Кампании выбираются совместно с каналами: учитываются стоимость, оставшийся охват, 10 слотов и точный порядок ID. Повторные контакты между финальными кампаниями запрещены планировщиком.", "",
        "| № | Текущие тарифы / сегмент | Цель | Канал | Контакты | Затраты | Расчётный net* |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |"]
    for i, c in enumerate(trace["campaigns"], 1):
        audience = f"{c['filter_current_tariff']} / {c['filter_arpu_segment']}"
        for key in ("filter_data_segment", "filter_call_segment"):
            if key in c:
                audience += f" / {key}={c[key]}"
        lines.append(f"| {i} | {audience} | {c['target_tariff']} | {c['channel']} | {c['planned_contacts']} | {c['planned_cost']:,.0f} | {c['estimated_net']:,.0f} |")
    lines += ["", "*Оценка с запасом на неопределённость; без вычитания пересечений с пилотами. Для звонков используется консервативный пересчёт, поскольку конверсия по одному push-пилоту отдельно не определяется.", "",
        "## Отклонённые оценки", ""]
    for e in trace["rejected"]:
        lines.append(f"- {e['current_tariff']} / {e['arpu_segment']} → {e['target_tariff']}: оценка {e['mean']:+.2%} недостаточна после поправки на неопределённость.")
    lines += ["", "Другие протестированные варианты могут не попасть в план из-за пересечений, ограничений ресурсов или меньшей расчётной отдачи.", "", "## Предупреждения", ""]
    lines += [f"- {w}" for w in trace["warnings"]] or ["Предупреждений нет."]
    (out / "decision_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out / "decision_report.md")


if __name__ == "__main__":
    main()
