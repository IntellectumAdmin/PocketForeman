# -*- coding: utf-8 -*-
"""
Decision Engine v1.0
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

Назначение (от Аяна):
  Слой управленческих решений.
  Читает отклонения (сроки + деньги) и выдаёт приоритеты, риски, действия.

  v1.0 = только rule-based. Никакого ML/AI. Простота и объяснимость.

Входные файлы:
  live_gpr_summary.json
  live_delay_risks.json
  live_finance_summary.json
  cash_gap_risks.json
  live_vs_baseline.json

Выходные файлы:
  decision_summary.json
  recommended_actions.json
  top_risks.json
  decision_report.html

ИСПОЛЬЗОВАНИЕ:
  python decision_engine.py
  python decision_engine.py --date 2025-07-15
"""

import json
import argparse
from pathlib import Path
from datetime import date


# ─── Правила классификации ───────────────────────────────────────────────────

IMPACT_CRITICAL = "CRITICAL"
IMPACT_HIGH     = "HIGH"
IMPACT_MEDIUM   = "MEDIUM"
IMPACT_LOW      = "LOW"

CASH_GAP_CRITICAL = -200_000_000   # -200 млн тг → CRITICAL
CASH_GAP_HIGH     = -50_000_000    # -50  млн тг → HIGH


# ─── Вспомогательные ─────────────────────────────────────────────────────────

def safe_load(path: str) -> dict | list | None:
    p = Path(path)
    if not p.exists():
        print(f"[Decision]   {path} не найден — пропускаем")
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def fmt_mln(v: float) -> str:
    return f"{v/1_000_000:+.2f} млн тг"


# ─── Основной класс ──────────────────────────────────────────────────────────

class DecisionEngine:

    def __init__(self, report_date: str):
        self.report_date = report_date

        # Входные данные
        self.gpr_summary    = {}
        self.delay_risks    = []
        self.finance_summary = {}
        self.cash_gap_risks  = []
        self.vs_baseline     = []

        # Результаты
        self.all_risks   = []   # объединённый список рисков
        self.actions     = []   # рекомендованные действия
        self.top_problem = {}
        self.counters    = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def load(self):
        print("[Decision] Загружаю входные данные...")

        gpr = safe_load("live_gpr_summary.json")
        if gpr:
            self.gpr_summary = gpr
            rd = gpr.get("report_date","")
            if rd:
                self.report_date = rd

        dr = safe_load("live_delay_risks.json")
        if dr:
            self.delay_risks = dr.get("risks", [])
        print(f"[Decision]   Риски сроков: {len(self.delay_risks)}")

        fin = safe_load("live_finance_summary.json")
        if fin:
            self.finance_summary = fin

        cgr = safe_load("cash_gap_risks.json")
        if cgr:
            self.cash_gap_risks = cgr.get("risks", [])
        print(f"[Decision]   Кассовые риски: {len(self.cash_gap_risks)}")

        vsb = safe_load("live_vs_baseline.json")
        if vsb:
            self.vs_baseline = vsb.get("items", [])

    # ── Сбор и классификация рисков ──────────────────────────────────────────

    def collect_risks(self):
        print("[Decision] Классифицирую риски...")
        rid = 0

        # ── Риски из сроков ──────────────────────────────────────────────────
        for dr in self.delay_risks:
            rid += 1
            phase     = dr.get("phase","")
            rtype     = dr.get("risk_type","")
            is_cp     = dr.get("is_critical", False)
            reason    = dr.get("reason","")
            impact_d  = dr.get("impact_days", 0)

            # Классификация по правилам Аяна
            if is_cp and rtype == "blocked":
                impact = IMPACT_CRITICAL
            elif is_cp and rtype == "critical_delay":
                impact = IMPACT_CRITICAL
            elif rtype == "blocked":
                impact = IMPACT_HIGH
            elif is_cp:
                impact = IMPACT_HIGH
            elif rtype == "delay":
                impact = IMPACT_MEDIUM
            else:
                impact = IMPACT_LOW

            self.all_risks.append({
                "id":           f"risk_{rid:03d}",
                "type":         "schedule",
                "phase":        phase,
                "critical_path": is_cp,
                "status":       rtype,
                "impact":       impact,
                "impact_days":  impact_d,
                "reason":       reason,
                "source":       "live_delay_risks",
            })

        # ── Риски из финансов ────────────────────────────────────────────────
        for cr in self.cash_gap_risks:
            rid += 1
            gap_mln   = cr.get("gap_mln", 0)
            gap_abs   = gap_mln * 1_000_000
            severity  = cr.get("severity","")

            if gap_abs <= CASH_GAP_CRITICAL or severity == "critical":
                impact = IMPACT_CRITICAL
            elif gap_abs <= CASH_GAP_HIGH or severity == "risk":
                impact = IMPACT_HIGH
            else:
                impact = IMPACT_MEDIUM

            self.all_risks.append({
                "id":     f"risk_{rid:03d}",
                "type":   "finance",
                "month":  cr.get("month",""),
                "gap":    gap_mln,
                "impact": impact,
                "severity": severity,
                "source": "cash_gap_risks",
            })

        # Сортируем: CRITICAL → HIGH → MEDIUM
        order = {IMPACT_CRITICAL: 0, IMPACT_HIGH: 1,
                 IMPACT_MEDIUM: 2, IMPACT_LOW: 3}
        self.all_risks.sort(key=lambda r: (
            order.get(r["impact"], 4),
            -abs(r.get("impact_days", 0) or r.get("gap", 0) or 0)
        ))

        # Счётчики
        for r in self.all_risks:
            self.counters[r["impact"]] = self.counters.get(r["impact"], 0) + 1

        # Top problem
        critical = [r for r in self.all_risks if r["impact"] == IMPACT_CRITICAL]
        if critical:
            c = critical[0]
            self.top_problem = {
                "type":   c["type"],
                "phase":  c.get("phase",""),
                "month":  c.get("month",""),
                "value":  c.get("gap", c.get("impact_days",0)),
                "impact": c["impact"],
                "reason": c.get("reason",""),
            }

        print(f"[Decision]   Всего рисков: {len(self.all_risks)}")
        print(f"[Decision]   CRITICAL:{self.counters['CRITICAL']} "
              f"HIGH:{self.counters['HIGH']} "
              f"MEDIUM:{self.counters['MEDIUM']}")

    # ── Генерация действий (rule-based) ──────────────────────────────────────

    def generate_actions(self):
        print("[Decision] Генерирую рекомендации (rule-based)...")
        prio = 0
        seen = set()  # дедупликация

        def add(category, action, reason, effect, atype):
            nonlocal prio
            key = f"{atype}:{action[:40]}"
            if key in seen:
                return
            seen.add(key)
            prio += 1
            self.actions.append({
                "priority":        prio,
                "category":        category,
                "action":          action,
                "reason":          reason,
                "expected_effect": effect,
                "type":            atype,
            })

        # ── ПРАВИЛО 1: блокировка на критическом пути ────────────────────────
        for r in self.all_risks:
            if r["type"] == "schedule" and r["status"] == "blocked" \
                    and r["critical_path"]:
                add(IMPACT_CRITICAL,
                    f"Устранить блокировку: {r['phase']}",
                    f"Фаза на критическом пути — {r.get('reason','')}",
                    "Снижение риска срыва сроков проекта",
                    "schedule")

        # ── ПРАВИЛО 2: кассовый разрыв > 200 млн ─────────────────────────────
        for r in self.all_risks:
            if r["type"] == "finance" and r["impact"] == IMPACT_CRITICAL:
                gap_mln = abs(r.get("gap", 0))
                add(IMPACT_CRITICAL,
                    f"Ускорить финансирование: {r['month']} "
                    f"(разрыв {gap_mln:.1f} млн тг)",
                    "Критический кассовый разрыв",
                    "Стабилизация закупок и оплаты подрядчиков",
                    "finance")

        # ── ПРАВИЛО 3: нехватка рабочих ──────────────────────────────────────
        for r in self.all_risks:
            reason = r.get("reason","").lower()
            if r["type"] == "schedule" and ("рабоч" in reason or "бригад" in reason):
                add(IMPACT_HIGH,
                    f"Увеличить бригаду на фазе: {r['phase']}",
                    r.get("reason",""),
                    "Ускорение выполнения отстающей фазы",
                    "schedule")
                add(IMPACT_HIGH,
                    f"Рассмотреть вторую смену: {r['phase']}",
                    "Отставание из-за нехватки персонала",
                    "Сокращение отставания без увеличения фронта работ",
                    "schedule")

        # ── ПРАВИЛО 4: задержка на критическом пути ──────────────────────────
        for r in self.all_risks:
            if r["type"] == "schedule" and r["critical_path"] \
                    and r["status"] in ("critical_delay", "delayed") \
                    and r["impact"] in (IMPACT_CRITICAL, IMPACT_HIGH):
                add(IMPACT_HIGH,
                    f"Увеличить сменность: {r['phase']}",
                    f"Критический путь, отставание {r.get('impact_days',0)} дн.",
                    "Снижение задержки проекта",
                    "schedule")

        # ── ПРАВИЛО 5: кассовый разрыв HIGH ──────────────────────────────────
        for r in self.all_risks:
            if r["type"] == "finance" and r["impact"] == IMPACT_HIGH:
                add(IMPACT_HIGH,
                    f"Перенести часть закупок: {r['month']}",
                    "Снижение пиковой нагрузки на финансирование",
                    "Сокращение кассового разрыва",
                    "finance")

        # ── ПРАВИЛО 6: некритичные отставания ────────────────────────────────
        medium_sched = [r for r in self.all_risks
                        if r["type"] == "schedule"
                        and not r["critical_path"]
                        and r["impact"] == IMPACT_MEDIUM]
        if medium_sched:
            phases = [r["phase"] for r in medium_sched[:3]]
            add(IMPACT_MEDIUM,
                "Усилить мониторинг некритичных фаз",
                f"Отставание на: {', '.join(phases)}",
                "Своевременное обнаружение нарастания задержек",
                "schedule")

        # ── ПРАВИЛО 7: нет рисков ────────────────────────────────────────────
        if not self.all_risks:
            add(IMPACT_LOW,
                "Продолжать плановый мониторинг",
                "Проект идёт в штатном режиме",
                "Поддержание текущего темпа",
                "monitor")

        print(f"[Decision]   Рекомендаций: {len(self.actions)}")

    # ── Общий статус ─────────────────────────────────────────────────────────

    def overall_status(self) -> str:
        if self.counters.get("CRITICAL", 0) > 0:
            return "CRITICAL"
        if self.counters.get("HIGH", 0) > 0:
            return "RISK"
        if self.counters.get("MEDIUM", 0) > 0:
            return "WARNING"
        return "OK"

    # ── Сохранение ───────────────────────────────────────────────────────────

    def save(self):
        status = self.overall_status()
        fin_s  = self.finance_summary
        gpr_s  = self.gpr_summary

        # 1. decision_summary.json
        self._save_json({
            "engine_version":  "1.0",
            "project":         "Школа №65, Уральск",
            "date":            self.report_date,
            "overall_status":  status,
            "critical_issues": self.counters.get("CRITICAL", 0),
            "high_issues":     self.counters.get("HIGH", 0),
            "medium_issues":   self.counters.get("MEDIUM", 0),
            "total_risks":     len(self.all_risks),
            "total_actions":   len(self.actions),
            "top_problem":     self.top_problem,
            "schedule_impact": gpr_s.get("schedule_impact", {}),
            "finance_impact": {
                "delta_mln":       fin_s.get("delta_total_mln", 0),
                "peak_gap_mln":    fin_s.get("peak_cash_gap_mln", 0),
                "peak_gap_month":  fin_s.get("peak_gap_month", ""),
                "finance_status":  fin_s.get("status", ""),
            },
        }, "decision_summary.json")

        # 2. top_risks.json
        self._save_json({
            "engine_version": "1.0",
            "report_date":    self.report_date,
            "risks_count":    len(self.all_risks),
            "risks":          self.all_risks[:20],
        }, "top_risks.json")

        # 3. recommended_actions.json
        self._save_json({
            "engine_version": "1.0",
            "report_date":    self.report_date,
            "actions_count":  len(self.actions),
            "actions":        self.actions,
        }, "recommended_actions.json")

        # 4. HTML
        self._build_html(status)
        self._print_summary(status)

    def _build_html(self, status: str):
        STATUS_COLOR = {"OK":"#1D9E75","WARNING":"#EF9F27",
                        "RISK":"#BA7517","CRITICAL":"#E24B4A"}
        STATUS_ICON  = {"OK":"✅","WARNING":"⚠️","RISK":"🔴","CRITICAL":"🚨"}
        IMPACT_COLOR = {"CRITICAL":"#E24B4A","HIGH":"#BA7517",
                        "MEDIUM":"#EF9F27","LOW":"#B4B2A9"}
        TYPE_ICON    = {"schedule":"📅","finance":"💰","monitor":"👁"}

        sc = STATUS_COLOR.get(status,"#888")
        si = STATUS_ICON.get(status,"")

        # Топ-3 проблемы
        top3 = self.all_risks[:3]
        top3_html = ""
        for r in top3:
            ic = IMPACT_COLOR.get(r["impact"],"#888")
            if r["type"] == "schedule":
                desc = f"{r['phase']} — {r.get('reason','')}"
                sub  = f"Задержка {r.get('impact_days',0)} дн."
            else:
                desc = f"Кассовый разрыв {r.get('month','')} — {r.get('gap',0):+.1f} млн тг"
                sub  = r.get("severity","")
            top3_html += f"""
      <div style="background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;
                  padding:12px 16px;margin-bottom:10px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
          <span style="background:{ic};color:#fff;font-size:11px;padding:2px 8px;
                       border-radius:3px;flex-shrink:0;">{r['impact']}</span>
          <span style="font-size:13px;font-weight:500;">{desc}</span>
        </div>
        <div style="font-size:12px;color:#888;">{sub}</div>
      </div>"""

        # Таблица действий
        act_rows = ""
        for a in self.actions:
            ic = IMPACT_COLOR.get(a["category"],"#888")
            ti = TYPE_ICON.get(a["type"],"")
            act_rows += f"""
      <tr>
        <td style="padding:8px 10px;font-size:13px;font-weight:500;
                   border-bottom:0.5px solid #eee;">{a['priority']}</td>
        <td style="padding:8px 8px;border-bottom:0.5px solid #eee;">
          <span style="background:{ic};color:#fff;font-size:11px;
                       padding:2px 7px;border-radius:3px;">{a['category']}</span>
        </td>
        <td style="padding:8px 10px;font-size:13px;border-bottom:0.5px solid #eee;">
          {ti} {a['action']}</td>
        <td style="padding:8px 10px;font-size:12px;color:#666;
                   border-bottom:0.5px solid #eee;">{a['reason']}</td>
        <td style="padding:8px 10px;font-size:12px;color:#1D9E75;
                   border-bottom:0.5px solid #eee;">{a['expected_effect']}</td>
      </tr>"""

        # Сводка по срокам и финансам
        gpr_s = self.gpr_summary
        fin_s = self.finance_summary
        si_data = gpr_s.get("schedule_impact",{})
        delay_d = si_data.get("delay_days",0)
        delay_color = "#E24B4A" if delay_d > 0 else "#1D9E75"
        delta_mln = fin_s.get("delta_total_mln", 0)
        fin_color = "#E24B4A" if delta_mln < 0 else "#1D9E75"

        html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Decision Report — AINTELLECTUM</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:#fafafa;color:#1a1a1a;padding:24px}}
h1{{font-size:18px;font-weight:500;margin-bottom:4px}}
.sub{{font-size:13px;color:#888;margin-bottom:20px}}
.status-banner{{background:#fff;border:2px solid {sc};border-radius:10px;
               padding:16px 20px;margin-bottom:20px;
               display:flex;align-items:center;gap:12px}}
.status-label{{font-size:22px;font-weight:500;color:{sc}}}
.status-sub{{font-size:13px;color:#888;margin-top:2px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}}
.card{{background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;padding:12px 16px}}
.cl{{font-size:11px;color:#999;margin-bottom:4px}}
.cv{{font-size:20px;font-weight:500}}
h2{{font-size:15px;font-weight:500;margin:20px 0 12px}}
table{{width:100%;border-collapse:collapse;background:#fff;
       border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:24px}}
thead tr{{background:#f5f5f5}}
th{{padding:8px 10px;font-size:12px;font-weight:500;text-align:left;
    border-bottom:0.5px solid #e0e0e0}}
tr:hover{{background:#fafafa}}
.footer{{font-size:11px;color:#bbb;text-align:right;margin-top:16px}}
</style></head><body>
<h1>Decision Report — Школа №65, Уральск</h1>
<div class="sub">AINTELLECTUM · Decision Engine v1.0 · {self.report_date}</div>

<div class="status-banner">
  <span style="font-size:32px">{si}</span>
  <div>
    <div class="status-label">{status}</div>
    <div class="status-sub">
      Критических: {self.counters.get("CRITICAL",0)} &nbsp;|&nbsp;
      Высоких: {self.counters.get("HIGH",0)} &nbsp;|&nbsp;
      Средних: {self.counters.get("MEDIUM",0)} &nbsp;|&nbsp;
      Рекомендаций: {len(self.actions)}
    </div>
  </div>
</div>

<div class="cards">
  <div class="card"><div class="cl">Сдвиг сроков</div>
    <div class="cv" style="color:{delay_color}">
      {f"+{delay_d} дн." if delay_d>0 else f"{delay_d} дн." if delay_d<0 else "по плану"}</div></div>
  <div class="card"><div class="cl">Финансовое отклонение</div>
    <div class="cv" style="color:{fin_color}">{delta_mln:+.1f} млн тг</div></div>
  <div class="card"><div class="cl">Пиковый разрыв</div>
    <div class="cv" style="color:#E24B4A">
      {fin_s.get("peak_cash_gap_mln",0):+.1f} млн тг</div></div>
  <div class="card"><div class="cl">Финстатус</div>
    <div class="cv">{fin_s.get("status","—").upper()}</div></div>
</div>

<h2>Топ-{min(3,len(top3))} проблемы</h2>
{top3_html if top3_html else '<p style="color:#888;font-size:13px">Критических проблем не обнаружено ✅</p>'}

<h2>Рекомендованные действия</h2>
<table>
  <thead><tr><th>#</th><th>Приоритет</th><th>Действие</th>
    <th>Причина</th><th>Ожидаемый эффект</th></tr></thead>
  <tbody>{act_rows if act_rows else '<tr><td colspan="5" style="padding:10px;color:#888">Нет рекомендаций</td></tr>'}</tbody>
</table>

<div class="footer">AINTELLECTUM Decision Engine v1.0 · Ереке · Аян · Claude</div>
</body></html>"""

        with open("decision_report.html","w",encoding="utf-8") as f:
            f.write(html)
        sz = Path("decision_report.html").stat().st_size
        print(f"[Decision] ✅ decision_report.html ({sz//1024} КБ) → открой в браузере")

    def _save_json(self, data, path):
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Decision] ✅ {path} ({Path(path).stat().st_size//1024} КБ)")

    def _print_summary(self, status: str):
        STATUS_ICONS = {"OK":"✅","WARNING":"⚠️","RISK":"🔴","CRITICAL":"🚨"}
        print()
        print("="*65)
        print("  DECISION ENGINE v1.0 — РЕЗУЛЬТАТ")
        print("="*65)
        print(f"  Дата отчёта:     {self.report_date}")
        print(f"  Общий статус:    {status} {STATUS_ICONS.get(status,'')}")
        print(f"  Рисков CRITICAL: {self.counters.get('CRITICAL',0)}")
        print(f"  Рисков HIGH:     {self.counters.get('HIGH',0)}")
        print(f"  Рисков MEDIUM:   {self.counters.get('MEDIUM',0)}")
        print()
        print("  ТОП РЕКОМЕНДАЦИИ:")
        for a in self.actions[:5]:
            icon = {"CRITICAL":"🚨","HIGH":"🔴","MEDIUM":"⚠️","LOW":"ℹ️"}.get(a["category"],"")
            print(f"  {a['priority']}. {icon} [{a['category']}] {a['action']}")
            print(f"     → {a['expected_effect']}")
        print()
        if self.top_problem:
            tp = self.top_problem
            print(f"  Главная проблема: {tp.get('type','').upper()}")
            if tp.get("phase"):
                print(f"    Фаза: {tp['phase']}")
            if tp.get("month"):
                print(f"    Месяц: {tp['month']}")
            print(f"    Причина: {tp.get('reason','')}")
        print()
        print("  Файлы: decision_summary.json · recommended_actions.json")
        print("         top_risks.json · decision_report.html")
        print("="*65)

    def run(self):
        self.load()
        self.collect_risks()
        self.generate_actions()
        self.save()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AINTELLECTUM Decision Engine v1.0")
    p.add_argument("--date", default=date.today().isoformat())
    args = p.parse_args()

    print("="*65)
    print("  DECISION ENGINE v1.0 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  риски + отклонения = управленческие решения")
    print("="*65); print()

    engine = DecisionEngine(args.date)
    engine.run()