# -*- coding: utf-8 -*-
"""
Live Finance Engine v1.0
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

Принцип (от Аяна):
  baseline финансы + факт денег + live график = живой финансовый контроль стройки
  Не бухгалтерский модуль — строительный финансовый контроль.
  Смысл: показать где стройка начнёт "задыхаться" по финансам.

Входные файлы:
  cash_flow.json            — план по работам (finance_layer v1.0)
  supply_cash_flow.json     — план по материалам (finance_layer v1.1)
  live_gpr_schedule.json    — живой график (live_construction_engine v1.1)
  actual_finance.json       — факт платежей (заполняет прораб/ПТО)

Выходные файлы:
  live_finance_summary.json
  live_finance_by_month.json
  cash_gap_risks.json
  live_finance_chart.html

ИСПОЛЬЗОВАНИЕ:
  python live_finance_engine.py
  python live_finance_engine.py --date 2025-07-15
  python live_finance_engine.py --demo
"""

import json
import csv
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import date, timedelta


# ─── Константы ───────────────────────────────────────────────────────────────

GAP_THRESHOLDS = {
    "ahead":    0,        # фактические расходы опережают план
    "on_track": -0.05,    # отставание до 5% — норма
    "warning":  -0.10,    # 5-10% — предупреждение
    "risk":     -0.25,    # 10-25% — риск
    "critical": -1e18,    # >25% — критично
}


def parse_date(s: str) -> date:
    return date.fromisoformat(s) if s else date(2025, 1, 1)


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def classify_gap(gap: float, plan: float) -> str:
    if plan <= 0:
        return "on_track"
    ratio = gap / plan
    if ratio >= 0:
        return "ahead"
    if ratio >= -0.05:
        return "on_track"
    if ratio >= -0.10:
        return "warning"
    if ratio >= -0.25:
        return "risk"
    return "critical"


# ─── Генератор демо-данных ────────────────────────────────────────────────────

def make_demo_actual(work_cf: dict, supply_cf: dict,
                     report_date: str) -> dict:
    """
    Создаёт реалистичные демо-данные:
    - первые 3 месяца: небольшое опережение
    - потом: нарастающее отставание (реальная стройка)
    """
    rdate   = parse_date(report_date)
    periods = []

    factors = {}
    months_sorted = sorted(set(list(work_cf.keys()) + list(supply_cf.keys())))

    for i, m in enumerate(months_sorted):
        m_date = parse_date(m + "-01")
        if m_date > rdate:
            break  # только прошедшие периоды
        if i < 3:
            factor = 0.95  # небольшое опережение вначале
        elif i < 6:
            factor = 0.75  # умеренное отставание
        else:
            factor = 0.60  # сильное отставание

        plan_w = work_cf.get(m, 0)
        plan_s = supply_cf.get(m, 0)
        plan_t = plan_w + plan_s

        actual_w = plan_w * factor
        actual_s = plan_s * factor
        actual_t = plan_t * factor

        periods.append({
            "month":                m,
            "actual_work_cost":     round(actual_w),
            "actual_material_cost": round(actual_s),
            "actual_total":         round(actual_t),
        })

    return {
        "project":     "Школа №65, Уральск",
        "report_date": report_date,
        "note":        "DEMO данные — замените реальными платежами",
        "periods":     periods,
    }


# ─── Основной класс ──────────────────────────────────────────────────────────

class LiveFinanceEngine:

    def __init__(self, work_cf_path: str, supply_cf_path: str,
                 live_gpr_path: str, actual_path: str,
                 report_date: str):
        self.work_cf_path   = work_cf_path
        self.supply_cf_path = supply_cf_path
        self.live_gpr_path  = live_gpr_path
        self.actual_path    = actual_path
        self.report_date    = report_date
        self.rdate          = parse_date(report_date)

        self.work_cf    = {}   # YYYY-MM → plan_work_cost
        self.supply_cf  = {}   # YYYY-MM → plan_material_cost
        self.actual_cf  = {}   # YYYY-MM → actual data dict
        self.live_delays = {}  # phase → delay_days

        self.monthly    = []   # итоговая помесячная таблица
        self.summary    = {}
        self.risks      = []

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def load(self):
        print(f"[LiveFin] Читаю work cash flow: {self.work_cf_path}...")
        with open(self.work_cf_path, encoding="utf-8") as f:
            wdata = json.load(f)
        for m in wdata.get("months", []):
            self.work_cf[m["period"]] = m.get("planned_cost", 0)
        print(f"[LiveFin] Work CF: {len(self.work_cf)} месяцев")

        print(f"[LiveFin] Читаю supply cash flow: {self.supply_cf_path}...")
        with open(self.supply_cf_path, encoding="utf-8") as f:
            sdata = json.load(f)
        for m in sdata.get("months", []):
            self.supply_cf[m["period"]] = m.get("supply_cost", 0)
        print(f"[LiveFin] Supply CF: {len(self.supply_cf)} месяцев")

        # Live GPR — сдвиги фаз
        if Path(self.live_gpr_path).exists():
            with open(self.live_gpr_path, encoding="utf-8") as f:
                lgpr = json.load(f)
            for task in lgpr.get("tasks", []):
                phase = task.get("phase","")
                delay = task.get("delay_days", 0)
                if phase and delay:
                    self.live_delays[phase] = delay
            print(f"[LiveFin] Live GPR: {len(self.live_delays)} задержек")
        else:
            print(f"[LiveFin] Live GPR не найден — используем baseline")

        # Факт
        if Path(self.actual_path).exists():
            with open(self.actual_path, encoding="utf-8") as f:
                adata = json.load(f)
            rd = adata.get("report_date","")
            if rd:
                self.report_date = rd
                self.rdate = parse_date(rd)
            for p in adata.get("periods", []):
                self.actual_cf[p["month"]] = p
            print(f"[LiveFin] Факт: {len(self.actual_cf)} месяцев, "
                  f"дата: {self.report_date}")
        else:
            print(f"[LiveFin] actual_finance.json не найден — генерирую демо...")
            demo = make_demo_actual(self.work_cf, self.supply_cf,
                                    self.report_date)
            with open("actual_finance_demo.json","w",encoding="utf-8") as f:
                json.dump(demo, f, ensure_ascii=False, indent=2)
            for p in demo.get("periods",[]):
                self.actual_cf[p["month"]] = p
            print(f"[LiveFin] Демо сохранён: actual_finance_demo.json "
                  f"({len(self.actual_cf)} мес.)")

    # ── Расчёт ───────────────────────────────────────────────────────────────

    def calc(self):
        print(f"[LiveFin] Считаю plan vs actual...")

        # Собираем все месяцы
        all_months = sorted(set(
            list(self.work_cf.keys()) +
            list(self.supply_cf.keys()) +
            list(self.actual_cf.keys())
        ))

        cum_plan   = 0.0
        cum_actual = 0.0

        for m in all_months:
            pw  = self.work_cf.get(m, 0)
            ps  = self.supply_cf.get(m, 0)
            pt  = pw + ps
            act = self.actual_cf.get(m, {})
            at  = float(act.get("actual_total", 0)) if act else 0

            is_past = parse_date(m + "-01") <= self.rdate
            has_fact = m in self.actual_cf

            delta = at - pt if has_fact else 0
            cum_plan   += pt
            cum_actual += at if has_fact else 0
            cum_gap     = cum_actual - cum_plan if has_fact else 0

            severity = classify_gap(delta, pt) if has_fact and pt > 0 else "planned"

            self.monthly.append({
                "month":            m,
                "plan_work":        round(pw),
                "plan_material":    round(ps),
                "plan_total":       round(pt),
                "actual_work":      round(float(act.get("actual_work_cost",0))) if act else None,
                "actual_material":  round(float(act.get("actual_material_cost",0))) if act else None,
                "actual_total":     round(at) if has_fact else None,
                "delta":            round(delta) if has_fact else None,
                "delta_pct":        round(delta/pt*100,1) if has_fact and pt>0 else None,
                "cumulative_plan":  round(cum_plan),
                "cumulative_actual": round(cum_actual) if has_fact else None,
                "cumulative_gap":   round(cum_gap) if has_fact else None,
                "is_past":          is_past,
                "has_fact":         has_fact,
                "severity":         severity,
            })

        # Summary
        fact_months  = [r for r in self.monthly if r["has_fact"]]
        total_plan   = sum(r["plan_total"] for r in self.monthly)
        total_actual = sum(r["actual_total"] for r in fact_months if r["actual_total"])
        total_delta  = total_actual - sum(r["plan_total"] for r in fact_months)

        gaps = [r["cumulative_gap"] for r in fact_months if r["cumulative_gap"] is not None]
        peak_gap     = min(gaps) if gaps else 0
        peak_gap_m   = next((r["month"] for r in fact_months
                             if r["cumulative_gap"] == peak_gap), "—")

        overall_ratio = total_delta / sum(r["plan_total"] for r in fact_months) \
                        if fact_months and sum(r["plan_total"] for r in fact_months) > 0 else 0
        if overall_ratio >= 0:
            status = "ahead"
        elif overall_ratio >= -0.05:
            status = "on_track"
        elif overall_ratio >= -0.10:
            status = "warning"
        elif overall_ratio >= -0.25:
            status = "risk"
        else:
            status = "critical"

        risk_level = "high" if status in ("risk","critical") \
                     else "medium" if status == "warning" else "low"

        self.summary = {
            "baseline_total_mln":  round(total_plan/1_000_000, 2),
            "actual_total_mln":    round(total_actual/1_000_000, 2),
            "delta_total_mln":     round(total_delta/1_000_000, 2),
            "delta_pct":           round(overall_ratio*100, 1),
            "peak_cash_gap_mln":   round(peak_gap/1_000_000, 2),
            "peak_gap_month":      peak_gap_m,
            "status":              status,
            "risk_level":          risk_level,
            "periods_with_fact":   len(fact_months),
            "report_date":         self.report_date,
        }

        # Риски
        for r in self.monthly:
            if not r["has_fact"] or r["severity"] in ("planned","on_track","ahead"):
                continue
            gap_mln = round((r["cumulative_gap"] or 0)/1_000_000, 2)
            sev = r["severity"]
            rec = {
                "warning":  "Проверить финансирование — небольшое отставание",
                "risk":     "Ускорить финансирование или скорректировать план закупок",
                "critical": "Срочно: критический кассовый разрыв — требуется решение",
            }.get(sev, "Мониторинг")
            self.risks.append({
                "month":            r["month"],
                "gap_mln":          gap_mln,
                "cumulative_gap_mln": gap_mln,
                "severity":         sev,
                "type":             "cash_deficit",
                "recommendation":   rec,
            })
        self.risks.sort(key=lambda x: x["gap_mln"])

    # ── Сохранение ───────────────────────────────────────────────────────────

    def save(self):
        s = self.summary

        self._save_json({
            "engine_version": "1.0",
            "project":        "Школа №65, Уральск",
            **s,
        }, "live_finance_summary.json")

        self._save_json({
            "engine_version": "1.0",
            "report_date":    self.report_date,
            "months":         self.monthly,
        }, "live_finance_by_month.json")

        self._save_json({
            "engine_version": "1.0",
            "report_date":    self.report_date,
            "risks_count":    len(self.risks),
            "risks":          self.risks,
        }, "cash_gap_risks.json")

        # CSV
        with open("live_finance_by_month.csv","w",encoding="utf-8-sig",
                  newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Период","План работы","План материалы","План итого",
                        "Факт","Дельта","Дельта %","Накопленный разрыв","Статус"])
            for r in self.monthly:
                w.writerow([r["month"],r["plan_work"],r["plan_material"],
                             r["plan_total"],r["actual_total"] or "",
                             r["delta"] or "",r["delta_pct"] or "",
                             r["cumulative_gap"] or "",r["severity"]])
        print(f"[LiveFin] ✅ live_finance_by_month.csv")

        self._build_html()
        self._print_summary()

    def _build_html(self):
        all_plan   = [r["plan_total"]   for r in self.monthly]
        all_actual = [r["actual_total"] for r in self.monthly if r["actual_total"]]
        max_v = max(max(all_plan) if all_plan else 1,
                    max(all_actual) if all_actual else 1)

        cum_gaps = [r["cumulative_gap"] for r in self.monthly
                    if r["cumulative_gap"] is not None]
        min_gap  = min(cum_gaps) if cum_gaps else 0
        max_abs_gap = max(abs(min_gap), 1)

        SCOLORS = {"ahead":"#1D9E75","on_track":"#378ADD","warning":"#EF9F27",
                   "risk":"#BA7517","critical":"#E24B4A","planned":"#B4B2A9"}

        rows = ""
        for r in self.monthly:
            pp  = round(r["plan_total"]/max_v*100,1)
            ap  = round((r["actual_total"] or 0)/max_v*100,1) if r["has_fact"] else 0
            sc  = SCOLORS.get(r["severity"],"#B4B2A9")
            is_peak = r["month"] == self.summary.get("peak_gap_month")
            peak_b  = '<span style="background:#E24B4A;color:#fff;font-size:10px;padding:1px 4px;border-radius:3px;margin-left:3px">пик</span>' if is_peak else ""
            fact_str = f'{round((r["actual_total"] or 0)/1_000_000,2)} млн' if r["has_fact"] else '<span style="color:#bbb">план</span>'
            delta_str = f'<span style="color:{"#E24B4A" if (r["delta"] or 0)<0 else "#1D9E75"}">{round((r["delta"] or 0)/1_000_000,2):+.2f} млн</span>' if r["has_fact"] else "—"
            cum_str = f'{round((r["cumulative_gap"] or 0)/1_000_000,2):+.2f} млн' if r["has_fact"] else "—"
            cum_color = "#E24B4A" if (r["cumulative_gap"] or 0) < 0 else "#1D9E75"

            # Полоска разрыва
            if r["has_fact"] and r["cumulative_gap"] is not None:
                gap_pct = round(abs(r["cumulative_gap"])/max_abs_gap*100,1)
                gap_color = "#E24B4A" if r["cumulative_gap"] < 0 else "#1D9E75"
            else:
                gap_pct = 0
                gap_color = "#B4B2A9"

            rows += f"""
      <tr>
        <td style="padding:4px 10px;font-size:12px;white-space:nowrap;
                   border-bottom:0.5px solid #eee;">{r["month"]}{peak_b}</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;color:#378ADD;">
          {round(r["plan_total"]/1_000_000,2)} млн</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;">{fact_str}</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;">{delta_str}</td>
        <td style="padding:4px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;color:{cum_color};">{cum_str}</td>
        <td style="padding:4px 8px;border-bottom:0.5px solid #eee;min-width:260px;">
          <div style="position:relative;height:28px;">
            <div style="position:absolute;top:0;left:0;width:{pp}%;height:12px;
                        background:#378ADD;border-radius:2px;min-width:2px;"
                 title="План"></div>
            <div style="position:absolute;top:14px;left:0;width:{ap}%;height:12px;
                        background:{sc};border-radius:2px;min-width:2px;"
                 title="Факт"></div>
          </div>
        </td>
      </tr>"""

        # Риски
        risk_rows = ""
        for rk in self.risks[:8]:
            sc = SCOLORS.get(rk["severity"],"#888")
            risk_rows += f"""
      <tr>
        <td style="padding:5px 10px;font-size:12px;border-bottom:0.5px solid #eee;">
          {rk["month"]}</td>
        <td style="padding:5px 8px;font-size:12px;text-align:right;
                   border-bottom:0.5px solid #eee;color:#E24B4A;font-weight:500;">
          {rk["gap_mln"]:+.2f} млн тг</td>
        <td style="padding:5px 8px;border-bottom:0.5px solid #eee;">
          <span style="background:{sc};color:#fff;font-size:11px;
                       padding:2px 7px;border-radius:3px;">{rk["severity"]}</span>
        </td>
        <td style="padding:5px 8px;font-size:12px;color:#666;
                   border-bottom:0.5px solid #eee;">{rk["recommendation"]}</td>
      </tr>"""
        if not risk_rows:
            risk_rows = '<tr><td colspan="4" style="padding:10px;color:#888;font-size:13px">Кассовых разрывов не обнаружено ✅</td></tr>'

        s = self.summary
        STATUS_LABEL = {"ahead":"Опережение 🚀","on_track":"По плану ✅",
                        "warning":"Предупреждение ⚠️","risk":"Риск 🔴",
                        "critical":"Критично 🚨"}
        STATUS_COLOR = {"ahead":"#1D9E75","on_track":"#378ADD",
                        "warning":"#EF9F27","risk":"#BA7517","critical":"#E24B4A"}
        st_label = STATUS_LABEL.get(s["status"],"—")
        st_color = STATUS_COLOR.get(s["status"],"#888")

        html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Live Finance — AINTELLECTUM</title>
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
.legend{{display:flex;gap:20px;margin-bottom:10px;font-size:12px;color:#666}}
.ld{{width:12px;height:12px;border-radius:2px;flex-shrink:0}}
table{{width:100%;border-collapse:collapse;background:#fff;
       border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:24px}}
thead tr{{background:#f5f5f5}}
th{{padding:8px 10px;font-size:12px;font-weight:500;text-align:left;
    border-bottom:0.5px solid #e0e0e0}}
tr:hover{{background:#fafafa}}
.footer{{font-size:11px;color:#bbb;text-align:right;margin-top:16px}}
</style></head><body>
<h1>Live Finance — Школа №65, Уральск</h1>
<div class="sub">AINTELLECTUM · Live Finance Engine v1.0 · {self.report_date}</div>

<div class="cards">
  <div class="card"><div class="cl">Общий план</div>
    <div class="cv">{s["baseline_total_mln"]} млн тг</div></div>
  <div class="card"><div class="cl">Факт освоения</div>
    <div class="cv">{s["actual_total_mln"]} млн тг</div></div>
  <div class="card"><div class="cl">Отклонение</div>
    <div class="cv" style="color:{'#E24B4A' if s['delta_total_mln']<0 else '#1D9E75'}">
      {s["delta_total_mln"]:+.1f} млн ({s["delta_pct"]:+.1f}%)</div></div>
  <div class="card"><div class="cl">Статус</div>
    <div class="cv" style="color:{st_color}">{st_label}</div></div>
</div>

<div class="legend">
  <span style="display:flex;align-items:center;gap:5px">
    <span class="ld" style="background:#378ADD"></span>верх = план</span>
  <span style="display:flex;align-items:center;gap:5px">
    <span class="ld" style="background:#1D9E75"></span>факт (норма)</span>
  <span style="display:flex;align-items:center;gap:5px">
    <span class="ld" style="background:#E24B4A"></span>факт (разрыв)</span>
  <span style="display:flex;align-items:center;gap:5px">
    <span class="ld" style="background:#B4B2A9"></span>ещё не наступило</span>
</div>

<h2>Помесячный план vs факт</h2>
<table>
  <thead><tr><th>Период</th><th>План</th><th>Факт</th>
    <th>Дельта</th><th>Накопленный разрыв</th><th>Диаграмма</th></tr></thead>
  <tbody>{rows}</tbody>
</table>

<h2>Кассовые риски</h2>
<table>
  <thead><tr><th>Месяц</th><th>Разрыв</th><th>Уровень</th><th>Рекомендация</th></tr></thead>
  <tbody>{risk_rows}</tbody>
</table>

<div class="footer">AINTELLECTUM Live Finance Engine v1.0 · Ереке · Аян · Claude</div>
</body></html>"""

        with open("live_finance_chart.html","w",encoding="utf-8") as f:
            f.write(html)
        sz = Path("live_finance_chart.html").stat().st_size
        print(f"[LiveFin] ✅ live_finance_chart.html ({sz//1024} КБ) → браузер")

    def _save_json(self, data, path):
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[LiveFin] ✅ {path} ({Path(path).stat().st_size//1024} КБ)")

    def _print_summary(self):
        s = self.summary
        STATUS_ICONS = {"ahead":"🚀","on_track":"✅","warning":"⚠️",
                        "risk":"🔴","critical":"🚨"}
        print()
        print("="*65)
        print("  LIVE FINANCE ENGINE v1.0 — РЕЗУЛЬТАТ")
        print("="*65)
        print(f"  Дата отчёта:        {self.report_date}")
        print(f"  План (baseline):    {s['baseline_total_mln']:>10.2f} млн тг")
        print(f"  Факт освоено:       {s['actual_total_mln']:>10.2f} млн тг")
        delta_sign = "+" if s['delta_total_mln'] >= 0 else ""
        print(f"  Отклонение:         {delta_sign}{s['delta_total_mln']:>9.2f} млн тг "
              f"({delta_sign}{s['delta_pct']}%)")
        print(f"  Пиковый разрыв:     {s['peak_cash_gap_mln']:>10.2f} млн тг "
              f"({s['peak_gap_month']})")
        icon = STATUS_ICONS.get(s["status"],"")
        print(f"  Статус:             {s['status'].upper()} {icon}")
        print(f"  Уровень риска:      {s['risk_level'].upper()}")
        print()
        if self.risks:
            print("  КАССОВЫЕ РИСКИ:")
            for r in self.risks[:5]:
                print(f"    {r['month']}  {r['gap_mln']:+.2f} млн  "
                      f"[{r['severity']}]")
                print(f"      → {r['recommendation']}")
        else:
            print("  Кассовых разрывов не обнаружено ✅")
        print()
        print("  Файлы: live_finance_summary.json · live_finance_by_month.json")
        print("         cash_gap_risks.json · live_finance_by_month.csv")
        print("         live_finance_chart.html")
        print("="*65)

    def run(self):
        self.load()
        self.calc()
        self.save()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AINTELLECTUM Live Finance Engine v1.0")
    p.add_argument("--work-cf",   default="cash_flow.json")
    p.add_argument("--supply-cf", default="supply_cash_flow.json")
    p.add_argument("--live-gpr",  default="live_gpr_schedule.json")
    p.add_argument("--actual",    default="actual_finance.json")
    p.add_argument("--date",      default="2025-07-15")
    p.add_argument("--demo",      action="store_true",
                   help="Запустить с демо-данными факта")
    args = p.parse_args()

    if args.demo and Path(args.actual).exists():
        Path(args.actual).unlink()

    print("="*65)
    print("  LIVE FINANCE ENGINE v1.0 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  план + факт + отклонение = живой финансовый контроль")
    print("="*65); print()

    eng = LiveFinanceEngine(args.work_cf, args.supply_cf,
                            args.live_gpr, args.actual, args.date)
    eng.run()