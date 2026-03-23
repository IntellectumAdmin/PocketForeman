# -*- coding: utf-8 -*-
"""
Decision Engine v2.0 — Assisted Replanning Engine
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

Принцип (от Аяна):
  Система ПРЕДЛАГАЕТ сценарии перепланирования — человек ВЫБИРАЕТ.
  Никакого black-box. Всё explainable.

  live risks + finance risks + live schedule
  → SHIFT / ACCELERATE / DEFER
  → сравнение → recommended scenario

Входные файлы:
  gpr_schedule.json, live_gpr_schedule.json, live_gpr_summary.json
  live_delay_risks.json, live_finance_summary.json
  cash_gap_risks.json, recommended_actions.json, decision_summary.json

Выходные файлы:
  replanning_summary.json
  replanning_scenarios.json
  recommended_replanned_gpr.json
  replanning_report.html

ИСПОЛЬЗОВАНИЕ:
  python decision_engine_v2.py
  python decision_engine_v2.py --date 2025-07-15
"""

import json
import argparse
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict, deque


# ─── Конфигурация ────────────────────────────────────────────────────────────

ACCELERATION_FACTOR     = 0.8    # ускорение критичной задачи
DEFER_FLOAT_THRESHOLD   = 30     # задачи с резервом > 30 дней — кандидаты в defer
CASH_GAP_CRITICAL_MLN   = -200   # критический порог разрыва (млн тг)

# Веса для score (configurable)
WEIGHTS = {
    "schedule":  0.4,
    "finance":   0.3,
    "stability": 0.1,
    "risk":      0.2,
}


# ─── Вспомогательные ─────────────────────────────────────────────────────────

def safe_load(path: str):
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def parse_date(s: str) -> date:
    return date.fromisoformat(s) if s else date(2025, 1, 1)


def topo_sort(tasks: dict, deps: dict) -> list:
    in_deg = {t: 0 for t in tasks}
    succ   = defaultdict(list)
    for t, ds in deps.items():
        for d in ds:
            if d in tasks:
                in_deg[t] += 1
                succ[d].append(t)
    q   = deque(t for t, d in in_deg.items() if d == 0)
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


def forward_pass(tasks: dict, deps: dict, durations: dict) -> dict:
    """Forward pass — возвращает {tid: (start_day, finish_day)}"""
    order = topo_sort(tasks, deps)
    ef = {}
    es = {}
    for tid in order:
        d_list = [d for d in deps.get(tid, []) if d in tasks]
        e_s = max((ef.get(d, 0) for d in d_list), default=0)
        es[tid] = e_s
        ef[tid] = e_s + max(durations.get(tid, 0), 0)
    return {t: (es[t], ef[t]) for t in tasks}


# ─── Основной класс ──────────────────────────────────────────────────────────

class DecisionEngineV2:

    def __init__(self, report_date: str):
        self.report_date = report_date

        # Входные данные
        self.baseline_tasks  = {}   # tid → task
        self.live_tasks      = {}   # tid → live task
        self.deps            = {}   # tid → [dep_tids]
        self.gpr_summary     = {}
        self.delay_risks     = []
        self.finance_summary = {}
        self.cash_gap_risks  = []
        self.decision_summary = {}

        # Результаты
        self.triggers    = []
        self.scenarios   = []
        self.recommended = None

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def load_inputs(self):
        print("[Replan] Загружаю входные данные...")

        # Baseline GPR
        bg = safe_load("gpr_schedule.json")
        if bg:
            for t in bg.get("tasks", []):
                tid = t.get("task_id","")
                if tid:
                    self.baseline_tasks[tid] = dict(t)
                    preds = t.get("predecessors",[])
                    self.deps[tid] = [p for p in (preds if isinstance(preds,list) else []) if p]
        print(f"[Replan]   Baseline задач: {len(self.baseline_tasks)}")

        # Live GPR
        lg = safe_load("live_gpr_schedule.json")
        if lg:
            for t in lg.get("tasks", []):
                tid = t.get("task_id","")
                if tid:
                    self.live_tasks[tid] = dict(t)

        self.gpr_summary = safe_load("live_gpr_summary.json") or {}

        dr = safe_load("live_delay_risks.json")
        self.delay_risks = (dr or {}).get("risks", [])
        print(f"[Replan]   Риски сроков: {len(self.delay_risks)}")

        self.finance_summary = safe_load("live_finance_summary.json") or {}

        cr = safe_load("cash_gap_risks.json")
        self.cash_gap_risks = (cr or {}).get("risks", [])
        print(f"[Replan]   Кассовые риски: {len(self.cash_gap_risks)}")

        self.decision_summary = safe_load("decision_summary.json") or {}

    # ── 1. Триггеры перепланирования ─────────────────────────────────────────

    def detect_replanning_triggers(self):
        print("[Replan] Определяю триггеры перепланирования...")
        self.triggers = []

        # Schedule triggers
        for r in self.delay_risks:
            if r.get("is_critical") and r.get("risk_type") == "blocked":
                self.triggers.append({
                    "type":   "critical_path_blocked",
                    "phase":  r.get("phase",""),
                    "detail": r.get("reason",""),
                })
            elif r.get("is_critical") and r.get("risk_type") in ("critical_delay","delay"):
                self.triggers.append({
                    "type":   "critical_path_delayed",
                    "phase":  r.get("phase",""),
                    "impact_days": r.get("impact_days",0),
                })

        # Finance triggers
        fin_status = self.finance_summary.get("status","")
        peak_gap   = self.finance_summary.get("peak_cash_gap_mln", 0) * 1_000_000
        if fin_status in ("critical","risk") or peak_gap < CASH_GAP_CRITICAL_MLN * 1_000_000:
            self.triggers.append({
                "type":   "critical_cash_gap",
                "peak_gap_mln": round(peak_gap/1_000_000, 2),
                "month":  self.finance_summary.get("peak_gap_month",""),
            })

        # Schedule drift
        si = self.gpr_summary.get("schedule_impact",{})
        delay_d = si.get("delay_days", 0)
        if delay_d > 14:
            self.triggers.append({
                "type":   "schedule_drift",
                "delay_days": delay_d,
            })

        trigger_needed = len(self.triggers) > 0
        print(f"[Replan]   Триггеров: {len(self.triggers)} → "
              f"{'ПЕРЕПЛАНИРОВАНИЕ НУЖНО' if trigger_needed else 'Нет необходимости'}")
        return trigger_needed

    # ── Вспомогательные для сценариев ────────────────────────────────────────

    def _live_durations(self) -> dict:
        """Текущие длительности из live GPR."""
        return {tid: max(t.get("live_duration", t.get("baseline_duration",0)), 0)
                for tid, t in self.live_tasks.items()} \
               if self.live_tasks else \
               {tid: max(t.get("duration_days",0), 0)
                for tid, t in self.baseline_tasks.items()}

    def _project_start(self) -> date:
        dates = []
        for t in self.baseline_tasks.values():
            s = t.get("start_date") or t.get("live_start")
            if s:
                dates.append(parse_date(s))
        return min(dates) if dates else date(2025, 1, 1)

    def _calc_finish(self, durations: dict) -> date:
        proj_start = self._project_start()
        sched = forward_pass(durations, self.deps, durations)
        if not sched:
            return proj_start
        max_day = max(v[1] for v in sched.values())
        return proj_start + timedelta(days=max_day)

    def _critical_path_ids(self, durations: dict) -> list:
        """Простой CPM для нового расписания."""
        order   = topo_sort(durations, self.deps)
        ef = {}
        es = {}
        for t in order:
            ds  = [d for d in self.deps.get(t,[]) if d in durations]
            e_s = max((ef.get(d,0) for d in ds), default=0)
            es[t] = e_s
            ef[t] = e_s + durations.get(t, 0)
        proj_end = max(ef.values()) if ef else 0
        succ = defaultdict(list)
        for t, ds in self.deps.items():
            for d in ds:
                if d in durations:
                    succ[d].append(t)
        lf = {}
        ls = {}
        for t in reversed(order):
            my_s = [s for s in succ[t] if s in durations]
            lf[t] = min((ls.get(s, proj_end) for s in my_s), default=proj_end)
            ls[t] = lf[t] - durations.get(t, 0)
        return [t for t in durations
                if max(0, ls.get(t,0) - es.get(t,0)) == 0 and durations.get(t,0) > 0]

    def _affected_tasks(self, new_dur: dict, base_dur: dict) -> int:
        return sum(1 for t in new_dur if abs(new_dur[t] - base_dur.get(t,0)) > 0)

    # ── 2. Сценарий SHIFT ────────────────────────────────────────────────────

    def generate_shift_scenario(self) -> dict:
        """Консервативный: честный сдвиг downstream без изменения ресурсов."""
        print("[Replan]   Генерирую сценарий SHIFT...")
        base_dur = self._live_durations()
        new_dur  = dict(base_dur)  # без изменений — сдвиг определяется зависимостями

        new_finish    = self._calc_finish(new_dur)
        baseline_fin  = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                    "baseline_finish","2027-02-02"))
        live_fin      = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                    "live_finish","2027-02-02"))
        affected      = 0  # SHIFT не меняет длительности, только честно показывает live

        cp = self._critical_path_ids(new_dur)
        cp_phases = [self.baseline_tasks.get(t,{}).get("phase",t) for t in cp[:5]]

        return {
            "scenario_id":                "SHIFT",
            "scenario_type":              "conservative",
            "description":                "Сдвиг downstream задач без изменения ресурсов",
            "new_finish":                 new_finish.isoformat(),
            "finish_delta_vs_live_days":  (new_finish - live_fin).days,
            "finish_delta_vs_baseline_days": (new_finish - baseline_fin).days,
            "peak_cash_gap_mln":          self.finance_summary.get("peak_cash_gap_mln",0),
            "affected_tasks":             affected,
            "new_critical_path":          cp_phases,
            "new_durations":              new_dur,
            "pros":                       ["Реалистичный прогноз", "Нет дополнительных затрат"],
            "cons":                       ["Финиш уходит вправо", "Кассовый разрыв не устраняется"],
            "score":                      0.0,
        }

    # ── 3. Сценарий ACCELERATE ────────────────────────────────────────────────

    def generate_accelerate_scenario(self) -> dict:
        """Ускоренный: сокращение duration критичных задач за счёт ресурсов."""
        print("[Replan]   Генерирую сценарий ACCELERATE...")
        base_dur = self._live_durations()
        new_dur  = dict(base_dur)

        # Найти критичные задачи с задержкой/блокировкой
        cp_delayed = set()
        for r in self.delay_risks:
            if r.get("is_critical") and r.get("risk_type") in (
                    "blocked","critical_delay","delay"):
                # Ищем task_id по фазе
                for tid, t in self.baseline_tasks.items():
                    if t.get("phase","") == r.get("phase",""):
                        cp_delayed.add(tid)

        accelerated = []
        for tid in cp_delayed:
            old_dur = new_dur.get(tid, 0)
            if old_dur > 0:
                new_d = max(1, int(old_dur * ACCELERATION_FACTOR))
                new_dur[tid] = new_d
                accelerated.append({
                    "task_id": tid,
                    "phase":   self.baseline_tasks.get(tid,{}).get("phase",tid),
                    "old_dur": old_dur,
                    "new_dur": new_d,
                    "saved_days": old_dur - new_d,
                })

        new_finish    = self._calc_finish(new_dur)
        baseline_fin  = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                    "baseline_finish","2027-02-02"))
        live_fin      = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                    "live_finish","2027-02-02"))
        # При ускорении нужно больше ресурсов → немного растёт cash gap
        gap_est = self.finance_summary.get("peak_cash_gap_mln",0) * 1.1
        cp      = self._critical_path_ids(new_dur)
        cp_ph   = [self.baseline_tasks.get(t,{}).get("phase",t) for t in cp[:5]]

        return {
            "scenario_id":                "ACCELERATE",
            "scenario_type":              "resource_boost",
            "description":                "Ускорение критичных фаз за счёт увеличения ресурсов",
            "new_finish":                 new_finish.isoformat(),
            "finish_delta_vs_live_days":  (new_finish - live_fin).days,
            "finish_delta_vs_baseline_days": (new_finish - baseline_fin).days,
            "peak_cash_gap_mln":          round(gap_est, 2),
            "affected_tasks":             len(accelerated),
            "accelerated_tasks":          accelerated,
            "new_critical_path":          cp_ph,
            "new_durations":              new_dur,
            "acceleration_factor":        ACCELERATION_FACTOR,
            "pros":                       ["Улучшает срок финиша", "Снижает риск критического пути"],
            "cons":                       ["Требует больше ресурсов и бюджета",
                                           "Небольшой рост кассового давления"],
            "score":                      0.0,
        }

    # ── 4. Сценарий DEFER ────────────────────────────────────────────────────

    def generate_defer_scenario(self) -> dict:
        """Финансово-щадящий: перенос некритичных задач."""
        print("[Replan]   Генерирую сценарий DEFER...")
        base_dur = self._live_durations()
        new_dur  = dict(base_dur)

        # CPM на текущем расписании
        cp_ids = set(self._critical_path_ids(new_dur))

        # Найти некритичные задачи с большим резервом
        deferred = []
        for tid, t in self.live_tasks.items():
            if tid in cp_ids:
                continue
            flt = t.get("live_float", t.get("float_days", 0)) or 0
            if flt >= DEFER_FLOAT_THRESHOLD:
                # Сдвигаем: уменьшаем эффективную duration для раннего периода
                # (моделируем перенос начала на float/2)
                deferred.append({
                    "task_id":    tid,
                    "phase":      t.get("phase", tid),
                    "float_days": flt,
                    "defer_days": flt // 2,
                })

        new_finish    = self._calc_finish(new_dur)
        baseline_fin  = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                    "baseline_finish","2027-02-02"))
        live_fin      = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                    "live_finish","2027-02-02"))
        # DEFER снижает пиковую нагрузку на финансы
        gap_est = self.finance_summary.get("peak_cash_gap_mln",0) * 0.75
        cp      = self._critical_path_ids(new_dur)
        cp_ph   = [self.baseline_tasks.get(t,{}).get("phase",t) for t in cp[:5]]

        return {
            "scenario_id":                "DEFER",
            "scenario_type":              "finance_relief",
            "description":                "Перенос некритичных фаз для снижения кассового давления",
            "new_finish":                 new_finish.isoformat(),
            "finish_delta_vs_live_days":  (new_finish - live_fin).days,
            "finish_delta_vs_baseline_days": (new_finish - baseline_fin).days,
            "peak_cash_gap_mln":          round(gap_est, 2),
            "affected_tasks":             len(deferred),
            "deferred_tasks":             deferred[:10],
            "new_critical_path":          cp_ph,
            "new_durations":              new_dur,
            "pros":                       ["Снижает пиковую финансовую нагрузку",
                                           "Не требует дополнительных ресурсов"],
            "cons":                       ["Некоторые второстепенные работы откладываются",
                                           "Финиш не улучшается"],
            "score":                      0.0,
        }

    # ── 5. Оценка сценариев ──────────────────────────────────────────────────

    def evaluate_scenario(self, sc: dict) -> float:
        """Score model (0-100, выше = лучше)."""
        live_fin     = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                   "live_finish","2027-02-02"))
        baseline_fin = parse_date(self.gpr_summary.get("schedule_impact",{}).get(
                                   "baseline_finish","2027-02-02"))
        new_fin      = parse_date(sc["new_finish"])
        total_tasks  = max(len(self.baseline_tasks), 1)

        # Schedule score: чем раньше новый финиш относительно live — тем лучше
        delta_live = (live_fin - new_fin).days
        sched_score = min(100, max(0, 50 + delta_live))

        # Finance score: чем меньше (по модулю) пиковый разрыв — тем лучше
        gap_mln = sc.get("peak_cash_gap_mln", 0)
        fin_score = min(100, max(0, 100 + gap_mln * 0.2))

        # Stability score: чем меньше изменений — тем лучше
        aff = sc.get("affected_tasks", 0)
        stab_score = min(100, max(0, 100 - aff / total_tasks * 100))

        # Risk score: нет критичных задач на КП = лучше
        n_cp_blocked = sum(1 for r in self.delay_risks
                           if r.get("is_critical") and r.get("risk_type")=="blocked")
        risk_score = min(100, max(0, 100 - n_cp_blocked * 25))

        score = (WEIGHTS["schedule"]  * sched_score +
                 WEIGHTS["finance"]   * fin_score   +
                 WEIGHTS["stability"] * stab_score  +
                 WEIGHTS["risk"]      * risk_score)
        return round(score, 1)

    def compare_scenarios(self):
        print("[Replan] Сравниваю сценарии и выбираю рекомендованный...")
        for sc in self.scenarios:
            sc["score"] = self.evaluate_scenario(sc)
            # Убираем служебные поля перед сериализацией
            sc.pop("new_durations", None)

        self.scenarios.sort(key=lambda x: -x["score"])

        best = self.scenarios[0]
        self.recommended = best["scenario_id"]
        print(f"[Replan]   Сценарии (score):")
        for sc in self.scenarios:
            star = " ← РЕКОМЕНДОВАН" if sc["scenario_id"] == self.recommended else ""
            print(f"[Replan]     {sc['scenario_id']:<12} score={sc['score']}"
                  f"  финиш={sc['new_finish']}{star}")

    # ── 6. Recommended replanned GPR ─────────────────────────────────────────

    def build_recommended_replanned_gpr(self) -> list:
        best_sc = next(s for s in self.scenarios
                       if s["scenario_id"] == self.recommended)
        sc_type = best_sc["scenario_type"]

        tasks_out = []
        for tid, bt in self.baseline_tasks.items():
            lt = self.live_tasks.get(tid, bt)
            change_type   = "unchanged"
            change_reason = ""

            # Определяем тип изменения
            if sc_type == "resource_boost":
                accel = [a for a in best_sc.get("accelerated_tasks",[])
                         if a["task_id"] == tid]
                if accel:
                    change_type   = "accelerated"
                    change_reason = "critical_path_delay"
            elif sc_type == "finance_relief":
                def_t = [d for d in best_sc.get("deferred_tasks",[])
                         if d["task_id"] == tid]
                if def_t:
                    change_type   = "deferred"
                    change_reason = f"float={def_t[0]['float_days']}д"
            elif sc_type == "conservative":
                if lt.get("delay_days",0) > 0:
                    change_type   = "shifted"
                    change_reason = f"downstream_of_delayed"

            tasks_out.append({
                "task_id":           tid,
                "phase":             bt.get("phase",""),
                "baseline_start":    bt.get("start_date"),
                "baseline_finish":   bt.get("finish_date"),
                "live_start":        lt.get("live_start"),
                "live_finish":       lt.get("live_finish"),
                "replanned_start":   lt.get("live_start"),
                "replanned_finish":  lt.get("live_finish"),
                "change_type":       change_type,
                "change_reason":     change_reason,
            })
        return tasks_out

    # ── Сохранение ───────────────────────────────────────────────────────────

    def save_results(self):
        best = next(s for s in self.scenarios
                    if s["scenario_id"] == self.recommended)
        live_fin = self.gpr_summary.get("schedule_impact",{}).get("live_finish","")
        base_fin = self.gpr_summary.get("schedule_impact",{}).get("baseline_finish","")
        impr = (parse_date(live_fin) - parse_date(best["new_finish"])).days \
               if live_fin and best.get("new_finish") else 0

        why_map = {
            "SHIFT":       "Консервативный сценарий — реалистичный прогноз без дополнительных затрат",
            "ACCELERATE":  "Лучший баланс между улучшением срока и финансовым давлением",
            "DEFER":       "Приоритет снижения кассового давления при сохранении критического пути",
        }

        # 1. replanning_summary.json
        self._save_json({
            "engine_version":      "2.0",
            "project":             "Школа №65, Уральск",
            "date":                self.report_date,
            "replanning_trigger":  len(self.triggers) > 0,
            "trigger_types":       [t["type"] for t in self.triggers],
            "baseline_finish":     base_fin,
            "live_finish":         live_fin,
            "recommended_scenario": self.recommended,
            "recommended_finish":  best.get("new_finish",""),
            "improvement_days":    impr,
            "why":                 why_map.get(self.recommended,""),
            "tradeoffs":           best.get("cons",[]),
        }, "replanning_summary.json")

        # 2. replanning_scenarios.json
        sc_clean = [{k: v for k, v in s.items()
                     if k not in ("new_durations","accelerated_tasks","deferred_tasks")}
                    for s in self.scenarios]
        for i, s in enumerate(sc_clean):
            s["accelerated_tasks"] = self.scenarios[i].get("accelerated_tasks",[])
            s["deferred_tasks"]    = self.scenarios[i].get("deferred_tasks",[])
        self._save_json({
            "engine_version": "2.0",
            "report_date":    self.report_date,
            "scenarios":      sc_clean,
        }, "replanning_scenarios.json")

        # 3. recommended_replanned_gpr.json
        tasks_out = self.build_recommended_replanned_gpr()
        self._save_json({
            "engine_version": "2.0",
            "scenario":       self.recommended,
            "report_date":    self.report_date,
            "replanned_finish": best.get("new_finish",""),
            "tasks":          tasks_out,
        }, "recommended_replanned_gpr.json")

        # 4. HTML
        self._build_html(best, base_fin, live_fin, impr, why_map)
        self._print_summary(best, base_fin, live_fin, impr)

    def _build_html(self, best, base_fin, live_fin, impr, why_map):
        SC_COLOR = {"SHIFT":"#378ADD","ACCELERATE":"#1D9E75","DEFER":"#EF9F27"}
        SC_ICON  = {"SHIFT":"→","ACCELERATE":"⚡","DEFER":"⏸"}

        # Таблица сценариев
        sc_rows = ""
        for sc in self.scenarios:
            is_rec = sc["scenario_id"] == self.recommended
            bc     = SC_COLOR.get(sc["scenario_id"],"#888")
            badge  = '<span style="background:#1D9E75;color:#fff;font-size:10px;padding:1px 5px;border-radius:3px;margin-left:4px">★ РЕК.</span>' if is_rec else ""
            delta  = sc["finish_delta_vs_live_days"]
            delta_s = f"+{delta} дн." if delta > 0 else f"{delta} дн." if delta < 0 else "без изменений"
            delta_c = "#E24B4A" if delta > 0 else "#1D9E75" if delta < 0 else "#888"
            sc_rows += f"""
      <tr style="{'background:#f0f9f4;' if is_rec else ''}">
        <td style="padding:8px 10px;font-size:13px;border-bottom:0.5px solid #eee;">
          <span style="background:{bc};color:#fff;padding:3px 8px;border-radius:4px;
                       font-size:12px">{SC_ICON.get(sc['scenario_id'],'')} {sc['scenario_id']}</span>
          {badge}</td>
        <td style="padding:8px 10px;font-size:12px;border-bottom:0.5px solid #eee;">
          {sc.get('description','')}</td>
        <td style="padding:8px 10px;font-size:13px;font-weight:500;
                   border-bottom:0.5px solid #eee;">{sc.get('new_finish','')}</td>
        <td style="padding:8px 10px;font-size:13px;color:{delta_c};
                   border-bottom:0.5px solid #eee;">{delta_s}</td>
        <td style="padding:8px 10px;font-size:12px;color:#E24B4A;
                   border-bottom:0.5px solid #eee;">{sc.get('peak_cash_gap_mln',0):+.1f} млн</td>
        <td style="padding:8px 10px;font-size:12px;border-bottom:0.5px solid #eee;">
          {sc.get('affected_tasks',0)}</td>
        <td style="padding:8px 10px;font-size:14px;font-weight:500;
                   border-bottom:0.5px solid #eee;color:{bc}">{sc.get('score',0)}</td>
      </tr>"""

        # Триггеры
        trig_html = "".join(
            f'<div style="margin-bottom:6px;padding:8px 12px;background:#fff;'
            f'border:0.5px solid #e0e0e0;border-radius:6px;font-size:13px;">'
            f'<b>{t["type"]}</b>'
            f'{" — " + t.get("phase","") if t.get("phase") else ""}'
            f'{" (" + str(t.get("impact_days","")) + " дн.)" if t.get("impact_days") else ""}'
            f'{" → " + str(t.get("peak_gap_mln","")) + " млн тг" if t.get("peak_gap_mln") else ""}'
            f'</div>'
            for t in self.triggers
        ) or '<p style="color:#888;font-size:13px">Триггеров не обнаружено</p>'

        # Изменения в рекомендованном сценарии
        changes_html = ""
        if best["scenario_id"] == "ACCELERATE":
            for a in best.get("accelerated_tasks",[]):
                changes_html += f'<div style="padding:5px 10px;font-size:12px;border-bottom:0.5px solid #eee;">⚡ <b>{a["phase"]}</b>: {a["old_dur"]} → {a["new_dur"]} дн. (сэкономлено {a["saved_days"]} дн.)</div>'
        elif best["scenario_id"] == "DEFER":
            for d in best.get("deferred_tasks",[])[:5]:
                changes_html += f'<div style="padding:5px 10px;font-size:12px;border-bottom:0.5px solid #eee;">⏸ <b>{d["phase"]}</b>: перенос на {d["defer_days"]} дн. (резерв {d["float_days"]} дн.)</div>'
        if not changes_html:
            changes_html = '<p style="padding:10px;color:#888;font-size:13px">Сдвиг downstream задач согласно зависимостям</p>'

        impr_color = "#1D9E75" if impr > 0 else "#E24B4A" if impr < 0 else "#888"
        impr_str   = f"+{impr} дн. улучшение" if impr > 0 else f"{impr} дн." if impr < 0 else "без изменений"

        html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Replanning Report — AINTELLECTUM</title>
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
table{{width:100%;border-collapse:collapse;background:#fff;
       border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:24px}}
thead tr{{background:#f5f5f5}}
th{{padding:8px 10px;font-size:12px;font-weight:500;text-align:left;
    border-bottom:0.5px solid #e0e0e0}}
tr:hover{{background:#fafafa}}
.rec-box{{background:#fff;border:2px solid #1D9E75;border-radius:10px;
          padding:16px 20px;margin-bottom:24px}}
.footer{{font-size:11px;color:#bbb;text-align:right;margin-top:16px}}
</style></head><body>
<h1>Replanning Report — Школа №65, Уральск</h1>
<div class="sub">AINTELLECTUM · Decision Engine v2.0 · Assisted Replanning · {self.report_date}</div>

<div class="cards">
  <div class="card"><div class="cl">Baseline финиш</div><div class="cv">{base_fin}</div></div>
  <div class="card"><div class="cl">Live финиш</div><div class="cv" style="color:#E24B4A">{live_fin}</div></div>
  <div class="card"><div class="cl">Рекомендованный финиш</div>
    <div class="cv" style="color:#1D9E75">{best.get('new_finish','')}</div></div>
  <div class="card"><div class="cl">Улучшение</div>
    <div class="cv" style="color:{impr_color}">{impr_str}</div></div>
</div>

<h2>Триггеры перепланирования</h2>
{trig_html}

<h2>Сравнение сценариев</h2>
<table>
  <thead><tr><th>Сценарий</th><th>Описание</th><th>Новый финиш</th>
    <th>Δ vs live</th><th>Пик разрыва</th><th>Затронуто</th><th>Score</th></tr></thead>
  <tbody>{sc_rows}</tbody>
</table>

<div class="rec-box">
  <div style="font-size:15px;font-weight:500;color:#1D9E75;margin-bottom:8px">
    ★ Рекомендованный сценарий: {self.recommended}</div>
  <div style="font-size:13px;color:#444;margin-bottom:8px">
    {why_map.get(self.recommended,'')}</div>
  <div style="font-size:12px;color:#888">
    Компромиссы: {' · '.join(best.get('cons',[]))}</div>
</div>

<h2>Что изменится ({self.recommended})</h2>
<div style="background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden;margin-bottom:24px">
{changes_html}
</div>

<div style="background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;padding:14px 16px;
            font-size:13px;color:#666;margin-bottom:24px">
  ⚠️ Этот план <b>не применяется автоматически</b>. Ереке или ПТО должны утвердить сценарий.
</div>

<div class="footer">AINTELLECTUM Decision Engine v2.0 · Ереке · Аян · Claude</div>
</body></html>"""

        with open("replanning_report.html","w",encoding="utf-8") as f:
            f.write(html)
        sz = Path("replanning_report.html").stat().st_size
        print(f"[Replan] ✅ replanning_report.html ({sz//1024} КБ) → открой в браузере")

    def _save_json(self, data, path):
        with open(path,"w",encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Replan] ✅ {path} ({Path(path).stat().st_size//1024} КБ)")

    def _print_summary(self, best, base_fin, live_fin, impr):
        print()
        print("="*65)
        print("  DECISION ENGINE v2.0 — ASSISTED REPLANNING — РЕЗУЛЬТАТ")
        print("="*65)
        print(f"  Дата отчёта:       {self.report_date}")
        print(f"  Триггеров:         {len(self.triggers)}")
        for t in self.triggers:
            print(f"    • {t['type']}")
        print()
        print(f"  Baseline финиш:    {base_fin}")
        print(f"  Live финиш:        {live_fin}")
        print(f"  Рекомендован:      {self.recommended}")
        print(f"  Новый финиш:       {best.get('new_finish','')}")
        impr_s = f"+{impr} дн. улучшение" if impr > 0 else f"{impr} дн." if impr < 0 else "без изменений"
        print(f"  Улучшение:         {impr_s}")
        print()
        print("  СЦЕНАРИИ:")
        for sc in self.scenarios:
            star = " ★ РЕКОМЕНДОВАН" if sc["scenario_id"] == self.recommended else ""
            print(f"    {sc['scenario_id']:<12} score={sc['score']:>5.1f}  "
                  f"финиш={sc.get('new_finish','')}  "
                  f"gap={sc.get('peak_cash_gap_mln',0):+.1f}млн{star}")
        print()
        print("  Файлы: replanning_summary.json · replanning_scenarios.json")
        print("         recommended_replanned_gpr.json · replanning_report.html")
        print("="*65)

    def run(self):
        self.load_inputs()
        needs_replan = self.detect_replanning_triggers()

        if not needs_replan:
            print("[Replan] Перепланирование не требуется — проект в норме ✅")
            self._save_json({
                "engine_version":     "2.0",
                "replanning_trigger": False,
                "message":            "Перепланирование не требуется",
                "date":               self.report_date,
            }, "replanning_summary.json")
            return

        # Генерируем 3 сценария
        self.scenarios.append(self.generate_shift_scenario())
        self.scenarios.append(self.generate_accelerate_scenario())
        self.scenarios.append(self.generate_defer_scenario())

        self.compare_scenarios()
        self.save_results()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="AINTELLECTUM Decision Engine v2.0 — Assisted Replanning")
    p.add_argument("--date", default=date.today().isoformat())
    args = p.parse_args()

    print("="*65)
    print("  DECISION ENGINE v2.0 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  Assisted Replanning Engine — система предлагает, человек решает")
    print("="*65); print()

    engine = DecisionEngineV2(args.date)
    engine.run()