# -*- coding: utf-8 -*-
"""
Finance Layer v1.1 — Supply-Linked Cash Flow
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

ИЗМЕНЕНИЯ v1.1 vs v1.0:
  - Materials cost + supply-linked cash flow
  - Привязка материалов к фазам ГПР (не равномерно по проекту!)
  - Supply shift: закупка за SUPPLY_LEAD_DAYS до начала фазы
  - Overlay: work cash flow + material cash flow
  - supply_cash_flow_chart.html — два слоя (работы синий + материалы зелёный)

Принцип (от Аяна):
  material → phase → time window → cost distribution
  НЕ равномерно по проекту — только внутри своей фазы!

Входные файлы:
  materials_summary.json   (от materials_extractor v2.0)
  gpr_schedule.json        (baseline ГПР)
  cash_flow.json           (work cash flow от finance_layer v1.0)

Выходные файлы:
  supply_cash_flow.json
  supply_finance_summary.json
  supply_cash_flow.csv
  supply_cash_flow_chart.html

ИСПОЛЬЗОВАНИЕ:
  python finance_layer.py --mode supply
  python finance_layer.py --mode supply --lead-days 15
"""

import json
import csv
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import date, timedelta


# ─── Конфигурация ────────────────────────────────────────────────────────────

SUPPLY_LEAD_DAYS = 15   # закупка за 15 дней до начала фазы

# Proxy-ставки для материалов по категории (тг/ед) — если нет цен в JSON
PROXY_RATES_MAT = {
    # Категория → (единица, тг/ед)
    "Нерудные материалы":          ("м3",  3_500),
    "Бетон и растворы":            ("м3",  35_000),
    "Металлы и метизы":            ("кг",  1_200),
    "Пиломатериалы":               ("м3",  80_000),
    "Вяжущие и сыпучие":           ("т",   25_000),
    "Прочие строительные":         ("шт",  500),
    "Отделочные материалы":        ("м2",  4_500),
    "Изоляционные материалы":      ("м2",  3_800),
    "Кровельные материалы":        ("м2",  6_500),
    "Химия и растворители":        ("кг",  800),
    "Трубы и трубопроводы":        ("м",   2_500),
    "Трубопроводная арматура":     ("шт",  15_000),
    "Электромонтажные материалы":  ("м",   500),
    "Вентиляционные изделия":      ("м2",  9_000),
    "Противопожарные материалы":   ("шт",  12_000),
    "Расходные материалы":         ("шт",  300),
    "Прочие материалы":            ("шт",  200),
}

# Категория материала → фаза (fallback если фаза не указана)
CATEGORY_TO_PHASE = {
    "Нерудные материалы":          "Земляные работы",
    "Бетон и растворы":            "Монолитный каркас",
    "Металлы и метизы":            "Металлические конструкции",
    "Пиломатериалы":               "Деревянные конструкции",
    "Вяжущие и сыпучие":           "Монолитный каркас",
    "Прочие строительные":         "Монолитный каркас",
    "Отделочные материалы":        "Отделочные работы",
    "Изоляционные материалы":      "Гидро- и пароизоляция",
    "Кровельные материалы":        "Кровля наружная",
    "Химия и растворители":        "Отделочные работы",
    "Трубы и трубопроводы":        "Водоснабжение и канализация",
    "Трубопроводная арматура":     "Водоснабжение и канализация",
    "Электромонтажные материалы":  "Электроснабжение",
    "Вентиляционные изделия":      "Вентиляция и кондиционирование",
    "Противопожарные материалы":   "Прочие работы",
    "Расходные материалы":         "Прочие работы",
    "Прочие материалы":            "Прочие работы",
}


def parse_date(s: str) -> date:
    return date.fromisoformat(s) if s else date(2025, 1, 1)


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def months_in_range(start: date, finish: date) -> list:
    months = []
    cur = date(start.year, start.month, 1)
    end = date(finish.year, finish.month, 1)
    while cur <= end:
        months.append(cur.strftime("%Y-%m"))
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 \
              else date(cur.year, cur.month + 1, 1)
    return months


def calc_material_cost(item: dict) -> float:
    """Стоимость одной позиции материала."""
    # Пробуем взять цену из данных
    tc = item.get("total_cost") or item.get("cost") or 0
    up = item.get("unit_price") or item.get("price") or 0
    vol = float(item.get("volume") or 0)

    if tc > 0:
        return float(tc)
    if up > 0 and vol > 0:
        return float(up) * vol

    # Proxy по категории
    cat   = item.get("material_type", item.get("category", "Прочие материалы"))
    unit  = str(item.get("unit", "")).strip().lower()
    proxy = PROXY_RATES_MAT.get(cat, ("шт", 300))
    rate  = proxy[1]

    if vol > 0:
        return vol * rate
    return rate  # нет объёма — берём единичную ставку


# ─── Основной класс ──────────────────────────────────────────────────────────

class FinanceLayerV11:

    def __init__(self, materials_path: str, gpr_path: str,
                 work_cf_path: str, lead_days: int = SUPPLY_LEAD_DAYS):
        self.materials_path = materials_path
        self.gpr_path       = gpr_path
        self.work_cf_path   = work_cf_path
        self.lead_days      = lead_days

        self.materials  = []   # все материалы
        self.gpr_phases = {}   # phase_name → {start, finish}
        self.work_cf    = {}   # YYYY-MM → work_cost

        self.mat_by_phase    = defaultdict(list)   # phase → [items]
        self.mat_by_category = defaultdict(list)   # category → [items]
        self.supply_monthly  = defaultdict(float)  # YYYY-MM → supply_cost
        self.phase_costs     = {}  # phase → total_mat_cost

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def load(self):
        print(f"[Supply] Читаю материалы: {self.materials_path}...")
        with open(self.materials_path, encoding="utf-8") as f:
            data = json.load(f)

        # Поддерживаем оба формата materials_extractor v2.0
        items = []
        if isinstance(data, dict):
            # Из types_plan берём all_materials или top_items
            if "all_materials" in data:
                items = data["all_materials"]
            elif "types_plan" in data:
                for tp in data["types_plan"]:
                    items.extend(tp.get("top_items", []))
            for key in ("material_items", "items"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
        elif isinstance(data, list):
            items = data

        self.materials = [i for i in items if isinstance(i, dict)]
        print(f"[Supply] Материалов: {len(self.materials)}")

        print(f"[Supply] Читаю ГПР: {self.gpr_path}...")
        with open(self.gpr_path, encoding="utf-8") as f:
            gpr = json.load(f)
        for task in gpr.get("tasks", []):
            phase = task.get("phase","").strip()
            if phase and task.get("start_date") and task.get("finish_date"):
                self.gpr_phases[phase] = {
                    "start":  parse_date(task["start_date"]),
                    "finish": parse_date(task["finish_date"]),
                    "duration_days": task.get("duration_days", 30),
                }
        print(f"[Supply] Фаз в ГПР: {len(self.gpr_phases)}")

        # Work cash flow (v1.0) — для overlay
        if Path(self.work_cf_path).exists():
            with open(self.work_cf_path, encoding="utf-8") as f:
                cf = json.load(f)
            for m in cf.get("months", []):
                self.work_cf[m["period"]] = m.get("planned_cost", 0)
            print(f"[Supply] Work CF: {len(self.work_cf)} месяцев")
        else:
            print(f"[Supply] Work CF не найден ({self.work_cf_path}) — только материалы")

    # ── Расчёт стоимости и группировка ───────────────────────────────────────

    def calc_costs(self):
        print(f"[Supply] Рассчитываю стоимость материалов...")

        for item in self.materials:
            cost = calc_material_cost(item)
            item["_cost"] = cost

            # Определяем фазу
            phase = str(item.get("supply_phase",
                         item.get("phase", ""))).strip()
            if not phase:
                cat   = item.get("material_type",
                                  item.get("category", "Прочие материалы"))
                phase = CATEGORY_TO_PHASE.get(cat, "Прочие работы")
            item["_phase"] = phase

            cat = item.get("material_type",
                            item.get("category", "Прочие материалы"))
            self.mat_by_phase[phase].append(item)
            self.mat_by_category[cat].append(item)

        total = sum(i["_cost"] for i in self.materials)
        print(f"[Supply] Общая стоимость материалов: {total:,.0f} тг "
              f"({total/1_000_000:.2f} млн тг)")

    # ── Распределение по времени ──────────────────────────────────────────────

    def distribute(self):
        """
        Ключевая логика (от Аяна):
          material → phase → time window → distribute cost
          supply_start = phase_start - LEAD_DAYS
          НЕ равномерно по проекту!
        """
        print(f"[Supply] Привязываю к фазам и распределяю по месяцам "
              f"(lead={self.lead_days} дн.)...")

        unresolved_cost = 0

        for phase, items in self.mat_by_phase.items():
            phase_total = sum(i["_cost"] for i in items)
            self.phase_costs[phase] = phase_total

            gpr = self.gpr_phases.get(phase)
            if not gpr:
                # Фаза не найдена в ГПР — кладём в первый месяц
                self.supply_monthly["2025-01"] += phase_total
                unresolved_cost += phase_total
                continue

            # supply_start = phase_start - lead_days
            supply_start  = gpr["start"] - timedelta(days=self.lead_days)
            supply_finish = gpr["finish"]
            months = months_in_range(supply_start, supply_finish)
            if not months:
                self.supply_monthly["2025-01"] += phase_total
                continue

            per_month = phase_total / len(months)
            for m in months:
                self.supply_monthly[m] += per_month

        if unresolved_cost > 0:
            print(f"[Supply]   Не привязано к ГПР: "
                  f"{unresolved_cost/1_000_000:.2f} млн тг → отнесено к старту")

    # ── Сохранение ───────────────────────────────────────────────────────────

    def save(self):
        sorted_months = sorted(self.supply_monthly.items())
        total_mat = sum(self.supply_monthly.values())
        total_work = sum(self.work_cf.values())
        peak_m = max(self.supply_monthly, key=self.supply_monthly.get,
                     default="—") if self.supply_monthly else "—"
        peak_v = self.supply_monthly.get(peak_m, 0)

        # Top категории
        top_cats = sorted(
            [(cat, sum(i["_cost"] for i in items))
             for cat, items in self.mat_by_category.items()],
            key=lambda x: -x[1]
        )[:8]

        # Top фазы
        top_phases = sorted(self.phase_costs.items(), key=lambda x: -x[1])[:8]

        # 1. supply_cash_flow.json
        self._save_json({
            "finance_version": "1.1",
            "project":         "Школа №65, Уральск",
            "supply_lead_days": self.lead_days,
            "total_material_cost":      round(total_mat),
            "total_material_cost_mln":  round(total_mat / 1_000_000, 2),
            "peak_month":      peak_m,
            "peak_cost":       round(peak_v),
            "months": [
                {"period": m,
                 "supply_cost":     round(v),
                 "supply_cost_mln": round(v / 1_000_000, 3),
                 "work_cost":       round(self.work_cf.get(m, 0)),
                 "total_cost":      round(v + self.work_cf.get(m, 0))}
                for m, v in sorted_months
            ],
        }, "supply_cash_flow.json")

        # 2. supply_finance_summary.json
        self._save_json({
            "finance_version":  "1.1",
            "total_material_cost_mln": round(total_mat / 1_000_000, 2),
            "total_work_cost_mln":     round(total_work / 1_000_000, 2),
            "total_project_cost_mln":  round((total_mat + total_work) / 1_000_000, 2),
            "supply_lead_days":        self.lead_days,
            "peak_supply_month":       peak_m,
            "peak_supply_cost_mln":    round(peak_v / 1_000_000, 3),
            "top_categories": [
                {"category": c, "cost_mln": round(v / 1_000_000, 2)}
                for c, v in top_cats
            ],
            "top_phases": [
                {"phase": p, "cost_mln": round(v / 1_000_000, 2)}
                for p, v in top_phases
            ],
        }, "supply_finance_summary.json")

        # 3. CSV
        with open("supply_cash_flow.csv", "w", encoding="utf-8-sig",
                  newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Период","Материалы (тг)","Работы (тг)",
                        "Итого (тг)","Материалы (млн)"])
            for m, v in sorted_months:
                wv = self.work_cf.get(m, 0)
                w.writerow([m, round(v), round(wv), round(v+wv),
                             round(v/1_000_000, 3)])
        print(f"[Supply] ✅ supply_cash_flow.csv")

        # 4. HTML
        self._build_html(sorted_months, total_mat, total_work,
                         peak_m, top_cats, top_phases)
        self._print_summary(sorted_months, total_mat, total_work,
                            peak_m, peak_v, top_cats, top_phases)

    def _build_html(self, sorted_months, total_mat, total_work,
                    peak_m, top_cats, top_phases):
        all_vals = [v + self.work_cf.get(m, 0) for m, v in sorted_months]
        max_v = max(all_vals) if all_vals else 1

        rows = ""
        for m, sv in sorted_months:
            wv   = self.work_cf.get(m, 0)
            tv   = sv + wv
            s_pct = round(sv / max_v * 100, 1)
            w_pct = round(wv / max_v * 100, 1)
            is_peak = m == peak_m
            peak_b = '<span style="background:#1D9E75;color:#fff;font-size:10px;padding:1px 4px;border-radius:3px;margin-left:4px">пик</span>' if is_peak else ""
            rows += f"""
      <tr>
        <td style="padding:4px 10px;font-size:12px;white-space:nowrap;
                   border-bottom:0.5px solid #eee;">{m}{peak_b}</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;color:#1D9E75;">
          {round(sv/1_000_000,2)} млн</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;color:#378ADD;">
          {round(wv/1_000_000,2)} млн</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;font-weight:500;">
          {round(tv/1_000_000,2)} млн</td>
        <td style="padding:4px 8px;border-bottom:0.5px solid #eee;min-width:280px;">
          <div style="position:relative;height:28px;">
            <div style="position:absolute;top:0;left:0;width:{s_pct}%;
                        height:13px;background:#1D9E75;border-radius:2px;
                        min-width:2px;" title="Материалы"></div>
            <div style="position:absolute;top:14px;left:0;width:{w_pct}%;
                        height:13px;background:#378ADD;border-radius:2px;
                        min-width:2px;" title="Работы"></div>
          </div>
        </td>
      </tr>"""

        # Топ категорий
        cat_rows = ""
        max_cat = top_cats[0][1] if top_cats else 1
        for cat, cv in top_cats:
            pct = round(cv / max_cat * 100, 1)
            cat_rows += f"""
      <tr>
        <td style="padding:5px 10px;font-size:12px;border-bottom:0.5px solid #eee;">
          {cat}</td>
        <td style="padding:5px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;font-weight:500;color:#1D9E75;">
          {round(cv/1_000_000,2)} млн тг</td>
        <td style="padding:5px 8px;border-bottom:0.5px solid #eee;min-width:200px;">
          <div style="width:{pct}%;height:14px;background:#1D9E75;
                      border-radius:2px;min-width:2px;"></div>
        </td>
      </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Supply Cash Flow — AINTELLECTUM</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:#fafafa;color:#1a1a1a;padding:24px}}
h1{{font-size:18px;font-weight:500;margin-bottom:4px}}
.sub{{font-size:13px;color:#888;margin-bottom:20px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}}
.card{{background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;padding:12px 16px}}
.cl{{font-size:11px;color:#999;margin-bottom:4px}}
.cv{{font-size:18px;font-weight:500}}
h2{{font-size:15px;font-weight:500;margin:20px 0 12px}}
.legend{{display:flex;gap:20px;margin-bottom:10px;font-size:12px;color:#666;align-items:center}}
.ld{{width:12px;height:12px;border-radius:2px;flex-shrink:0}}
table{{width:100%;border-collapse:collapse;background:#fff;
       border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:24px}}
thead tr{{background:#f5f5f5}}
th{{padding:8px 10px;font-size:12px;font-weight:500;text-align:left;
    border-bottom:0.5px solid #e0e0e0}}
tr:hover{{background:#fafafa}}
.footer{{font-size:11px;color:#bbb;text-align:right;margin-top:16px}}
</style></head><body>
<h1>Supply Cash Flow — Школа №65, Уральск</h1>
<div class="sub">AINTELLECTUM · Finance Layer v1.1 · Lead time: {self.lead_days} дн.</div>
<div class="cards">
  <div class="card"><div class="cl">Материалы (план)</div>
    <div class="cv" style="color:#1D9E75">{round(total_mat/1_000_000,1)} млн тг</div></div>
  <div class="card"><div class="cl">Работы (план)</div>
    <div class="cv" style="color:#378ADD">{round(total_work/1_000_000,1)} млн тг</div></div>
  <div class="card"><div class="cl">Итого проект</div>
    <div class="cv">{round((total_mat+total_work)/1_000_000,1)} млн тг</div></div>
  <div class="card"><div class="cl">Пик закупок</div>
    <div class="cv">{peak_m}</div></div>
</div>
<h2>Помесячный план финансирования</h2>
<div class="legend">
  <span style="display:flex;align-items:center;gap:5px">
    <span class="ld" style="background:#1D9E75"></span>верх = материалы</span>
  <span style="display:flex;align-items:center;gap:5px">
    <span class="ld" style="background:#378ADD"></span>низ = работы</span>
</div>
<table>
  <thead><tr><th>Период</th><th>Материалы</th><th>Работы</th>
    <th>Итого</th><th>Диаграмма</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<h2>Топ категорий материалов</h2>
<table>
  <thead><tr><th>Категория</th><th>Стоимость</th><th>Диаграмма</th></tr></thead>
  <tbody>{cat_rows}</tbody>
</table>
<div class="footer">AINTELLECTUM Finance Layer v1.1 · Ереке · Аян · Claude</div>
</body></html>"""

        with open("supply_cash_flow_chart.html","w",encoding="utf-8") as f:
            f.write(html)
        size = Path("supply_cash_flow_chart.html").stat().st_size
        print(f"[Supply] ✅ supply_cash_flow_chart.html ({size//1024} КБ) → браузер")

    def _save_json(self, data, path):
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size = Path(path).stat().st_size
        print(f"[Supply] ✅ {path} ({size//1024} КБ)")

    def _print_summary(self, sorted_months, total_mat, total_work,
                       peak_m, peak_v, top_cats, top_phases):
        total_project = total_mat + total_work
        print()
        print("="*65)
        print("  FINANCE LAYER v1.1 — SUPPLY CASH FLOW")
        print("="*65)
        print(f"  Материалы:         {total_mat/1_000_000:>10.2f} млн тг")
        print(f"  Работы (v1.0):     {total_work/1_000_000:>10.2f} млн тг")
        print(f"  ИТОГО ПРОЕКТ:      {total_project/1_000_000:>10.2f} млн тг")
        print(f"  Lead time:         {self.lead_days} дн.")
        print(f"  Пик закупок:       {peak_m} ({round(peak_v/1_000_000,2)} млн/мес)")
        print()
        print("  ТОП КАТЕГОРИЙ МАТЕРИАЛОВ:")
        for cat, cv in top_cats[:5]:
            pct = round(cv / total_mat * 100, 1) if total_mat else 0
            print(f"    {cat:<38} {cv/1_000_000:>7.2f} млн  {pct}%")
        print()
        print("  ТОП ФАЗ ПО МАТЕРИАЛАМ:")
        for phase, cv in top_phases[:5]:
            print(f"    {phase:<38} {cv/1_000_000:>7.2f} млн тг")
        print()
        print("  CASH FLOW (материалы млн/мес):")
        max_v = max(v for _, v in sorted_months) if sorted_months else 1
        for m, v in sorted_months:
            bar = "█" * min(25, int(v/max_v*25))
            print(f"  {m}  {round(v/1_000_000,2):>7.2f}  {bar}")
        print()
        print("  Файлы: supply_cash_flow.json · supply_finance_summary.json")
        print("         supply_cash_flow.csv  · supply_cash_flow_chart.html")
        print("="*65)

    def run(self):
        self.load()
        self.calc_costs()
        self.distribute()
        self.save()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AINTELLECTUM Finance Layer v1.1")
    p.add_argument("--materials", default="materials_summary.json")
    p.add_argument("--gpr",       default="gpr_schedule.json")
    p.add_argument("--work-cf",   default="cash_flow.json")
    p.add_argument("--lead-days", type=int, default=SUPPLY_LEAD_DAYS)
    args = p.parse_args()

    print("="*65)
    print("  FINANCE LAYER v1.1 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  материалы + фазы + время = supply cash flow")
    print("="*65); print()

    fl = FinanceLayerV11(args.materials, args.gpr, args.work_cf, args.lead_days)
    fl.run()