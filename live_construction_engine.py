# -*- coding: utf-8 -*-
"""
Live Construction Engine v1.1
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

ИЗМЕНЕНИЯ v1.1 vs v1.0:
  - Корректная логика completed (actual_start/finish)
  - Коррекция remaining по ресурсам (actual vs planned workers)
  - Расширенные статусы (delayed вычисляется автоматически)
  - live_vs_baseline.json — сравнение план/факт
  - live_gantt_chart.html — двойная визуализация baseline+live
  - 3 тестовых сценария (--test on_track / delayed / ahead)

ИСПОЛЬЗОВАНИЕ:
  python live_construction_engine.py
  python live_construction_engine.py --progress daily_progress.json
  python live_construction_engine.py --test delayed
"""

import json
import argparse
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict, deque


# ─── Константы ───────────────────────────────────────────────────────────────
DELAY_TOLERANCE_PCT = 10
BLOCK_FACTOR        = 1.5
MAX_PERF_FACTOR     = 2.5


# ─── Тестовые сценарии ───────────────────────────────────────────────────────

def make_test_progress(gpr_tasks: list, scenario: str, report_date: str) -> dict:
    """3 сценария: on_track / delayed / ahead"""
    rdate   = date.fromisoformat(report_date)
    updates = []

    factors = {
        "on_track": 1.0,
        "delayed":  0.5,
        "ahead":    1.3,
    }
    factor = factors.get(scenario, 1.0)

    for task in gpr_tasks:
        tid    = task.get("task_id", "")
        start  = date.fromisoformat(task["start_date"]) if task.get("start_date") else None
        finish = date.fromisoformat(task["finish_date"]) if task.get("finish_date") else None
        if not start or not tid:
            continue

        duration = max((finish - start).days, 1) if finish else 30

        if rdate < start:
            continue

        if finish and rdate > finish:
            if scenario == "delayed":
                # Некоторые задачи не завершены вовремя
                import hashlib
                h = int(hashlib.md5(tid.encode()).hexdigest(), 16)
                if h % 3 == 0:
                    updates.append({
                        "task_id": tid, "status": "in_progress",
                        "progress_pct": 80,
                        "actual_start": start.isoformat(),
                        "actual_finish": None,
                        "actual_workers": 10, "planned_workers": 20,
                        "comment": "Отставание"
                    })
                    continue
            updates.append({
                "task_id": tid, "status": "completed",
                "progress_pct": 100,
                "actual_start":  start.isoformat(),
                "actual_finish": finish.isoformat(),
            })
        else:
            elapsed  = (rdate - start).days
            planned  = min(100, elapsed / duration * 100)
            actual   = min(100, planned * factor)
            workers_plan = 20
            workers_act  = int(workers_plan * factor)

            status = "blocked" if (scenario == "delayed" and actual < 10 and elapsed > 5) \
                     else "in_progress"
            entry = {
                "task_id": tid, "status": status,
                "progress_pct": round(actual, 1),
                "actual_start": start.isoformat(),
                "actual_finish": None,
                "actual_workers": workers_act,
                "planned_workers": workers_plan,
            }
            if status == "blocked":
                entry["block_reason"] = "Задержка поставки материалов"
            updates.append(entry)

    return {
        "project":     "Школа №65, Уральск",
        "report_date": report_date,
        "updates":     updates,
    }


# ─── Вспомогательные ─────────────────────────────────────────────────────────

def parse_date(s):
    return date.fromisoformat(s) if s else date(2025, 1, 1)


def topo_sort(tasks: dict, deps: dict) -> list:
    in_deg = {t: 0 for t in tasks}
    succ   = defaultdict(list)
    for t, ds in deps.items():
        for d in ds:
            if d in tasks:
                in_deg[t] += 1
                succ[d].append(t)
    q = deque(t for t, d in in_deg.items() if d == 0)
    out = []
    while q:
        t = q.popleft()
        out.append(t)
        for s in succ[t]:
            in_deg[s] -= 1
            if in_deg[s] == 0:
                q.append(s)
    for t in tasks:
        if t not in out:
            out.append(t)
    return out


# ─── Основной класс ──────────────────────────────────────────────────────────

class LiveConstructionEngineV11:

    def __init__(self, gpr_path, cp_path, progress_path, report_date):
        self.gpr_path       = gpr_path
        self.cp_path        = cp_path
        self.progress_path  = progress_path
        self.report_date    = report_date
        self.rdate          = parse_date(report_date)

        self.baseline   = {}   # tid → task
        self.deps       = {}   # tid → [dep_tids]
        self.baseline_cp = []
        self.prog_map   = {}   # tid → update
        self.live       = {}   # tid → live task
        self.live_cp    = []
        self.risks      = []
        self.project_name = "Школа №65, Уральск"
        self.project_start = date(2025, 1, 1)

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def load_inputs(self):
        print(f"[Live] Читаю {self.gpr_path}...")
        with open(self.gpr_path, encoding="utf-8") as f:
            gpr = json.load(f)
        self.project_name  = gpr.get("project", self.project_name)
        self.project_start = parse_date(gpr.get("project_start_date",
                                                  gpr.get("start_date","2025-01-01")))
        for task in gpr.get("tasks", []):
            tid = task.get("task_id","")
            if not tid:
                continue
            self.baseline[tid] = dict(task)
            preds = task.get("predecessors", [])
            self.deps[tid] = [p for p in (preds if isinstance(preds,list) else [])
                              if p] if preds else []

        try:
            with open(self.cp_path, encoding="utf-8") as f:
                cp = json.load(f)
            self.baseline_cp = [t.get("task_id","") for t in cp.get("critical_tasks",[])]
        except Exception:
            self.baseline_cp = []

        print(f"[Live] Baseline задач: {len(self.baseline)}")

        if Path(self.progress_path).exists():
            with open(self.progress_path, encoding="utf-8") as f:
                prog = json.load(f)
            rd = prog.get("report_date", prog.get("date",""))
            if rd:
                self.report_date = rd
                self.rdate = parse_date(rd)
            for u in prog.get("updates", []):
                self.prog_map[u["task_id"]] = u
            print(f"[Live] Обновлений: {len(self.prog_map)}  |  Дата: {self.report_date}")
        else:
            print(f"[Live] Прогресс не найден: {self.progress_path}")

    # ── Логика статуса ───────────────────────────────────────────────────────

    def _planned_pct(self, task: dict) -> float:
        s = parse_date(task.get("start_date","2025-01-01"))
        f = parse_date(task.get("finish_date","2025-01-01"))
        if self.rdate < s:
            return 0.0
        if self.rdate >= f:
            return 100.0
        return min(100.0, (self.rdate - s).days / max((f - s).days, 1) * 100)

    def _live_status(self, task: dict, upd) -> str:
        planned = self._planned_pct(task)
        s_date  = parse_date(task.get("start_date",""))
        if upd is None:
            if planned == 0:
                return "not_started"
            return "not_updated"
        status = upd.get("status","in_progress")
        actual = float(upd.get("progress_pct", 0))
        if status == "completed" or actual >= 100:
            return "completed"
        if status == "blocked":
            return "blocked"
        if planned == 0 and self.rdate > s_date:
            return "delayed"
        if planned - actual > DELAY_TOLERANCE_PCT:
            return "delayed"
        if actual > planned + DELAY_TOLERANCE_PCT:
            return "ahead"
        return "on_track"

    def _remaining(self, task: dict, live_status: str, upd) -> int:
        dur     = max(task.get("duration_days", 1), 1)
        planned = self._planned_pct(task)
        actual  = float(upd.get("progress_pct", 0)) if upd else 0.0
        base_rem = max(0, int(dur * (1 - planned / 100)))

        if live_status == "completed":
            return 0
        if live_status in ("not_started", "not_updated"):
            return dur
        if live_status == "blocked":
            return int(base_rem * BLOCK_FACTOR)
        if live_status == "ahead":
            factor = planned / max(actual, 1)
            return max(1, int(base_rem * factor))
        if live_status == "delayed":
            # Коррекция по ресурсам
            pw = upd.get("planned_workers", 0) if upd else 0
            aw = upd.get("actual_workers", 0) if upd else 0
            perf_factor = planned / max(actual, 1)
            if pw > 0 and aw > 0 and aw < pw:
                res_factor = pw / aw
                perf_factor = min(MAX_PERF_FACTOR, max(perf_factor, res_factor))
            else:
                perf_factor = min(MAX_PERF_FACTOR, perf_factor)
            return max(1, int(base_rem * perf_factor))
        # on_track
        return base_rem

    # ── Перестройка графика ───────────────────────────────────────────────────

    def rebuild(self):
        print(f"[Live] Перестраиваю live-расписание...")

        # Инициализация
        for tid, task in self.baseline.items():
            upd    = self.prog_map.get(tid)
            status = self._live_status(task, upd)
            rem    = self._remaining(task, status, upd)
            planned_pct = self._planned_pct(task)
            actual_pct  = float(upd.get("progress_pct",0)) if upd else 0.0

            self.live[tid] = {
                "task_id":             tid,
                "phase":               task.get("phase",""),
                "baseline_start":      task.get("start_date"),
                "baseline_finish":     task.get("finish_date"),
                "baseline_duration":   task.get("duration_days",0),
                "planned_progress_pct": round(planned_pct, 1),
                "actual_progress_pct":  round(actual_pct, 1),
                "live_status":          status,
                "remaining_days":       rem,
                "actual_workers":       (upd or {}).get("actual_workers"),
                "planned_workers":      (upd or {}).get("planned_workers"),
                "block_reason":         (upd or {}).get("block_reason"),
                "comment":              (upd or {}).get("comment"),
                "actual_start":         (upd or {}).get("actual_start"),
                "actual_finish":        (upd or {}).get("actual_finish"),
                "live_start":           None,
                "live_finish":          None,
                "live_duration":        rem,
                "delay_days":           0,
                "is_live_critical":     False,
                "dependencies":         self.deps.get(tid, []),
            }

        # Forward pass
        order = topo_sort(self.live, self.deps)
        finish_map = {}

        for tid in order:
            lt   = self.live[tid]
            deps = [d for d in self.deps.get(tid,[]) if d in self.live]

            if lt["live_status"] == "completed":
                # Используем actual_finish если есть, иначе baseline
                af = lt.get("actual_finish") or lt["baseline_finish"]
                live_start  = parse_date(lt.get("actual_start") or lt["baseline_start"] or "2025-01-01")
                live_finish = parse_date(af or "2025-01-01")
            else:
                if deps:
                    dep_f = [finish_map.get(d, parse_date(
                        self.baseline.get(d,{}).get("finish_date","2025-01-01")
                    )) for d in deps]
                    live_start = max(dep_f)
                else:
                    live_start = parse_date(lt["baseline_start"] or "2025-01-01")
                live_finish = live_start + timedelta(days=lt["remaining_days"])

            baseline_finish = parse_date(lt["baseline_finish"] or "2025-01-01")
            delay = max(0, (live_finish - baseline_finish).days)

            lt["live_start"]   = live_start.isoformat()
            lt["live_finish"]  = live_finish.isoformat()
            lt["live_duration"]= lt["remaining_days"]
            lt["delay_days"]   = delay
            finish_map[tid]    = live_finish

    # ── Live CPM ─────────────────────────────────────────────────────────────

    def run_cpm(self):
        print(f"[Live] Live CPM...")
        order = topo_sort(self.live, self.deps)

        ef = {}  # early finish
        es = {}  # early start
        for tid in order:
            lt   = self.live[tid]
            deps = [d for d in self.deps.get(tid,[]) if d in self.live]
            e_s  = max((ef.get(d,0) for d in deps), default=0)
            es[tid] = e_s
            ef[tid] = e_s + max(lt["live_duration"], 0)

        proj_end = max(ef.values()) if ef else 0
        succ = defaultdict(list)
        for tid, ds in self.deps.items():
            for d in ds:
                if d in self.live:
                    succ[d].append(tid)

        lf = {}
        ls = {}
        for tid in reversed(order):
            lt    = self.live[tid]
            my_s  = [s for s in succ[tid] if s in self.live]
            lf[tid] = min((ls.get(s, proj_end) for s in my_s), default=proj_end)
            ls[tid] = lf[tid] - max(lt["live_duration"], 0)

        self.live_cp = []
        for tid, lt in self.live.items():
            flt = max(0, ls[tid] - es[tid])
            lt["live_float"] = flt
            is_cp = (flt == 0 and lt["live_duration"] > 0)
            lt["is_live_critical"] = is_cp
            if is_cp:
                self.live_cp.append(tid)

        self.live_cp.sort(key=lambda t: es.get(t,0))
        print(f"[Live] Критический путь: {len(self.live_cp)} задач")

    # ── Риски ────────────────────────────────────────────────────────────────

    def build_risks(self):
        self.risks = []
        for tid, lt in self.live.items():
            rtype = None
            reason = None
            if lt["live_status"] == "blocked":
                rtype  = "blocked"
                reason = lt.get("block_reason") or "Причина не указана"
            elif lt["live_status"] == "delayed" and lt["is_live_critical"]:
                rtype  = "critical_delay"
                reason = f"Крит. путь, отставание {lt['delay_days']} дн."
            elif lt["live_status"] == "delayed":
                rtype  = "delay"
                gap    = lt["planned_progress_pct"] - lt["actual_progress_pct"]
                reason = f"Отстаём на {round(gap,1)}%"
                # Ресурсы
                pw = lt.get("planned_workers") or 0
                aw = lt.get("actual_workers") or 0
                if pw > 0 and aw > 0 and aw < pw:
                    reason += f" (рабочих {aw}/{pw})"
            elif lt["live_status"] == "not_updated" and lt["is_live_critical"]:
                rtype  = "no_data_critical"
                reason = "Нет данных на крит. задаче"

            if rtype:
                self.risks.append({
                    "task_id":     tid,
                    "phase":       lt["phase"],
                    "risk_type":   rtype,
                    "reason":      reason,
                    "impact_days": lt["delay_days"],
                    "is_critical": lt["is_live_critical"],
                    "recommendation": self._rec(lt, rtype),
                })
        self.risks.sort(key=lambda r: (-r["is_critical"], -r["impact_days"]))

    def _rec(self, lt: dict, rtype: str) -> str:
        pw = lt.get("planned_workers") or 0
        aw = lt.get("actual_workers") or 0
        if rtype == "blocked":
            return f"Устранить блокировку: {lt.get('block_reason','')}"
        if rtype == "critical_delay":
            if pw > 0 and aw < pw:
                return f"Увеличить рабочую силу: {aw} → {pw} чел."
            return "Увеличить сменность на критической задаче"
        if rtype == "delay":
            if pw > 0 and aw < pw:
                return f"Усилить бригаду: {aw} → {pw} чел."
            return "Проверить организацию работ"
        return "Обновить данные о прогрессе"

    # ── Сохранение ───────────────────────────────────────────────────────────

    def save(self):
        tasks_list = sorted(self.live.values(),
                            key=lambda t: t.get("live_start",""))
        lf = [parse_date(t["live_finish"]) for t in tasks_list if t.get("live_finish")]
        bf = [parse_date(t["baseline_finish"]) for t in tasks_list if t.get("baseline_finish")]
        live_fin = max(lf).isoformat() if lf else "—"
        base_fin = max(bf).isoformat() if bf else "—"
        total_delay = (parse_date(live_fin)-parse_date(base_fin)).days \
                      if live_fin!="—" and base_fin!="—" else 0
        statuses = [t["live_status"] for t in tasks_list]
        stat = {s: statuses.count(s) for s in set(statuses)}
        cp_changed = set(self.live_cp) != set(self.baseline_cp)
        recs = list(dict.fromkeys(r["recommendation"] for r in self.risks[:5]))
        if not recs:
            recs = ["Проект идёт по плану — продолжать мониторинг"]

        # 1. live_gpr_schedule.json
        self._save_json({"engine_version":"1.1","project":self.project_name,
                         "report_date":self.report_date,
                         "live_finish":live_fin,"baseline_finish":base_fin,
                         "total_delay_days":total_delay,"tasks":tasks_list},
                        "live_gpr_schedule.json")

        # 2. live_gpr_summary.json
        self._save_json({"engine_version":"1.1","project":self.project_name,
                         "report_date":self.report_date,
                         "summary":{"total_tasks":len(tasks_list),**stat},
                         "schedule_impact":{"baseline_finish":base_fin,
                                            "live_finish":live_fin,
                                            "delay_days":total_delay},
                         "critical_path_changed":cp_changed,
                         "live_critical_path":self.live_cp,
                         "top_risks":[r["reason"] for r in self.risks[:5]],
                         "recommended_actions":recs},
                        "live_gpr_summary.json")

        # 3. live_delay_risks.json
        self._save_json({"engine_version":"1.1","report_date":self.report_date,
                         "risks_count":len(self.risks),"risks":self.risks},
                        "live_delay_risks.json")

        # 4. live_vs_baseline.json
        vb = []
        for t in tasks_list:
            vb.append({"task_id":t["task_id"],"phase":t["phase"],
                       "baseline_start":t["baseline_start"],
                       "baseline_finish":t["baseline_finish"],
                       "baseline_duration":t["baseline_duration"],
                       "live_start":t["live_start"],
                       "live_finish":t["live_finish"],
                       "delay_days":t["delay_days"],
                       "status":t["live_status"],
                       "progress_planned":t["planned_progress_pct"],
                       "progress_actual":t["actual_progress_pct"],
                       "is_critical":t["is_live_critical"]})
        self._save_json({"engine_version":"1.1","report_date":self.report_date,
                         "items":vb}, "live_vs_baseline.json")

        # 5. HTML
        self._build_html(tasks_list, base_fin, live_fin, total_delay, stat, recs)
        self._print_summary(stat, base_fin, live_fin, total_delay, cp_changed, recs)

    def _build_html(self, tasks, base_fin, live_fin, total_delay, stat, recs):
        all_dates = []
        for t in tasks:
            for f in ["baseline_start","baseline_finish","live_start","live_finish"]:
                if t.get(f):
                    all_dates.append(parse_date(t[f]))
        if not all_dates:
            return
        proj_s = min(all_dates)
        proj_e = max(all_dates)
        total_span = max((proj_e - proj_s).days, 1)

        COLORS = {"completed":"#1D9E75","on_track":"#378ADD",
                  "delayed":"#BA7517","blocked":"#2C2C2A",
                  "ahead":"#639922","not_started":"#B4B2A9",
                  "not_updated":"#B4B2A9"}

        rows = ""
        for t in tasks:
            bs = parse_date(t["baseline_start"]) if t.get("baseline_start") else proj_s
            bf = parse_date(t["baseline_finish"]) if t.get("baseline_finish") else proj_s
            ls = parse_date(t["live_start"]) if t.get("live_start") else bs
            lf = parse_date(t["live_finish"]) if t.get("live_finish") else bf

            bl   = round((bs-proj_s).days/total_span*100, 2)
            bw   = max(round((bf-bs).days/total_span*100, 2), 0.3)
            ll   = round((ls-proj_s).days/total_span*100, 2)
            lw   = max(round((lf-ls).days/total_span*100, 2), 0.3)
            color = COLORS.get(t["live_status"], "#888")
            cp_b = '<span style="background:#E24B4A;color:#fff;font-size:10px;padding:1px 4px;border-radius:3px;margin-left:3px">КП</span>' \
                   if t["is_live_critical"] else ""
            delay_b = f'<span style="font-size:10px;color:#BA7517;margin-left:3px">+{t["delay_days"]}д</span>' \
                      if t["delay_days"] > 0 else ""
            prog = t["actual_progress_pct"]

            tooltip = (f"Фаза: {t['phase']}&#10;"
                       f"Статус: {t['live_status']}&#10;"
                       f"План: {t['planned_progress_pct']}%  Факт: {prog}%&#10;"
                       f"Baseline: {t['baseline_start']} → {t['baseline_finish']}&#10;"
                       f"Live:     {t['live_start']} → {t['live_finish']}&#10;"
                       f"Задержка: +{t['delay_days']} дн.")
            if t.get("comment"):
                tooltip += f"&#10;{t['comment']}"

            rows += f"""
      <tr title="{tooltip}">
        <td style="padding:5px 10px;font-size:12px;white-space:nowrap;
                   border-bottom:0.5px solid #eee;max-width:200px;">
          {t['phase'][:28]}{cp_b}{delay_b}</td>
        <td style="padding:5px 8px;font-size:11px;color:#777;
                   border-bottom:0.5px solid #eee;">{t['live_status']}</td>
        <td style="padding:5px 8px;font-size:11px;text-align:right;
                   border-bottom:0.5px solid #eee;">{prog}%</td>
        <td style="padding:4px 8px;border-bottom:0.5px solid #eee;min-width:400px;">
          <div style="position:relative;height:32px;">
            <div style="position:absolute;top:2px;left:{bl}%;width:{bw}%;
                        height:12px;background:#D3D1C7;border-radius:2px;
                        min-width:2px;" title="Baseline"></div>
            <div style="position:absolute;top:16px;left:{ll}%;width:{lw}%;
                        height:12px;background:{color};border-radius:2px;
                        min-width:2px;" title="Live"></div>
            <div style="position:absolute;top:2px;left:{bl}%;height:28px;
                        width:{max(lw,bw)}%;overflow:hidden;">
              <div style="position:absolute;top:0;left:0;width:{prog}%;
                          height:12px;background:rgba(255,255,255,0.35);
                          border-radius:2px;"></div>
            </div>
          </div>
        </td>
      </tr>"""

        # Легенда
        legend = "".join(
            f'<span style="display:flex;align-items:center;gap:4px;">'
            f'<span style="width:12px;height:12px;border-radius:2px;background:{c}"></span>'
            f'<span style="font-size:12px;color:var(--color-text-secondary,#666)">{s}</span></span>'
            for s, c in [("on_track","#378ADD"),("delayed","#BA7517"),
                         ("blocked","#2C2C2A"),("completed","#1D9E75"),
                         ("ahead","#639922")]
        )

        delay_str = (f"+{total_delay} дн." if total_delay > 0
                     else f"−{abs(total_delay)} дн. (опережение)" if total_delay < 0
                     else "по плану")
        recs_html = "".join(f'<li style="font-size:13px;margin-bottom:4px">{r}</li>'
                             for r in recs)

        html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Live ГПР — AINTELLECTUM</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:#fafafa;color:#1a1a1a;padding:24px}}
h1{{font-size:18px;font-weight:500;margin-bottom:4px}}
.sub{{font-size:13px;color:#888;margin-bottom:20px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
.card{{background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;padding:12px 16px}}
.cl{{font-size:11px;color:#999;margin-bottom:4px}}
.cv{{font-size:18px;font-weight:500}}
.legend{{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:12px;align-items:center}}
table{{width:100%;border-collapse:collapse;background:#fff;
       border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:20px}}
thead tr{{background:#f5f5f5}}
th{{padding:8px 10px;font-size:12px;font-weight:500;text-align:left;
    border-bottom:0.5px solid #e0e0e0}}
tr:hover{{background:#fafafa}}
.recs{{background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;
       padding:14px 16px;margin-bottom:16px}}
.recs h3{{font-size:14px;font-weight:500;margin-bottom:10px}}
.footer{{font-size:11px;color:#bbb;text-align:right}}
.bl-label{{font-size:10px;color:#aaa}}
</style></head><body>
<h1>Live ГПР — Школа №65, Уральск</h1>
<div class="sub">AINTELLECTUM · Live Construction Engine v1.1 · Дата: {self.report_date}</div>
<div class="cards">
  <div class="card"><div class="cl">Baseline финиш</div><div class="cv">{base_fin}</div></div>
  <div class="card"><div class="cl">Live финиш</div>
    <div class="cv" style="color:{'#BA7517' if total_delay>0 else '#1D9E75'}">{live_fin}</div></div>
  <div class="card"><div class="cl">Сдвиг графика</div>
    <div class="cv" style="color:{'#BA7517' if total_delay>0 else '#1D9E75'}">{delay_str}</div></div>
  <div class="card"><div class="cl">Задач</div>
    <div class="cv">{len(tasks)} ({stat.get("completed",0)} завершено)</div></div>
</div>
<div class="recs"><h3>Рекомендации</h3><ul style="padding-left:18px">{recs_html}</ul></div>
<div class="legend">{legend}
  <span style="font-size:12px;color:#999;margin-left:8px">
    ▪ верхняя полоса = baseline &nbsp; ▪ нижняя = live
  </span>
</div>
<table>
  <thead><tr><th>Фаза</th><th>Статус</th><th>Прогресс</th><th>Диаграмма (baseline / live)</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<div class="footer">AINTELLECTUM Live Construction Engine v1.1 · Ереке · Аян · Claude</div>
</body></html>"""

        with open("live_gantt_chart.html","w",encoding="utf-8") as f:
            f.write(html)
        size = Path("live_gantt_chart.html").stat().st_size
        print(f"[Live] ✅ live_gantt_chart.html ({size//1024} КБ) → открой в браузере")

    def _save_json(self, data, path):
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Live] ✅ {path} ({Path(path).stat().st_size//1024} КБ)")

    def _print_summary(self, stat, base_fin, live_fin, delay, cp_chg, recs):
        print()
        print("="*65)
        print("  LIVE CONSTRUCTION ENGINE v1.1 — РЕЗУЛЬТАТ")
        print("="*65)
        print(f"  Дата отчёта:   {self.report_date}")
        print(f"  Baseline:      {base_fin}")
        print(f"  Live финиш:    {live_fin}")
        ds = f"+{delay} дн. ЗАДЕРЖКА" if delay>0 else f"{abs(delay)} дн. ОПЕРЕЖЕНИЕ" if delay<0 else "БЕЗ ИЗМЕНЕНИЙ"
        print(f"  Сдвиг:         {ds}")
        print(f"  КП изменился:  {'ДА ⚠️' if cp_chg else 'нет'}")
        print()
        ICONS = {"completed":"✅","on_track":"🟢","delayed":"🔴",
                 "blocked":"🚫","ahead":"🚀","not_started":"⬜","not_updated":"❓"}
        for s, cnt in sorted(stat.items(), key=lambda x:-x[1]):
            print(f"    {ICONS.get(s,'  ')} {s:<15} {cnt}")
        if self.risks:
            print()
            print("  РИСКИ:")
            for r in self.risks[:5]:
                print(f"    {'[КП] ' if r['is_critical'] else '      '}"
                      f"{r['phase']:<35} {r['risk_type']}")
                print(f"           {r['reason']}")
                print(f"           → {r['recommendation']}")
        print()
        print("  ФАЙЛЫ: live_gpr_schedule.json · live_gpr_summary.json")
        print("         live_delay_risks.json  · live_vs_baseline.json")
        print("         live_gantt_chart.html")
        print("="*65)

    def run(self):
        self.load_inputs()
        self.rebuild()
        self.run_cpm()
        self.build_risks()
        self.save()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gpr",      default="gpr_schedule.json")
    p.add_argument("--cp",       default="gpr_critical_path.json")
    p.add_argument("--progress", default="daily_progress.json")
    p.add_argument("--date",     default=date.today().isoformat())
    p.add_argument("--test",     choices=["on_track","delayed","ahead"],
                   help="Запустить тестовый сценарий")
    args = p.parse_args()

    print("="*65)
    print("  LIVE CONSTRUCTION ENGINE v1.1 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  baseline + факт = живой график + визуализация")
    print("="*65); print()

    # Тестовый сценарий
    if args.test:
        print(f"[Live] Тестовый сценарий: {args.test}")
        with open(args.gpr, encoding="utf-8") as f:
            gpr = json.load(f)
        demo = make_test_progress(gpr.get("tasks",[]), args.test, args.date)
        test_path = f"daily_progress_{args.test}.json"
        with open(test_path,"w",encoding="utf-8") as f:
            json.dump(demo, f, ensure_ascii=False, indent=2)
        args.progress = test_path
        print(f"[Live] Тест-данные: {test_path}")

    engine = LiveConstructionEngineV11(args.gpr, args.cp, args.progress, args.date)
    engine.run()