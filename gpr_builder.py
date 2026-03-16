# -*- coding: utf-8 -*-
"""
GPR BUILDER v1.0
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

НАЗНАЧЕНИЕ:
  Строит График Производства Работ (ГПР) из длительностей.
  Реализует Critical Path Method (CPM).

PIPELINE:
  duration_estimates.json + section_hierarchy.json
        ↓
  [1] Загрузка длительностей
        ↓
  [2] Построение графа зависимостей (DAG)
        ↓
  [3] Топологическая сортировка (Kahn's algorithm)
        ↓
  [4] Forward pass → start/finish days
        ↓
  [5] Critical Path Method (CPM)
        ↓
  gpr_schedule.json       — полный ГПР
  gpr_calendar.json       — календарь по месяцам
  gpr_critical_path.json  — критический путь
  gpr_summary.json        — итог для инженера

ИСПОЛЬЗОВАНИЕ:
  python gpr_builder.py
  python gpr_builder.py --start-date 2024-01-15
  python gpr_builder.py --verbose
"""

import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict, deque
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════════
# ГРАФ ЗАВИСИМОСТЕЙ
#
# Строительная логика: каждая фаза зависит от предыдущей.
# Основан на реальной последовательности строительства.
#
# Аян: "foundation → frame → roof → finishing"
# ═══════════════════════════════════════════════════════════════
DEPENDENCY_RULES = [
    # Формат: (фаза, зависит от фазы)
    # Нулевой уровень — начало строительства
    ("земляные работы",                []),
    ("фундаменты",                     ["земляные работы"]),
    ("монолитный каркас",              ["фундаменты"]),
    ("плиты перекрытия и балки",       ["монолитный каркас"]),
    ("лестницы",                       ["монолитный каркас"]),
    ("металлоконструкции",             ["фундаменты"]),
    ("стены и перегородки",            ["монолитный каркас", "плиты перекрытия и балки"]),
    ("кровля и парапеты",              ["монолитный каркас", "стены и перегородки"]),
    ("проемы и заполнение",            ["стены и перегородки", "кровля и парапеты"]),
    ("крыльца и козырьки",             ["фундаменты", "стены и перегородки"]),
    # Инженерные сети — после закрытия коробки
    ("водоснабжение и канализация",    ["стены и перегородки", "проемы и заполнение"]),
    ("отопление и теплоснабжение",     ["стены и перегородки", "проемы и заполнение"]),
    ("вентиляция и кондиционирование", ["стены и перегородки", "проемы и заполнение"]),
    ("электроснабжение и электрооборудование", ["стены и перегородки", "проемы и заполнение"]),
    ("котельная",                      ["отопление и теплоснабжение"]),
    ("лифтовое оборудование",          ["монолитный каркас", "стены и перегородки"]),
    # Отделка — после инженерки
    ("полы",                           ["стены и перегородки", "водоснабжение и канализация"]),
    ("внутренняя отделка",             ["стены и перегородки", "проемы и заполнение",
                                        "водоснабжение и канализация"]),
    # Специальные помещения
    ("оснащение учебных кабинетов",    ["внутренняя отделка", "электроснабжение и электрооборудование"]),
    ("административные помещения",    ["внутренняя отделка"]),
    ("спортивные и актовые залы",      ["внутренняя отделка", "полы"]),
    ("медицинские и специальные помещения", ["внутренняя отделка"]),
    ("пищеблок",                       ["внутренняя отделка", "водоснабжение и канализация",
                                        "вентиляция и кондиционирование"]),
    ("санитарные помещения",           ["внутренняя отделка", "водоснабжение и канализация"]),
    ("прочее оборудование и мебель",   ["внутренняя отделка", "оснащение учебных кабинетов"]),
    # Благоустройство — в конце
    ("благоустройство территории",     ["кровля и парапеты", "крыльца и козырьки"]),
    ("малые архитектурные формы",      ["благоустройство территории"]),
]


class GPRBuilder:

    def __init__(
        self,
        duration_estimates_path: str = "duration_estimates.json",
        hierarchy_path:          str = "section_hierarchy.json",
        start_date:              str = None,
    ):
        self.duration_estimates_path = Path(duration_estimates_path)
        self.hierarchy_path          = Path(hierarchy_path)
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime(2025, 1, 1)

        self.duration_estimates = {}
        self.hierarchy          = {}

        # Задачи ГПР
        self.tasks: Dict[str, Dict[str, Any]] = {}
        # task_id → [зависимые task_id]
        self.dependencies: Dict[str, List[str]] = {}
        # Порядок выполнения
        self.sorted_tasks: List[str] = []
        self.project_name = "unknown"

    # ═══════════════════════════════════════════════════════════
    # ЗАГРУЗКА
    # ═══════════════════════════════════════════════════════════
    def load_inputs(self):
        print("Загружаю входные данные...")

        with open(self.duration_estimates_path, encoding="utf-8") as f:
            data = json.load(f)
        self.duration_estimates = data
        self.project_name = data.get("project", "unknown")

        if self.hierarchy_path.exists():
            with open(self.hierarchy_path, encoding="utf-8") as f:
                self.hierarchy = json.load(f)

        estimates = data.get("estimates", [])
        print(f"  Проект:    {self.project_name}")
        print(f"  Оценок:    {len(estimates)}")
        print(f"  Старт:     {self.start_date.strftime('%d.%m.%Y')}")

    # ═══════════════════════════════════════════════════════════
    # ПОСТРОЕНИЕ ЗАДАЧ ГПР
    # ═══════════════════════════════════════════════════════════
    def build_tasks(self):
        """
        Агрегируем duration_estimates по фазам → задачи ГПР.
        Одна фаза = одна задача ГПР.
        """
        print("\nСтрою задачи ГПР...")

        phase_data: Dict[str, Dict] = {}

        for est in self.duration_estimates.get("estimates", []):
            phase = est.get("phase", "").strip()
            days  = est.get("duration_days") or 0

            if phase not in phase_data:
                phase_data[phase] = {
                    "total_days":  0,
                    "subsections": [],
                    "statuses":    [],
                }

            phase_data[phase]["total_days"]  += days
            phase_data[phase]["subsections"].append(est.get("subsection_name", ""))
            phase_data[phase]["statuses"].append(est.get("duration_status", "ok"))

        # Создаём задачи
        for phase_name, data in phase_data.items():
            task_id = self._make_task_id(phase_name)
            has_auto_corrected = "auto_corrected" in data["statuses"]
            has_suspicious     = "suspicious"     in data["statuses"]

            self.tasks[task_id] = {
                "task_id":            task_id,
                "phase":              phase_name,
                "duration_days":      data["total_days"],
                "subsections_count":  len(data["subsections"]),
                "data_quality":       "auto_corrected" if has_auto_corrected
                                      else ("suspicious" if has_suspicious else "ok"),
                # Заполним при расчёте
                "start_day":          0,
                "finish_day":         0,
                "start_date":         None,
                "finish_date":        None,
                "is_critical":        False,
                "float_days":         0,
            }

        print(f"  Задач ГПР: {len(self.tasks)}")

    # ═══════════════════════════════════════════════════════════
    # ГРАФ ЗАВИСИМОСТЕЙ
    # ═══════════════════════════════════════════════════════════
    def build_dependency_graph(self):
        """
        Строит граф зависимостей на основе DEPENDENCY_RULES.
        Если фаза не найдена в правилах — добавляем без зависимостей.
        """
        print("\nСтрою граф зависимостей...")

        # Инициализируем все задачи без зависимостей
        for task_id in self.tasks:
            self.dependencies[task_id] = []

        # Применяем правила
        matched = 0
        for phase_norm, dep_norms in DEPENDENCY_RULES:
            # Ищем задачу по нормализованному имени
            task_id = self._find_task_by_norm(phase_norm)
            if task_id is None:
                continue

            for dep_norm in dep_norms:
                dep_id = self._find_task_by_norm(dep_norm)
                if dep_id and dep_id != task_id:
                    if dep_id not in self.dependencies[task_id]:
                        self.dependencies[task_id].append(dep_id)

            matched += 1

        # Задачи без зависимостей и без зависящих → независимые
        total_deps = sum(len(v) for v in self.dependencies.values())
        print(f"  Правил применено:  {matched}")
        print(f"  Связей в графе:    {total_deps}")

        # Диагностика: задачи без зависимостей (стартовые)
        start_tasks = [tid for tid, deps in self.dependencies.items() if not deps]
        print(f"  Стартовых задач:   {len(start_tasks)}")

    def _find_task_by_norm(self, phase_norm: str) -> Optional[str]:
        """Ищет task_id по нормализованному имени фазы."""
        phase_norm_lower = phase_norm.lower().strip()
        for task_id, task in self.tasks.items():
            if task["phase"].lower().strip() == phase_norm_lower:
                return task_id
            # Частичное совпадение
            if phase_norm_lower in task["phase"].lower():
                return task_id
        return None

    # ═══════════════════════════════════════════════════════════
    # ТОПОЛОГИЧЕСКАЯ СОРТИРОВКА (алгоритм Кана)
    # ═══════════════════════════════════════════════════════════
    def topological_sort(self) -> bool:
        """
        Алгоритм Кана для топологической сортировки DAG.
        Возвращает False если есть цикл (не должно быть).
        """
        print("\nТопологическая сортировка...")

        # Считаем входящие рёбра для каждой задачи
        in_degree: Dict[str, int] = {tid: 0 for tid in self.tasks}
        # Строим список "кто зависит от меня"
        dependents: Dict[str, List[str]] = {tid: [] for tid in self.tasks}

        for task_id, deps in self.dependencies.items():
            for dep_id in deps:
                in_degree[task_id] += 1
                dependents[dep_id].append(task_id)

        # Начинаем с задач без зависимостей
        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        self.sorted_tasks = []

        while queue:
            task_id = queue.popleft()
            self.sorted_tasks.append(task_id)

            for dependent in dependents[task_id]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(self.sorted_tasks) != len(self.tasks):
            print("  ⚠️ Обнаружен цикл в графе зависимостей!")
            # Добавляем оставшиеся задачи в конец
            remaining = set(self.tasks.keys()) - set(self.sorted_tasks)
            self.sorted_tasks.extend(remaining)
            return False

        print(f"  Порядок выполнения: {len(self.sorted_tasks)} задач")
        return True

    # ═══════════════════════════════════════════════════════════
    # РАСЧЁТ РАСПИСАНИЯ (Forward Pass)
    #
    # Аян: "start = max(finish(dependencies))"
    # ═══════════════════════════════════════════════════════════
    def calculate_schedule(self):
        """
        Forward pass: рассчитывает start_day и finish_day для каждой задачи.
        start_day = max(finish_day всех зависимостей)
        finish_day = start_day + duration_days
        """
        print("\nРассчитываю расписание (Forward Pass)...")

        for task_id in self.sorted_tasks:
            task = self.tasks[task_id]
            deps = self.dependencies.get(task_id, [])

            # start = после завершения всех зависимостей
            if deps:
                start_day = max(
                    self.tasks[dep]["finish_day"]
                    for dep in deps
                    if dep in self.tasks
                )
            else:
                start_day = 0

            finish_day = start_day + task["duration_days"]

            task["start_day"]  = start_day
            task["finish_day"] = finish_day

            # Конвертируем в календарные даты
            task["start_date"]  = (self.start_date + timedelta(days=start_day)).strftime("%Y-%m-%d")
            task["finish_date"] = (self.start_date + timedelta(days=finish_day)).strftime("%Y-%m-%d")

        # Общая длительность проекта
        total_days = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0
        finish_date = self.start_date + timedelta(days=total_days)

        print(f"  Общая длительность: {total_days} дн. ({total_days//30} мес.)")
        print(f"  Дата завершения:    {finish_date.strftime('%d.%m.%Y')}")

        return total_days

    # ═══════════════════════════════════════════════════════════
    # КРИТИЧЕСКИЙ ПУТЬ (CPM — Backward Pass)
    #
    # Аян: "backward pass для поиска critical path"
    #
    # Логика:
    #   Late Finish = min(Late Start зависящих задач)
    #   Late Start  = Late Finish - duration
    #   Float       = Late Start - Early Start
    #   Critical    = Float == 0
    # ═══════════════════════════════════════════════════════════
    def detect_critical_path(self):
        """
        Реализует Backward Pass алгоритма CPM.
        Задачи с Float=0 — критические.
        """
        print("\nИщу критический путь (CPM Backward Pass)...")

        # Максимальный день проекта
        project_end = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0

        # Строим: кто зависит от каждой задачи
        dependents: Dict[str, List[str]] = {tid: [] for tid in self.tasks}
        for task_id, deps in self.dependencies.items():
            for dep_id in deps:
                dependents[dep_id].append(task_id)

        # Инициализация Late Finish/Start
        late_finish: Dict[str, int] = {}
        late_start:  Dict[str, int] = {}

        # Backward pass — идём в обратном порядке
        for task_id in reversed(self.sorted_tasks):
            task = self.tasks[task_id]
            deps_of_me = dependents[task_id]  # задачи которые зависят от меня

            if not deps_of_me:
                # Конечная задача — Late Finish = project_end
                late_finish[task_id] = project_end
            else:
                # Late Finish = min(Late Start зависящих задач)
                late_finish[task_id] = min(
                    late_start.get(dep, project_end)
                    for dep in deps_of_me
                )

            late_start[task_id] = late_finish[task_id] - task["duration_days"]

        # Определяем критические задачи (Float = 0)
        critical_path = []
        for task_id, task in self.tasks.items():
            float_days = late_start[task_id] - task["start_day"]
            float_days = max(0, float_days)  # не может быть отрицательным
            task["float_days"]   = float_days
            task["is_critical"]  = (float_days == 0 and task["duration_days"] > 0)
            task["late_start"]   = late_start[task_id]
            task["late_finish"]  = late_finish[task_id]

            if task["is_critical"]:
                critical_path.append(task_id)

        # Сортируем критический путь по start_day
        critical_path.sort(key=lambda tid: self.tasks[tid]["start_day"])

        print(f"  Задач на критическом пути: {len(critical_path)}")
        for tid in critical_path:
            t = self.tasks[tid]
            print(f"    → {t['phase']}: {t['duration_days']} дн. "
                  f"({t['start_date']} → {t['finish_date']})")

        return critical_path

    # ═══════════════════════════════════════════════════════════
    # ВСПОМОГАТЕЛЬНЫЕ
    # ═══════════════════════════════════════════════════════════
    def _make_task_id(self, phase_name: str) -> str:
        """Создаёт task_id из имени фазы."""
        tid = phase_name.lower().strip()
        tid = tid.replace(" ", "_").replace("/", "_").replace("и", "i")
        return tid[:40]

    # ═══════════════════════════════════════════════════════════
    # СОХРАНЕНИЕ РЕЗУЛЬТАТОВ
    # ═══════════════════════════════════════════════════════════
    def save_results(self):
        print("\nСохраняю файлы...")

        project_end = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0
        finish_date = (self.start_date + timedelta(days=project_end)).strftime("%Y-%m-%d")
        critical = [tid for tid, t in self.tasks.items() if t.get("is_critical")]
        critical.sort(key=lambda tid: self.tasks[tid]["start_day"])

        # 1. gpr_schedule.json — полный ГПР
        tasks_sorted = sorted(self.tasks.values(), key=lambda t: t["start_day"])
        self._save_json({
            "project":         self.project_name,
            "version":         "1.0",
            "project_start_date": self.start_date.strftime("%Y-%m-%d"),
            "start_date":      self.start_date.strftime("%Y-%m-%d"),
            "finish_date":     finish_date,
            "total_days":      project_end,
            "total_months":    round(project_end / 30, 1),
            "tasks_count":     len(self.tasks),
            "critical_tasks":  len(critical),
            "tasks":           tasks_sorted,
        }, "gpr_schedule.json")

        # 2. gpr_critical_path.json
        cp_tasks = [self.tasks[tid] for tid in critical]
        self._save_json({
            "project":      self.project_name,
            "version":      "1.0",
            "total_days":   project_end,
            "finish_date":  finish_date,
            "critical_path_length": len(critical),
            "critical_tasks": cp_tasks,
        }, "gpr_critical_path.json")

        # 3. gpr_calendar.json — разбивка по месяцам
        calendar = self._build_calendar()
        self._save_json(calendar, "gpr_calendar.json")

        # 4. gpr_summary.json — итог для инженера
        summary = self._build_summary(project_end, finish_date, critical)
        self._save_json(summary, "gpr_summary.json")

    def _build_calendar(self) -> Dict[str, Any]:
        """Строит разбивку активных задач по месяцам."""
        months: Dict[str, List[str]] = {}

        for task in self.tasks.values():
            if not task.get("start_date"):
                continue
            start = datetime.strptime(task["start_date"], "%Y-%m-%d")
            end   = datetime.strptime(task["finish_date"], "%Y-%m-%d")

            # Идём по месяцам от старта до конца задачи
            current = datetime(start.year, start.month, 1)
            while current <= end:
                key = current.strftime("%Y-%m")
                if key not in months:
                    months[key] = []
                months[key].append(task["phase"])
                # Следующий месяц
                if current.month == 12:
                    current = datetime(current.year + 1, 1, 1)
                else:
                    current = datetime(current.year, current.month + 1, 1)

        return {
            "project": self.project_name,
            "version": "1.0",
            "months": [
                {
                    "month": k,
                    "active_phases": v,
                    "active_count": len(v)
                }
                for k, v in sorted(months.items())
            ]
        }

    def _build_summary(self, project_end: int, finish_date: str, critical: List[str]) -> Dict:
        """Читаемый итог для инженера."""
        tasks_by_start = sorted(self.tasks.values(), key=lambda t: t["start_day"])
        critical_set   = set(critical)

        return {
            "project":   self.project_name,
            "version":   "1.0",
            "schedule": {
                "start_date":       self.start_date.strftime("%Y-%m-%d"),
                "finish_date":      finish_date,
                "total_days":       project_end,
                "total_months":     round(project_end / 30, 1),
                "total_years":      round(project_end / 365, 1),
            },
            "critical_path": {
                "length":  len(critical),
                "phases":  [self.tasks[tid]["phase"] for tid in critical],
            },
            "phases": [
                {
                    "phase":        t["phase"],
                    "start_date":   t["start_date"],
                    "finish_date":  t["finish_date"],
                    "duration_days": t["duration_days"],
                    "is_critical":  t["task_id"] in critical_set,
                    "float_days":   t.get("float_days", 0),
                    "data_quality": t.get("data_quality", "ok"),
                }
                for t in tasks_by_start
            ],
            "note": "ГПР построен методом Critical Path Method (CPM). "
                    "Для уточнения: откалибруй production_rates.json по реальным объектам."
        }

    def _save_json(self, data: Any, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size = Path(path).stat().st_size
        print(f"  ✓ {path}: {size/1024:.1f} КБ")

    # ═══════════════════════════════════════════════════════════
    # ИТОГОВЫЙ ОТЧЁТ
    # ═══════════════════════════════════════════════════════════
    def print_summary(self):
        project_end = max(t["finish_day"] for t in self.tasks.values()) if self.tasks else 0
        finish_date = (self.start_date + timedelta(days=project_end)).strftime("%d.%m.%Y")
        critical    = [tid for tid, t in self.tasks.items() if t.get("is_critical")]

        print()
        print("=" * 65)
        print("GPR BUILDER v1.0 — РЕЗУЛЬТАТ")
        print("=" * 65)
        print(f"Проект:         {self.project_name}")
        print(f"Старт:          {self.start_date.strftime('%d.%m.%Y')}")
        print(f"Финиш:          {finish_date}")
        print(f"Длительность:   {project_end} дн. "
              f"({project_end//30} мес. / {project_end/365:.1f} лет)")
        print(f"Задач в ГПР:    {len(self.tasks)}")
        print(f"Критич. путь:   {len(critical)} задач")

        print()
        print("📅 ПЛАН ПО ФАЗАМ:")
        print(f"  {'Фаза':<38} {'Старт':<12} {'Финиш':<12} {'Дн':>5} {'Кр':>4}")
        print(f"  {'─'*38} {'─'*12} {'─'*12} {'─'*5} {'─'*4}")

        tasks_sorted = sorted(self.tasks.values(), key=lambda t: t["start_day"])
        for t in tasks_sorted:
            if t["duration_days"] == 0:
                continue
            crit = " ★" if t.get("is_critical") else ""
            qual = " ⚠" if t.get("data_quality") != "ok" else ""
            print(f"  {t['phase']:<38} "
                  f"{t['start_date']:<12} "
                  f"{t['finish_date']:<12} "
                  f"{t['duration_days']:>5}"
                  f"{crit}{qual}")

        print()
        print("★ = критический путь  ⚠ = данные скорректированы автоматически")
        print()
        print("📁 Файлы:")
        print("  - gpr_schedule.json       (полный ГПР)")
        print("  - gpr_critical_path.json  (критический путь)")
        print("  - gpr_calendar.json       (разбивка по месяцам)")
        print("  - gpr_summary.json        (итог для инженера)")
        print()
        print("🚀 AINTELLECTUM: PDF → Смета → Иерархия → Объёмы → ГПР ✅")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AINTELLECTUM GPR Builder v1.0")
    parser.add_argument("--start-date",         default="2025-01-01",
                        help="Дата начала строительства (YYYY-MM-DD)")
    parser.add_argument("--duration-estimates", default="duration_estimates.json")
    parser.add_argument("--hierarchy",          default="section_hierarchy.json")
    parser.add_argument("--verbose", "-v",      action="store_true")
    args = parser.parse_args()

    print("=" * 65)
    print("GPR BUILDER v1.0 — AINTELLECTUM")
    print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("Алгоритм: Critical Path Method (CPM) + Kahn Topological Sort")
    print("=" * 65)
    print()

    builder = GPRBuilder(
        duration_estimates_path=args.duration_estimates,
        hierarchy_path=args.hierarchy,
        start_date=args.start_date,
    )

    builder.load_inputs()
    builder.build_tasks()
    builder.build_dependency_graph()
    builder.topological_sort()
    total_days = builder.calculate_schedule()
    builder.detect_critical_path()
    builder.save_results()
    builder.print_summary()