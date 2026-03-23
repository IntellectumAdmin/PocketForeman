# -*- coding: utf-8 -*-
"""
Finance Layer v1.0 — Time-Phased
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

Принцип (от Аяна):
  стоимость из сметы + сроки из ГПР = cash flow по периодам

Вход:
  smeta_works_clean.json   — работы с объёмами
  gpr_schedule.json        — даты старта/финиша по фазам
  duration_summary.json    — длительности (опционально)

Выход:
  cash_flow.json           — помесячный cash flow
  finance_summary.json     — сводка по фазам
  cash_flow.csv            — для Excel/таблиц
  cash_flow_chart.html     — визуализация

ИСПОЛЬЗОВАНИЕ:
  python finance_layer.py
  python finance_layer.py --works smeta_works_clean.json --gpr gpr_schedule.json
"""

import json
import csv
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import date, timedelta
import math


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def parse_date(s: str) -> date:
    return date.fromisoformat(s) if s else date(2025, 1, 1)


def month_range(start: date, finish: date) -> list:
    """Список месяцев (YYYY-MM) между двумя датами включительно."""
    months = []
    current = date(start.year, start.month, 1)
    end = date(finish.year, finish.month, 1)
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        # Следующий месяц
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def distribute_evenly(total_cost: float, months: list) -> dict:
    """Равномерное распределение стоимости по месяцам (v1.0 simple)."""
    if not months or total_cost <= 0:
        return {}
    per_month = total_cost / len(months)
    return {m: per_month for m in months}


# ─── Основной класс ──────────────────────────────────────────────────────────

class FinanceLayer:

    def __init__(self, works_path: str, gpr_path: str):
        self.works_path = works_path
        self.gpr_path   = gpr_path

        self.works      = []
        self.gpr_tasks  = {}   # phase → {start_date, finish_date, duration_days}
        self.phase_costs = {}  # phase → total_cost
        self.monthly_cf  = defaultdict(float)  # YYYY-MM → cost
        self.finance_by_phase = []

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def load(self):
        print(f"[Finance] Читаю {self.works_path}...")
        with open(self.works_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in ("work_items", "works", "items"):
                if key in data and isinstance(data[key], list):
                    self.works = data[key]
                    break
        elif isinstance(data, list):
            self.works = data
        print(f"[Finance] Работ загружено: {len(self.works)}")

        print(f"[Finance] Читаю {self.gpr_path}...")
        with open(self.gpr_path, encoding="utf-8") as f:
            gpr_data = json.load(f)
        for task in gpr_data.get("tasks", []):
            phase = task.get("phase", "")
            if phase:
                self.gpr_tasks[phase] = {
                    "start_date":    task.get("start_date"),
                    "finish_date":   task.get("finish_date"),
                    "duration_days": task.get("duration_days", 0),
                }
        print(f"[Finance] Фаз в ГПР: {len(self.gpr_tasks)}")

    # ── Расчёт стоимости по работам ──────────────────────────────────────────

    def calc_phase_costs(self):
        """
        Суммирует стоимость работ по фазам.
        Источник стоимости: поле total_cost или unit_price * volume.
        Если цен нет — используем нормативные proxy-ставки по типу работы.
        """
        print(f"[Finance] Рассчитываю стоимость по фазам...")

        phase_costs = defaultdict(float)
        phase_counts = defaultdict(int)
        works_with_price = 0
        works_proxy = 0

        for w in self.works:
            if w.get("qa_status") == "skipped":
                continue

            phase   = w.get("phase", "Прочие работы")
            volume  = w.get("volume") or 0
            unit    = w.get("unit", "")

            # Пробуем взять цену из сметы
            total_cost  = w.get("total_cost") or w.get("cost") or 0
            unit_price  = w.get("unit_price") or w.get("price") or 0

            if total_cost > 0:
                cost = float(total_cost)
                works_with_price += 1
            elif unit_price > 0 and volume > 0:
                cost = float(unit_price) * float(volume)
                works_with_price += 1
            else:
                # Proxy-ставки (тенге/ед) — грубая оценка для v1.0
                cost = self._proxy_cost(phase, float(volume), unit)
                works_proxy += 1

            phase_costs[phase] += cost
            phase_counts[phase] += 1

        self.phase_costs = dict(phase_costs)

        if works_with_price > 0:
            print(f"[Finance] С ценой из сметы: {works_with_price} работ")
        if works_proxy > 0:
            print(f"[Finance] Proxy-оценка:      {works_proxy} работ "
                  f"(цены не найдены в JSON)")

        total = sum(self.phase_costs.values())
        print(f"[Finance] Общая стоимость:   {total:,.0f} тг")

    def _proxy_cost(self, phase: str, volume: float, unit: str) -> float:
        """
        Грубые proxy-ставки (тенге/ед) для оценки если в JSON нет цен.
        Источник: типовые расценки РК 2024-2025.
        """
        if volume <= 0:
            return 0.0

        RATES = {
            # (фраза в названии фазы, единица) → тг/ед
            ("Земляные",      "м3"):  2_500,
            ("Монолитный",    "м3"):  85_000,
            ("Каменные",      "м3"):  45_000,
            ("Металлические", "т"):   450_000,
            ("Металлические", "м2"):  15_000,
            ("Деревянные",    "м2"):  12_000,
            ("Кровля",        "м2"):  8_500,
            ("Гидро",         "м2"):  4_200,
            ("Окна",          "м2"):  55_000,
            ("Отделочные",    "м2"):  6_500,
            ("Полы",          "м2"):  7_200,
            ("Электроснаб",   "м"):   1_800,
            ("Водоснаб",      "м"):   2_200,
            ("Вентиляция",    "м2"):  9_500,
            ("Сантехника",    "м2"):  5_000,
            ("Благоустройство","м2"): 3_800,
        }

        unit_norm = unit.lower().strip() if unit else ""
        phase_low = phase.lower()

        for (phase_kw, unit_kw), rate in RATES.items():
            if phase_kw.lower() in phase_low and unit_kw == unit_norm:
                return volume * rate

        # Последний fallback — 3000 тг/ед
        return volume * 3_000

    # ── Распределение по месяцам ─────────────────────────────────────────────

    def distribute_to_months(self):
        """Равномерное распределение стоимости фазы по её месяцам (v1.0)."""
        print(f"[Finance] Распределяю по месяцам...")

        self.monthly_cf = defaultdict(float)
        self.finance_by_phase = []

        for phase, cost in sorted(self.phase_costs.items(),
                                   key=lambda x: -x[1]):
            task = self.gpr_tasks.get(phase)
            if not task or not task.get("start_date"):
                # Фаза есть в сметы но нет в ГПР — кладём в первый месяц
                self.monthly_cf["2025-01"] += cost
                self.finance_by_phase.append({
                    "phase":       phase,
                    "total_cost":  round(cost),
                    "start_date":  None,
                    "finish_date": None,
                    "months":      ["2025-01"],
                    "note":        "нет в ГПР — отнесено к старту",
                })
                continue

            start  = parse_date(task["start_date"])
            finish = parse_date(task["finish_date"])
            months = month_range(start, finish)

            distribution = distribute_evenly(cost, months)
            for m, v in distribution.items():
                self.monthly_cf[m] += v

            self.finance_by_phase.append({
                "phase":        phase,
                "total_cost":   round(cost),
                "start_date":   task["start_date"],
                "finish_date":  task["finish_date"],
                "duration_days": task["duration_days"],
                "months_count": len(months),
                "per_month":    round(cost / len(months)) if months else 0,
                "months":       months,
            })

    # ── Сохранение ───────────────────────────────────────────────────────────

    def save(self,
             cf_path:      str = "cash_flow.json",
             summary_path: str = "finance_summary.json",
             csv_path:     str = "cash_flow.csv",
             html_path:    str = "cash_flow_chart.html"):

        total = sum(self.monthly_cf.values())
        sorted_months = sorted(self.monthly_cf.items())
        peak_month = max(self.monthly_cf, key=self.monthly_cf.get,
                         default="—") if self.monthly_cf else "—"
        peak_value = self.monthly_cf.get(peak_month, 0)

        # 1. cash_flow.json
        with open(cf_path, "w", encoding="utf-8") as f:
            json.dump({
                "finance_version": "1.0",
                "project":         "Школа №65, Уральск",
                "total_cost":      round(total),
                "total_cost_mln":  round(total / 1_000_000, 2),
                "peak_month":      peak_month,
                "peak_cost":       round(peak_value),
                "months_count":    len(sorted_months),
                "months": [
                    {"period": m, "planned_cost": round(v),
                     "planned_cost_mln": round(v / 1_000_000, 3)}
                    for m, v in sorted_months
                ],
            }, f, ensure_ascii=False, indent=2)
        print(f"[Finance] ✅ {cf_path} ({Path(cf_path).stat().st_size // 1024} КБ)")

        # 2. finance_summary.json
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "finance_version": "1.0",
                "project":         "Школа №65, Уральск",
                "total_cost":      round(total),
                "total_cost_mln":  round(total / 1_000_000, 2),
                "peak_month":      peak_month,
                "peak_cost_mln":   round(peak_value / 1_000_000, 3),
                "phases": sorted(
                    self.finance_by_phase,
                    key=lambda x: -x["total_cost"]
                ),
            }, f, ensure_ascii=False, indent=2)
        print(f"[Finance] ✅ {summary_path} ({Path(summary_path).stat().st_size // 1024} КБ)")

        # 3. cash_flow.csv
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Период", "Плановые затраты (тг)",
                             "Плановые затраты (млн тг)"])
            for m, v in sorted_months:
                writer.writerow([m, round(v), round(v / 1_000_000, 3)])
        print(f"[Finance] ✅ {csv_path}")

        # 4. HTML визуализация
        self._build_html(sorted_months, total, peak_month, peak_value, html_path)

        self._print_summary(total, sorted_months, peak_month, peak_value)

    def _build_html(self, sorted_months, total, peak_month, peak_value, html_path):
        max_v = max(v for _, v in sorted_months) if sorted_months else 1

        bars_html = ""
        for m, v in sorted_months:
            pct = round(v / max_v * 100, 1)
            is_peak = m == peak_month
            bc = "#BA7517" if is_peak else "#378ADD"
            peak_badge = ' <span style="background:#BA7517;color:#fff;font-size:10px;padding:1px 4px;border-radius:3px">пик</span>' if is_peak else ""
            bars_html += f"""
      <tr>
        <td style="padding:4px 10px;font-size:12px;white-space:nowrap;
                   border-bottom:0.5px solid #eee;">{m}{peak_badge}</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;color:#555;">
          {round(v/1_000_000, 2)} млн</td>
        <td style="padding:4px 8px;border-bottom:0.5px solid #eee;min-width:300px;">
          <div style="width:{pct}%;height:18px;background:{bc};
                      border-radius:3px;min-width:2px;"></div>
        </td>
      </tr>"""

        # Топ-5 фаз по стоимости
        top_phases = sorted(self.finance_by_phase,
                            key=lambda x: -x["total_cost"])[:5]
        phases_html = ""
        for p in top_phases:
            phases_html += f"""
      <tr>
        <td style="padding:5px 10px;font-size:12px;border-bottom:0.5px solid #eee;">
          {p['phase']}</td>
        <td style="padding:5px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;font-weight:500;">
          {round(p['total_cost']/1_000_000, 2)} млн тг</td>
        <td style="padding:5px 8px;font-size:12px;color:#777;
                   border-bottom:0.5px solid #eee;">
          {p.get('start_date','—')} → {p.get('finish_date','—')}</td>
      </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Cash Flow — AINTELLECTUM</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:#fafafa;
     color:#1a1a1a;padding:24px}}
h1{{font-size:18px;font-weight:500;margin-bottom:4px}}
.sub{{font-size:13px;color:#888;margin-bottom:20px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);
        gap:12px;margin-bottom:24px}}
.card{{background:#fff;border:0.5px solid #e0e0e0;
       border-radius:8px;padding:12px 16px}}
.cl{{font-size:11px;color:#999;margin-bottom:4px}}
.cv{{font-size:20px;font-weight:500}}
h2{{font-size:15px;font-weight:500;margin:24px 0 12px}}
table{{width:100%;border-collapse:collapse;background:#fff;
       border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;
       margin-bottom:24px}}
thead tr{{background:#f5f5f5}}
th{{padding:8px 10px;font-size:12px;font-weight:500;
    text-align:left;border-bottom:0.5px solid #e0e0e0}}
.footer{{margin-top:16px;font-size:11px;color:#bbb;text-align:right}}
</style></head><body>
<h1>Cash Flow — Школа №65, Уральск</h1>
<div class="sub">AINTELLECTUM · Finance Layer v1.0 · Плановый cash flow</div>

<div class="cards">
  <div class="card"><div class="cl">Общая стоимость</div>
    <div class="cv">{round(total/1_000_000, 1)} млн тг</div></div>
  <div class="card"><div class="cl">Пик финансирования</div>
    <div class="cv">{peak_month}</div></div>
  <div class="card"><div class="cl">Пик в месяц</div>
    <div class="cv">{round(peak_value/1_000_000, 2)} млн тг</div></div>
  <div class="card"><div class="cl">Периодов</div>
    <div class="cv">{len(sorted_months)} мес.</div></div>
</div>

<h2>Помесячный план финансирования</h2>
<table>
  <thead><tr><th>Период</th><th>Затраты</th><th>Диаграмма</th></tr></thead>
  <tbody>{bars_html}</tbody>
</table>

<h2>Топ-5 фаз по стоимости</h2>
<table>
  <thead><tr><th>Фаза</th><th>Стоимость</th><th>Период</th></tr></thead>
  <tbody>{phases_html}</tbody>
</table>

<div class="footer">AINTELLECTUM Finance Layer v1.0 · Ереке · Аян · Claude</div>
</body></html>"""

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[Finance] ✅ {html_path} → открой в браузере")

    def _print_summary(self, total, sorted_months, peak_month, peak_value):
        print()
        print("=" * 65)
        print("  FINANCE LAYER v1.0 — РЕЗУЛЬТАТ")
        print("=" * 65)
        print(f"  Общая стоимость:   {total:>15,.0f} тг")
        print(f"                     {total/1_000_000:>15.2f} млн тг")
        print(f"  Пик финансирования: {peak_month}  "
              f"({round(peak_value/1_000_000, 2)} млн тг/мес)")
        print()
        print("  ТОП-5 ДОРОГИХ ФАЗ:")
        for p in sorted(self.finance_by_phase,
                        key=lambda x: -x["total_cost"])[:5]:
            print(f"  {p['phase']:<38} "
                  f"{round(p['total_cost']/1_000_000, 2):>8.2f} млн тг")
        print()
        print("  CASH FLOW (млн тг/мес):")
        for m, v in sorted_months:
            bar = "█" * min(30, int(v / max(1, max(vv for _, vv in sorted_months)) * 30))
            print(f"  {m}  {round(v/1_000_000, 2):>8.2f}  {bar}")
        print()
        print("  Файлы: cash_flow.json, finance_summary.json, "
              "cash_flow.csv, cash_flow_chart.html")
        print("=" * 65)

    def run(self):
        self.load()
        self.calc_phase_costs()
        self.distribute_to_months()
        self.save()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AINTELLECTUM Finance Layer v1.0"
    )
    parser.add_argument("--works",   default="smeta_works_clean.json")
    parser.add_argument("--gpr",     default="gpr_schedule.json")
    parser.add_argument("--cf",      default="cash_flow.json")
    parser.add_argument("--summary", default="finance_summary.json")
    parser.add_argument("--csv",     default="cash_flow.csv")
    parser.add_argument("--html",    default="cash_flow_chart.html")
    args = parser.parse_args()

    print("=" * 65)
    print("  FINANCE LAYER v1.0 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  стоимость из сметы + сроки из ГПР = cash flow")
    print("=" * 65)
    print()

    fl = FinanceLayer(args.works, args.gpr)
    fl.run()