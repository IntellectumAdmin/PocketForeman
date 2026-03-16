# -*- coding: utf-8 -*-
"""
GANTT EXPORTER v1.0
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

ЗАДАЧА:
Визуализировать результаты GPR Builder как диаграмму Ганта.

ВХОД:
  gpr_schedule.json
  gpr_calendar.json
  gpr_critical_path.json

ВЫХОД:
  gantt_tasks.csv       — таблица задач для Excel
  gantt_phases.csv      — таблица фаз для Excel
  gantt_chart.html      — диаграмма Ганта в браузере

ЦВЕТА:
  🔵 Синий   — обычная задача
  🔴 Красный — критический путь ★
  🟠 Оранжевый — auto_corrected ⚠
  🟡 Жёлтый — suspicious

ИСПОЛЬЗОВАНИЕ:
  python gantt_exporter.py
  python gantt_exporter.py --start-date 2025-01-01
"""

import json
import csv
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta


class GanttExporter:

    def __init__(
        self,
        gpr_schedule_path:      str = "gpr_schedule.json",
        gpr_calendar_path:      str = "gpr_calendar.json",
        gpr_critical_path_path: str = "gpr_critical_path.json",
        start_date_override:    str = None,
    ):
        self.gpr_schedule_path      = Path(gpr_schedule_path)
        self.gpr_calendar_path      = Path(gpr_calendar_path)
        self.gpr_critical_path_path = Path(gpr_critical_path_path)
        self.start_date_override    = start_date_override

        self.gpr_schedule     = {}
        self.gpr_calendar     = {}
        self.gpr_critical     = {}

        self.project_name     = "unknown"
        self.project_start    = None
        self.project_end_day  = 0

        self.tasks:  List[Dict] = []
        self.phases: List[Dict] = []

    # ═══════════════════════════════════════════════════════════
    # ЗАГРУЗКА
    # ═══════════════════════════════════════════════════════════
    def load_inputs(self):
        print("Загружаю входные файлы...")
        self.gpr_schedule = self._load_json(self.gpr_schedule_path)
        self.gpr_calendar = self._load_json(self.gpr_calendar_path)
        self.gpr_critical  = self._load_json(self.gpr_critical_path_path)

        self.project_name = (
            self.gpr_schedule.get("project") or
            self.gpr_calendar.get("project") or "unknown"
        )

        # Дата старта — из файла или override
        start_str = (
            self.start_date_override or
            self.gpr_schedule.get("project_start_date") or
            self.gpr_schedule.get("start_date")
        )
        if start_str:
            self.project_start = datetime.strptime(start_str, "%Y-%m-%d")
        else:
            self.project_start = datetime(2025, 1, 1)
            print("  ⚠️ start_date не найдена, использую 2025-01-01")

        self.project_end_day = self.gpr_schedule.get("total_days", 0)

        print(f"  Проект:   {self.project_name}")
        print(f"  Старт:    {self.project_start.strftime('%d.%m.%Y')}")
        print(f"  Задач:    {len(self.gpr_schedule.get('tasks', []))}")
        print(f"  Горизонт: {self.project_end_day} дн.")

    def _load_json(self, path: Path) -> Dict:
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ═══════════════════════════════════════════════════════════
    # ПОДГОТОВКА ДАННЫХ
    # ═══════════════════════════════════════════════════════════
    def prepare_data(self):
        print("\nПодготавливаю данные...")
        self._prepare_tasks()
        self._prepare_phases()
        print(f"  Задач: {len(self.tasks)} | Фаз: {len(self.phases)}")

    def _prepare_tasks(self):
        self.tasks = []
        for t in self.gpr_schedule.get("tasks", []):
            start_day  = t.get("start_day",  t.get("early_start",  0))
            finish_day = t.get("finish_day", t.get("early_finish", 0))
            if t.get("duration_days", 0) == 0:
                continue
            self.tasks.append({
                "task_id":        t.get("task_id", ""),
                "phase":          t.get("phase", ""),
                "subsection_name": t.get("subsection_name", t.get("phase", "")),
                "title":          t.get("phase", ""),
                "start_day":      start_day,
                "finish_day":     finish_day,
                "start_date":     self._to_date(start_day),
                "finish_date":    self._to_date(finish_day),
                "duration_days":  t.get("duration_days", 0),
                "is_critical":    t.get("is_critical", False),
                "duration_status": t.get("data_quality", t.get("duration_status", "ok")),
                "float_days":     t.get("float_days", t.get("total_float", 0)),
            })
        self.tasks.sort(key=lambda x: (x["start_day"], x["phase"]))

    def _prepare_phases(self):
        self.phases = []
        calendar = self.gpr_calendar.get("calendar", [])
        if calendar:
            for p in calendar:
                start_day  = p.get("start_day", 0)
                finish_day = p.get("finish_day", 0)
                self.phases.append({
                    "phase":           p.get("phase", ""),
                    "start_day":       start_day,
                    "finish_day":      finish_day,
                    "start_date":      self._to_date(start_day),
                    "finish_date":     self._to_date(finish_day),
                    "duration_days":   finish_day - start_day,
                    "tasks_count":     p.get("tasks_count", 0),
                    "critical_count":  p.get("critical_tasks_count", 0),
                })
        else:
            # Строим фазы из tasks
            phase_map: Dict[str, Dict] = {}
            for t in self.tasks:
                ph = t["phase"]
                if ph not in phase_map:
                    phase_map[ph] = {
                        "phase": ph,
                        "start_day": t["start_day"],
                        "finish_day": t["finish_day"],
                        "tasks_count": 0,
                        "critical_count": 0,
                    }
                phase_map[ph]["start_day"]  = min(phase_map[ph]["start_day"],  t["start_day"])
                phase_map[ph]["finish_day"] = max(phase_map[ph]["finish_day"], t["finish_day"])
                phase_map[ph]["tasks_count"] += 1
                if t["is_critical"]:
                    phase_map[ph]["critical_count"] += 1
            for ph, data in sorted(phase_map.items(), key=lambda x: x[1]["start_day"]):
                data["start_date"]  = self._to_date(data["start_day"])
                data["finish_date"] = self._to_date(data["finish_day"])
                data["duration_days"] = data["finish_day"] - data["start_day"]
                self.phases.append(data)

        self.phases.sort(key=lambda x: x["start_day"])

    def _to_date(self, day: int) -> str:
        return (self.project_start + timedelta(days=day)).strftime("%Y-%m-%d")

    # ═══════════════════════════════════════════════════════════
    # CSV ЭКСПОРТ
    # ═══════════════════════════════════════════════════════════
    def export_csv(self):
        print("\nЭкспортирую CSV...")

        # gantt_tasks.csv
        fields_tasks = ["task_id","phase","subsection_name","start_date","finish_date",
                        "duration_days","is_critical","duration_status","float_days"]
        with open("gantt_tasks.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields_tasks, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.tasks)
        print(f"  ✓ gantt_tasks.csv ({len(self.tasks)} задач)")

        # gantt_phases.csv
        fields_phases = ["phase","start_date","finish_date","duration_days","tasks_count","critical_count"]
        with open("gantt_phases.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields_phases, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.phases)
        print(f"  ✓ gantt_phases.csv ({len(self.phases)} фаз)")

    # ═══════════════════════════════════════════════════════════
    # HTML ДИАГРАММА ГАНТА
    # ═══════════════════════════════════════════════════════════
    def export_html(self):
        print("\nСтрою HTML диаграмму Ганта...")
        html = self._build_html()
        with open("gantt_chart.html", "w", encoding="utf-8") as f:
            f.write(html)
        size = Path("gantt_chart.html").stat().st_size
        print(f"  ✓ gantt_chart.html ({size//1024} КБ) — открой в браузере!")

    def _build_html(self) -> str:
        end_day    = max(self.project_end_day, 1)
        finish_dt  = self.project_start + timedelta(days=end_day)
        months     = self._get_months(end_day)
        n_months   = max(len(months), 1)

        critical_ids = {
            t.get("task_id", "")
            for t in self.gpr_critical.get("critical_tasks", [])
        }
        critical_phases = {
            t["phase"] for t in self.tasks
            if t.get("is_critical") or t["task_id"] in critical_ids
        }

        def bar(start_day, finish_day, label, css_cls, tooltip=""):
            left  = round(start_day  / end_day * 100, 2)
            width = max(round((finish_day - start_day) / end_day * 100, 2), 0.5)
            return (f'<div class="bar {css_cls}" '
                    f'style="left:{left}%;width:{width}%;" '
                    f'title="{tooltip}">{label}</div>')

        def task_css(t):
            s = t.get("duration_status", "ok")
            if s == "auto_corrected": return "corrected"
            if s == "suspicious":     return "suspicious"
            if t.get("is_critical") or t["task_id"] in critical_ids: return "critical"
            return "normal"

        def marker(t):
            s = t.get("duration_status", "ok")
            if s == "auto_corrected": return " ⚠"
            if s == "suspicious":     return " ?"
            if t.get("is_critical"):  return " ★"
            return ""

        # Шапка месяцев
        month_header = "".join(
            f'<div class="mcell">{m}</div>' for m in months
        )

        # Строки фаз
        phase_rows = ""
        for p in self.phases:
            is_crit = p["phase"] in critical_phases
            css = "phase-critical" if is_crit else "phase-bar"
            lbl = f'{p["phase"]} ({p["duration_days"]}д.)'
            tip = f'{p["phase"]}: {p["start_date"]} → {p["finish_date"]}'
            b   = bar(p["start_day"], p["finish_day"], lbl, css, tip)
            star = " ★" if is_crit else ""
            phase_rows += f'''
            <div class="row">
                <div class="lbl">{p["phase"]}{star} <span class="meta">{p["duration_days"]} дн.</span></div>
                <div class="bars" style="--nm:{n_months}">{b}</div>
            </div>'''

        # Строки задач
        task_rows = ""
        for t in self.tasks:
            css = task_css(t)
            lbl = t["subsection_name"] or t["phase"]
            tip = f'{t["phase"]} | {lbl}: {t["start_date"]} → {t["finish_date"]} ({t["duration_days"]} дн.)'
            b   = bar(t["start_day"], t["finish_day"], lbl, css, tip)
            mk  = marker(t)
            task_rows += f'''
            <div class="row">
                <div class="lbl">{t["phase"]} | {lbl}{mk} <span class="meta">{t["duration_days"]} дн.</span></div>
                <div class="bars" style="--nm:{n_months}">{b}</div>
            </div>'''

        # Критический путь список
        cp_list = ""
        for t in sorted(self.tasks, key=lambda x: x["start_day"]):
            if t.get("is_critical") or t["task_id"] in critical_ids:
                cp_list += f'<li><b>{t["phase"]}</b> — {t["duration_days"]} дн. ({t["start_date"]} → {t["finish_date"]})</li>'

        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>ГПР — {self.project_name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Arial,sans-serif;background:#f4f4f4;color:#222;padding:20px}}
h1{{margin-bottom:6px;font-size:22px}}
h2{{margin:24px 0 8px;font-size:16px;color:#444}}
.summary{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:16px;
  margin-bottom:20px;display:flex;flex-wrap:wrap;gap:20px}}
.stat{{font-size:14px}}.stat b{{font-size:18px;display:block;color:#333}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin-top:12px;align-items:center}}
.leg{{display:flex;align-items:center;gap:6px;font-size:13px}}
.sw{{width:20px;height:12px;border-radius:3px;display:inline-block}}
.sw-n{{background:#5b8dd9}}.sw-c{{background:#d9534f}}
.sw-a{{background:#f0ad4e}}.sw-s{{background:#f7e463;border:1px solid #aaa}}

.gantt{{background:#fff;border:1px solid #ddd;border-radius:8px;
  padding:12px;overflow-x:auto;margin-bottom:30px}}
.grid{{min-width:900px}}
.mheader{{display:flex;border-bottom:2px solid #ddd;margin-bottom:4px}}
.mlabel{{width:280px;flex-shrink:0;font-weight:bold;font-size:13px;padding:4px 8px}}
.mmonths{{flex:1;display:flex}}
.mcell{{flex:1;text-align:center;font-size:11px;color:#666;
  border-left:1px solid #eee;padding:4px 2px;white-space:nowrap}}

.row{{display:flex;min-height:32px;border-bottom:1px solid #f0f0f0;align-items:center}}
.row:hover{{background:#fafafa}}
.lbl{{width:280px;flex-shrink:0;font-size:12px;padding:4px 8px;
  border-right:1px solid #eee;line-height:1.4;word-break:break-word}}
.meta{{color:#999;font-size:11px}}
.bars{{flex:1;position:relative;height:24px;
  background-image:repeating-linear-gradient(to right,
    transparent, transparent calc(100%/var(--nm) - 1px),
    #f0f0f0 calc(100%/var(--nm) - 1px), #f0f0f0 calc(100%/var(--nm)))}}

.bar{{position:absolute;top:3px;height:18px;border-radius:3px;
  font-size:10px;line-height:18px;color:#fff;
  padding:0 4px;overflow:hidden;white-space:nowrap;cursor:default}}
.bar.normal{{background:#5b8dd9}}
.bar.critical{{background:#d9534f}}
.bar.corrected{{background:#f0ad4e;color:#222}}
.bar.suspicious{{background:#f7e463;color:#222;border:1px solid #ccc}}
.bar.phase-bar{{background:#5cb85c}}
.bar.phase-critical{{background:#a30000}}

.cp-list{{background:#fff7f7;border:1px solid #fcc;border-radius:8px;
  padding:16px;margin-bottom:20px}}
.cp-list li{{margin:4px 0;font-size:14px;list-style:none;padding-left:12px}}
.cp-list li::before{{content:"→ ";color:#d9534f;font-weight:bold}}
</style>
</head>
<body>
<h1>📅 ГПР — {self.project_name}</h1>

<div class="summary">
  <div class="stat"><b>{self.project_start.strftime('%d.%m.%Y')}</b>Дата старта</div>
  <div class="stat"><b>{finish_dt.strftime('%d.%m.%Y')}</b>Дата финиша</div>
  <div class="stat"><b>{end_day} дн.</b>Длительность</div>
  <div class="stat"><b>{end_day//30} мес. / {end_day/365:.1f} лет</b>В месяцах</div>
  <div class="stat"><b>{len(self.tasks)}</b>Задач</div>
  <div class="stat"><b>{len(self.phases)}</b>Фаз</div>
  <div class="legend">
    <div class="leg"><span class="sw sw-n"></span> Обычная</div>
    <div class="leg"><span class="sw sw-c"></span> Критический путь ★</div>
    <div class="leg"><span class="sw sw-a"></span> Автоисправлено ⚠</div>
    <div class="leg"><span class="sw sw-s"></span> Подозрительно ?</div>
  </div>
</div>

<div class="cp-list">
  <h2>★ Критический путь</h2>
  <ul>{cp_list}</ul>
</div>

<h2>Фазы проекта</h2>
<div class="gantt">
<div class="grid">
  <div class="mheader">
    <div class="mlabel">Фаза</div>
    <div class="mmonths">{month_header}</div>
  </div>
  {phase_rows}
</div>
</div>

<h2>Задачи (подразделы)</h2>
<div class="gantt">
<div class="grid">
  <div class="mheader">
    <div class="mlabel">Задача</div>
    <div class="mmonths">{month_header}</div>
  </div>
  {task_rows}
</div>
</div>

<p style="color:#999;font-size:12px;margin-top:20px">
  Сгенерировано: AINTELLECTUM GPR Builder v1.0 &nbsp;|&nbsp;
  Архитектура: Аян &nbsp;|&nbsp; Разработка: Claude &nbsp;|&nbsp; Капитан: Ереке
</p>
</body>
</html>"""

    def _get_months(self, total_days: int) -> List[str]:
        months = []
        cur = datetime(self.project_start.year, self.project_start.month, 1)
        end = self.project_start + timedelta(days=total_days + 31)
        while cur <= end:
            months.append(cur.strftime("%m.%Y"))
            cur = datetime(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
        return months

    # ═══════════════════════════════════════════════════════════
    # ИТОГ
    # ═══════════════════════════════════════════════════════════
    def print_summary(self):
        end_day   = self.project_end_day
        finish_dt = self.project_start + timedelta(days=end_day)
        critical  = sum(1 for t in self.tasks if t.get("is_critical"))
        print()
        print("=" * 60)
        print("GANTT EXPORTER v1.0 — ГОТОВО!")
        print("=" * 60)
        print(f"Проект:       {self.project_name}")
        print(f"Старт:        {self.project_start.strftime('%d.%m.%Y')}")
        print(f"Финиш:        {finish_dt.strftime('%d.%m.%Y')}")
        print(f"Длительность: {end_day} дн. ({end_day//30} мес.)")
        print(f"Задач:        {len(self.tasks)}")
        print(f"Критических:  {critical}")
        print()
        print("📁 Файлы:")
        print("  - gantt_tasks.csv    (задачи для Excel)")
        print("  - gantt_phases.csv   (фазы для Excel)")
        print("  - gantt_chart.html   ← ОТКРОЙ В БРАУЗЕРЕ!")
        print()
        print("🚀 AINTELLECTUM: PDF → Смета → Иерархия → ГПР → Диаграмма Ганта ✅")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AINTELLECTUM Gantt Exporter v1.0")
    parser.add_argument("--gpr-schedule",      default="gpr_schedule.json")
    parser.add_argument("--gpr-calendar",      default="gpr_calendar.json")
    parser.add_argument("--gpr-critical-path", default="gpr_critical_path.json")
    parser.add_argument("--start-date",        default=None,
                        help="Дата старта YYYY-MM-DD (переопределяет данные из файла)")
    args = parser.parse_args()

    print("=" * 60)
    print("GANTT EXPORTER v1.0 — AINTELLECTUM")
    print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("=" * 60)
    print()

    exporter = GanttExporter(
        gpr_schedule_path=args.gpr_schedule,
        gpr_calendar_path=args.gpr_calendar,
        gpr_critical_path_path=args.gpr_critical_path,
        start_date_override=args.start_date,
    )
    exporter.load_inputs()
    exporter.prepare_data()
    exporter.export_csv()
    exporter.export_html()
    exporter.print_summary()