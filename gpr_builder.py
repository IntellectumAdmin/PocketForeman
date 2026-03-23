# -*- coding: utf-8 -*-
"""
GPR BUILDER v3.0
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

ИЗМЕНЕНИЯ v3.0 vs v2.0:
  - Читает duration_summary.json (max per phase от Duration Engine v7.0)
  - Убрано ошибочное суммирование длительностей
  - Сохранена архитектура v2.0: CPM + Kahn + backward pass

ИСПОЛЬЗОВАНИЕ:
  python gpr_builder.py
  python gpr_builder.py --start-date 2025-01-01
"""

import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import deque
from datetime import datetime, timedelta


DEPENDENCY_RULES = [
    ("Земляные работы",                     []),
    ("Монолитный каркас",                   ["Земляные работы"]),
    ("Наружные сети водоснабжения",         ["Земляные работы"]),
    ("Наружная канализация",                ["Земляные работы"]),
    ("Каменные работы",                     ["Монолитный каркас"]),
    ("Металлические конструкции",           ["Монолитный каркас"]),
    ("Деревянные конструкции",              ["Монолитный каркас"]),
    ("Гидро- и пароизоляция",               ["Монолитный каркас"]),
    ("Фасадные работы",                     ["Монолитный каркас"]),
    ("Лестницы и площадки",                 ["Монолитный каркас"]),
    ("Перегородки",                         ["Каменные работы"]),
    ("Кровля",                              ["Металлические конструкции",
                                             "Деревянные конструкции"]),
    ("Кровля наружная",                     ["Монолитный каркас",
                                             "Металлические конструкции"]),
    ("Окна и двери",                        ["Кровля наружная",
                                             "Каменные работы"]),
    ("Водоснабжение и канализация",         ["Окна и двери"]),
    ("Отопление и теплоснабжение",          ["Окна и двери"]),
    ("Вентиляция и кондиционирование",      ["Окна и двери"]),
    ("Электроснабжение",                    ["Окна и двери"]),
    ("Отделочные работы",                   ["Водоснабжение и канализация",
                                             "Отопление и теплоснабжение",
                                             "Вентиляция и кондиционирование",
                                             "Электроснабжение"]),
    ("Полы",                                ["Отделочные работы"]),
    ("Сантехника (санузлы)",                ["Водоснабжение и канализация",
                                             "Отделочные работы"]),
    ("Слаботочные системы",                 ["Электроснабжение",
                                             "Отделочные работы"]),
    ("Прочие работы",                       ["Отделочные работы"]),
    # Благоустройство: обязательное — после кровли, некритичное — после земли (параллельно со стройкой)
    ("Благоустройство обязательное",        ["Кровля наружная",
                                             "Наружные сети водоснабжения",
                                             "Наружная канализация"]),
    ("Благоустройство некритичное",         ["Земляные работы"]),
]


class GPRBuilder:

    def __init__(self, summary_path="duration_summary.json", start_date=None):
        self.summary_path = Path(summary_path)
        self.start_date = (
            datetime.strptime(start_date, "%Y-%m-%d")
            if start_date else datetime(2025, 1, 1)
        )
        self.tasks = {}
        self.dependencies = {}
        self.sorted_tasks = []
        self.project_name = "Школа №65, Уральск"

    def load_inputs(self):
        print("Загружаю входные данные...")
        with open(self.summary_path, encoding="utf-8") as f:
            self.summary_data = json.load(f)
        phases = self.summary_data.get("phases", [])
        print(f"  Источник:  {self.summary_path}")
        print(f"  Фаз:       {len(phases)}")
        print(f"  Старт:     {self.start_date.strftime('%d.%m.%Y')}")

    def build_tasks(self):
        print("\nСтрою задачи ГПР...")
        for phase in self.summary_data.get("phases", []):
            phase_name = phase.get("phase", "").strip()
            if not phase_name:
                continue
            duration = phase.get("duration_days", 0)
            if duration <= 0:
                continue
            task_id = self._make_task_id(phase_name)
            self.tasks[task_id] = {
                "task_id":         task_id,
                "phase":           phase_name,
                "phase_order":     phase.get("phase_order", 99),
                "duration_days":   duration,
                "work_count":      phase.get("work_count", 0),
                "sum_sequential":  phase.get("sum_if_sequential", duration),
                "parallel_saving": phase.get("parallel_saving_days", 0),
                "start_day":       0,
                "finish_day":      0,
                "start_date":      None,
                "finish_date":     None,
                "is_critical":     False,
                "float_days":      0,
            }
        print(f"  Задач ГПР: {len(self.tasks)}")
        for tid, t in sorted(self.tasks.items(),
                              key=lambda x: x[1]["duration_days"], reverse=True):
            saving = t["parallel_saving"]
            save_s = f"  (экономия {saving} дн.)" if saving > 0 else ""
            print(f"    {t['duration_days']:>5} дн. | {t['phase']}{save_s}")

    def build_dependency_graph(self):
        print("\nСтрою граф зависимостей...")
        for task_id in self.tasks:
            self.dependencies[task_id] = []
        for phase_name, dep_names in DEPENDENCY_RULES:
            task_id = self._find_task(phase_name)
            if task_id is None:
                continue
            for dep_name in dep_names:
                dep_id = self._find_task(dep_name)
                if dep_id and dep_id != task_id:
                    if dep_id not in self.dependencies[task_id]:
                        self.dependencies[task_id].append(dep_id)
        total_deps  = sum(len(v) for v in self.dependencies.values())
        start_tasks = [tid for tid, deps in self.dependencies.items() if not deps]
        print(f"  Связей:          {total_deps}")
        print(f"  Стартовых задач: {len(start_tasks)}")
        for tid in start_tasks:
            print(f"    -> {self.tasks[tid]['phase']}")

    def _find_task(self, phase_name):
        name_lower = phase_name.lower().strip()
        for task_id, task in self.tasks.items():
            if task["phase"].lower().strip() == name_lower:
                return task_id
        for task_id, task in self.tasks.items():
            if name_lower in task["phase"].lower():
                return task_id
        return None

    def topological_sort(self):
        print("\nТопологическая сортировка (алгоритм Кана)...")
        in_degree  = {tid: 0 for tid in self.tasks}
        dependents = {tid: [] for tid in self.tasks}
        for task_id, deps in self.dependencies.items():
            for dep_id in deps:
                in_degree[task_id] += 1
                dependents[dep_id].append(task_id)
        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        self.sorted_tasks = []
        while queue:
            task_id = queue.popleft()
            self.sorted_tasks.append(task_id)
            for dep in dependents[task_id]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)
        if len(self.sorted_tasks) != len(self.tasks):
            print("  WARNING: цикл в графе")
            remaining = set(self.tasks.keys()) - set(self.sorted_tasks)
            self.sorted_tasks.extend(remaining)
        print(f"  Порядок: {len(self.sorted_tasks)} задач")

    def calculate_schedule(self):
        print("\nForward Pass - расчёт дат...")
        for task_id in self.sorted_tasks:
            task = self.tasks[task_id]
            deps = self.dependencies.get(task_id, [])
            start_day = (
                max(self.tasks[dep]["finish_day"] for dep in deps if dep in self.tasks)
                if deps else 0
            )
            task["start_day"]   = start_day
            task["finish_day"]  = start_day + task["duration_days"]
            task["start_date"]  = (self.start_date + timedelta(days=start_day)).strftime("%Y-%m-%d")
            task["finish_date"] = (self.start_date + timedelta(days=task["finish_day"])).strftime("%Y-%m-%d")
        total_days  = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0
        finish_date = self.start_date + timedelta(days=total_days)
        print(f"  Длительность: {total_days} дн. ({round(total_days/30.4,1)} мес.)")
        print(f"  Финиш:        {finish_date.strftime('%d.%m.%Y')}")
        return total_days

    def detect_critical_path(self):
        print("\nBackward Pass - критический путь (CPM)...")
        project_end = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0
        dependents  = {tid: [] for tid in self.tasks}
        for task_id, deps in self.dependencies.items():
            for dep_id in deps:
                dependents[dep_id].append(task_id)
        late_finish = {}
        late_start  = {}
        for task_id in reversed(self.sorted_tasks):
            task = self.tasks[task_id]
            my_deps = dependents[task_id]
            late_finish[task_id] = (
                min(late_start.get(dep, project_end) for dep in my_deps)
                if my_deps else project_end
            )
            late_start[task_id] = late_finish[task_id] - task["duration_days"]
        critical_path = []
        for task_id, task in self.tasks.items():
            float_days = max(0, late_start[task_id] - task["start_day"])
            task["float_days"]  = float_days
            task["is_critical"] = (float_days == 0 and task["duration_days"] > 0)
            task["late_start"]  = late_start[task_id]
            task["late_finish"] = late_finish[task_id]
            if task["is_critical"]:
                critical_path.append(task_id)
        critical_path.sort(key=lambda tid: self.tasks[tid]["start_day"])
        print(f"  На критическом пути: {len(critical_path)} фаз")
        for tid in critical_path:
            t = self.tasks[tid]
            print(f"    * {t['phase']:<35} {t['start_date']} -> {t['finish_date']}  {t['duration_days']} дн.")
        return critical_path

    def _make_task_id(self, phase_name):
        tid = phase_name.lower().strip()
        for ch in " /()":
            tid = tid.replace(ch, "_")
        return tid[:40]

    def save_results(self):
        print("\nСохраняю файлы...")
        project_end  = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0
        finish_date  = (self.start_date + timedelta(days=project_end)).strftime("%Y-%m-%d")
        critical     = sorted(
            [tid for tid, t in self.tasks.items() if t.get("is_critical")],
            key=lambda tid: self.tasks[tid]["start_day"]
        )
        tasks_sorted = sorted(self.tasks.values(), key=lambda t: t["start_day"])

        self._save_json({
            "project":            self.project_name,
            "version":            "3.0",
            "project_start_date": self.start_date.strftime("%Y-%m-%d"),
            "finish_date":        finish_date,
            "total_days":         project_end,
            "total_months":       round(project_end / 30.4, 1),
            "tasks_count":        len(self.tasks),
            "critical_path":      [self.tasks[tid]["phase"] for tid in critical],
            "tasks":              tasks_sorted,
        }, "gpr_schedule.json")

        self._save_json({
            "project":        self.project_name,
            "version":        "3.0",
            "total_days":     project_end,
            "finish_date":    finish_date,
            "critical_tasks": [self.tasks[tid] for tid in critical],
        }, "gpr_critical_path.json")

        self._build_gantt_html(tasks_sorted, set(critical), project_end, finish_date)

    def _build_gantt_html(self, tasks_sorted, critical_set, total_days, finish_date):
        start_str = self.start_date.strftime("%Y-%m-%d")
        rows = ""
        for t in tasks_sorted:
            if t["duration_days"] <= 0:
                continue
            lp  = round(t["start_day"] / total_days * 100, 2)
            wp  = max(round(t["duration_days"] / total_days * 100, 2), 0.4)
            cp  = t["task_id"] in critical_set
            bc  = "#BA7517" if cp else "#378ADD"
            cpb = '<span style="background:#BA7517;color:#fff;font-size:10px;padding:1px 5px;border-radius:3px;margin-left:4px;">КП</span>' if cp else ""
            flt = f'<span style="font-size:11px;color:#999;margin-left:4px;">резерв {t["float_days"]} дн.</span>' if t["float_days"] > 0 else ""
            preds_ids = self.dependencies.get(t["task_id"], [])
            preds_str = ", ".join(self.tasks[p]["phase"] for p in preds_ids if p in self.tasks) or "—"
            rows += f"""
      <tr>
        <td style="padding:6px 10px;font-size:12px;border-bottom:0.5px solid #eee;white-space:nowrap;">{t["phase"]}{cpb}{flt}</td>
        <td style="padding:6px 8px;font-size:12px;text-align:center;border-bottom:0.5px solid #eee;color:#777;">{t["start_date"]}</td>
        <td style="padding:6px 8px;font-size:12px;text-align:center;border-bottom:0.5px solid #eee;color:#777;">{t["finish_date"]}</td>
        <td style="padding:6px 8px;font-size:12px;text-align:center;border-bottom:0.5px solid #eee;">{t["duration_days"]}</td>
        <td style="padding:6px 8px;font-size:12px;color:#999;border-bottom:0.5px solid #eee;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{preds_str}">{preds_str}</td>
        <td style="padding:4px 8px;border-bottom:0.5px solid #eee;min-width:320px;">
          <div style="position:relative;height:20px;background:#f0f0f0;border-radius:3px;">
            <div style="position:absolute;left:{lp}%;width:{wp}%;height:100%;background:{bc};border-radius:3px;min-width:3px;"></div>
          </div>
        </td>
      </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>ГПР — AINTELLECTUM</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:#fafafa;color:#1a1a1a;padding:24px}}
h1{{font-size:18px;font-weight:500;margin-bottom:4px}}
.sub{{font-size:13px;color:#888;margin-bottom:20px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}}
.card{{background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;padding:12px 16px}}
.cl{{font-size:11px;color:#999;margin-bottom:4px}}
.cv{{font-size:20px;font-weight:500}}
.legend{{display:flex;gap:20px;margin-bottom:12px;font-size:12px;color:#666;align-items:center}}
.ld{{width:12px;height:12px;border-radius:2px;flex-shrink:0}}
table{{width:100%;border-collapse:collapse;background:#fff;border:0.5px solid #e0e0e0;border-radius:8px;overflow:hidden}}
thead tr{{background:#f5f5f5}}
th{{padding:8px 10px;font-size:12px;font-weight:500;text-align:left;border-bottom:0.5px solid #e0e0e0}}
tr:hover{{background:#fafafa}}
.footer{{margin-top:16px;font-size:11px;color:#bbb;text-align:right}}
</style></head><body>
<h1>ГПР — Школа №65, Уральск</h1>
<div class="sub">AINTELLECTUM · GPR Builder v3.0 · CPM + Kahn · Старт: {start_str}</div>
<div class="cards">
  <div class="card"><div class="cl">Старт</div><div class="cv">{start_str}</div></div>
  <div class="card"><div class="cl">Финиш</div><div class="cv">{finish_date}</div></div>
  <div class="card"><div class="cl">Длительность</div><div class="cv">{total_days} дн.</div></div>
  <div class="card"><div class="cl">Месяцев</div><div class="cv">{round(total_days/30.4,1)}</div></div>
</div>
<div class="legend">
  <span style="display:flex;align-items:center;gap:6px;"><span class="ld" style="background:#378ADD;"></span>Обычная фаза</span>
  <span style="display:flex;align-items:center;gap:6px;"><span class="ld" style="background:#BA7517;"></span>Критический путь</span>
</div>
<table>
  <thead><tr><th>Фаза</th><th>Старт</th><th>Финиш</th><th>Дней</th><th>После</th><th>Диаграмма Ганта</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<div class="footer">AINTELLECTUM GPR Builder v3.0 · Ереке · Аян · Claude</div>
</body></html>"""

        with open("gantt_chart.html", "w", encoding="utf-8") as f:
            f.write(html)
        size = Path("gantt_chart.html").stat().st_size
        print(f"  OK gantt_chart.html: {size//1024} KB -> открой в браузере")

    def _save_json(self, data, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size = Path(path).stat().st_size
        print(f"  OK {path}: {size/1024:.1f} KB")

    def print_summary(self):
        project_end = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0
        finish_date = (self.start_date + timedelta(days=project_end)).strftime("%d.%m.%Y")
        critical    = [tid for tid, t in self.tasks.items() if t.get("is_critical")]
        print()
        print("=" * 68)
        print("  GPR BUILDER v3.0 - РЕЗУЛЬТАТ")
        print("=" * 68)
        print(f"  Старт:        {self.start_date.strftime('%d.%m.%Y')}")
        print(f"  Финиш:        {finish_date}")
        print(f"  Длительность: {project_end} дн. = {round(project_end/30.4,1)} мес.")
        print(f"  Задач в ГПР:  {len(self.tasks)}")
        print(f"  Крит. путь:   {len(critical)} фаз")
        print()
        print(f"  {'Фаза':<38} {'Старт':<12} {'Финиш':<12} {'Дн':>5}  Рез.")
        print(f"  {'-'*70}")
        for t in sorted(self.tasks.values(), key=lambda t: t["start_day"]):
            if t["duration_days"] == 0:
                continue
            cp  = " *" if t.get("is_critical") else "  "
            flt = f" [{t['float_days']} д.]" if t.get("float_days", 0) > 0 else ""
            print(f"  {t['phase']:<38} {t['start_date']:<12} {t['finish_date']:<12} {t['duration_days']:>5}{cp}{flt}")
        print()
        print("  * = критический путь")
        print("  Файлы: gpr_schedule.json, gpr_critical_path.json, gantt_chart.html")
        print("=" * 68)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AINTELLECTUM GPR Builder v3.0")
    parser.add_argument("--summary",    default="duration_summary.json")
    parser.add_argument("--start-date", default="2025-01-01")
    args = parser.parse_args()

    print("=" * 68)
    print("  GPR BUILDER v3.0 - AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  Алгоритм: CPM + Kahn Topological Sort")
    print("=" * 68)

    builder = GPRBuilder(summary_path=args.summary, start_date=args.start_date)
    builder.load_inputs()
    builder.build_tasks()
    builder.build_dependency_graph()
    builder.topological_sort()
    builder.calculate_schedule()
    builder.detect_critical_path()
    builder.save_results()
    builder.print_summary()