# -*- coding: utf-8 -*-
"""
RSNB Registry Builder v1.0
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

Задача:
  Автоматически собирает локальную нормативную базу РСНБ-кодов
  из реальных смет. Источник истины — сами сметы, а не внешний справочник.

Принцип (от Аяна):
  Не ждём внешнюю базу — строим свою из реальных данных.
  Каждая новая смета обогащает registry.
  3 уровня точности: full_code → group_code → type_code

Входные файлы:
  smeta_works_clean.json  (или папка с несколькими файлами)

Выходные файлы:
  rsnb_registry.json       — основная нормативная база
  rsnb_registry_report.json — отчёт о качестве

ИСПОЛЬЗОВАНИЕ:
  python rsnb_registry_builder.py
  python rsnb_registry_builder.py smeta_works_clean.json
  python rsnb_registry_builder.py ./parsed_smetas/
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Optional


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def extract_code_levels(code: str) -> tuple:
    """
    '6103-0201-0114' -> ('6103-0201-0114', '6103-0201', '6103')
    """
    if not code:
        return "", "", ""
    parts = code.split("-")
    full  = code
    group = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else parts[0]
    type_ = parts[0]
    return full, group, type_


def most_common(values: list) -> Optional[str]:
    """Возвращает самое частое значение из списка."""
    if not values:
        return None
    counts = defaultdict(int)
    for v in values:
        if v:
            counts[str(v)] += 1
    if not counts:
        return None
    return max(counts, key=lambda x: counts[x])


def longest_meaningful(values: list) -> Optional[str]:
    """Возвращает самое длинное непустое значение (для названий)."""
    cleaned = [str(v).strip() for v in values if v and str(v).strip()]
    if not cleaned:
        return None
    # Берём самое частое, при равенстве — самое длинное
    counts = defaultdict(int)
    for v in cleaned:
        counts[v] += 1
    max_count = max(counts.values())
    candidates = [v for v, c in counts.items() if c == max_count]
    return max(candidates, key=len)


def calc_confidence(occurrences: int, unit_stable: bool,
                    phase_stable: bool, subgroup_stable: bool) -> float:
    """Вычисляет уверенность в записи реестра."""
    score = 0.5
    if occurrences >= 3:
        score += 0.2
    if unit_stable:
        score += 0.1
    if phase_stable:
        score += 0.1
    if subgroup_stable:
        score += 0.1
    return round(min(1.0, score), 2)


# ─── Основной класс ──────────────────────────────────────────────────────────

class RSNBRegistryBuilder:

    def __init__(self, input_paths: list):
        self.input_paths = input_paths
        self.all_rows = []          # все строки из всех файлов
        self.source_files = []

        self.full_codes = {}        # rsnb_registry["full_codes"]
        self.group_codes = {}       # rsnb_registry["group_codes"]
        self.type_codes = {}        # rsnb_registry["type_codes"]
        self.report = {}

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def load_files(self):
        print("Загружаю файлы смет...")
        for path in self.input_paths:
            p = Path(path)
            if p.is_dir():
                files = list(p.glob("smeta_works*.json")) + \
                        list(p.glob("*_works*.json"))
                for f in files:
                    self._load_one(f)
            elif p.exists():
                self._load_one(p)
            else:
                print(f"  Файл не найден: {path}")

        print(f"  Файлов загружено:  {len(self.source_files)}")
        print(f"  Строк всего:       {len(self.all_rows)}")

    def _load_one(self, path: Path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                rows = data.get("work_items", data.get("works", []))
                if not rows:
                    for v in data.values():
                        if isinstance(v, list):
                            rows = v
                            break
            elif isinstance(data, list):
                rows = data
            else:
                rows = []

            # Добавляем имя файла-источника в каждую строку
            for row in rows:
                if isinstance(row, dict) and row.get("code"):
                    row["_source_file"] = path.name
            self.all_rows.extend([r for r in rows if isinstance(r, dict)])
            self.source_files.append(path.name)
            print(f"  OK {path.name}: {len(rows)} строк")
        except Exception as e:
            print(f"  ОШИБКА {path}: {e}")

    # ── Построение full_codes ─────────────────────────────────────────────────

    def build_full_code_registry(self):
        print("\nСтрою full_codes registry...")

        # Группируем строки по full_code
        by_code = defaultdict(list)
        for row in self.all_rows:
            code = str(row.get("code", "")).strip()
            if code and code.startswith("6"):  # только работы
                by_code[code].append(row)

        for code, rows in by_code.items():
            names     = [r.get("name", "") for r in rows]
            units     = [r.get("unit", "") for r in rows]
            phases    = [r.get("phase", "") for r in rows]
            subgroups = [r.get("subgroup", "") for r in rows]
            sources   = list(set(r.get("_source_file", "") for r in rows))

            canon_name     = longest_meaningful(names)
            canon_unit     = most_common(units)
            canon_phase    = most_common(phases)
            canon_subgroup = most_common(subgroups)

            unit_stable     = len(set(u for u in units if u)) <= 1
            phase_stable    = len(set(p for p in phases if p)) <= 1
            subgroup_stable = len(set(s for s in subgroups if s)) <= 1

            unit_variants  = list(set(u for u in units if u))
            phase_variants = list(set(p for p in phases if p))

            confidence = calc_confidence(
                len(rows), unit_stable, phase_stable, subgroup_stable
            )

            self.full_codes[code] = {
                "canonical_name":     canon_name,
                "canonical_unit":     canon_unit,
                "canonical_phase":    canon_phase,
                "canonical_subgroup": canon_subgroup,
                "occurrences":        len(rows),
                "source_files":       sources,
                "unit_variants":      unit_variants,
                "phase_variants":     phase_variants,
                "unit_stable":        unit_stable,
                "phase_stable":       phase_stable,
                "confidence":         confidence,
            }

        print(f"  full_codes: {len(self.full_codes)}")

    # ── Построение group_codes ────────────────────────────────────────────────

    def build_group_code_registry(self):
        print("Строю group_codes registry...")

        by_group = defaultdict(list)
        for code in self.full_codes:
            _, group, _ = extract_code_levels(code)
            if group:
                by_group[group].append(code)

        for group, subcodes in by_group.items():
            # Агрегируем из full_codes
            all_names  = []
            all_phases = []
            all_units  = []
            for fc in subcodes:
                entry = self.full_codes[fc]
                if entry["canonical_name"]:
                    all_names.append(entry["canonical_name"])
                if entry["canonical_phase"]:
                    all_phases.append(entry["canonical_phase"])
                if entry["canonical_unit"]:
                    all_units.append(entry["canonical_unit"])

            self.group_codes[group] = {
                "canonical_phase": most_common(all_phases),
                "canonical_unit":  most_common(all_units),
                "subcodes_count":  len(subcodes),
                "subcodes":        sorted(subcodes),
                "total_occurrences": sum(
                    self.full_codes[fc]["occurrences"] for fc in subcodes
                ),
            }

        print(f"  group_codes: {len(self.group_codes)}")

    # ── Построение type_codes ─────────────────────────────────────────────────

    def build_type_code_registry(self):
        print("Строю type_codes registry...")

        by_type = defaultdict(list)
        for group in self.group_codes:
            type_code = group.split("-")[0]
            by_type[type_code].append(group)

        for type_code, groups in by_type.items():
            all_phases = []
            all_units  = []
            for g in groups:
                entry = self.group_codes[g]
                if entry["canonical_phase"]:
                    all_phases.append(entry["canonical_phase"])
                if entry["canonical_unit"]:
                    all_units.append(entry["canonical_unit"])

            self.type_codes[type_code] = {
                "canonical_phase":    most_common(all_phases),
                "canonical_unit":     most_common(all_units),
                "group_codes_count":  len(groups),
                "group_codes":        sorted(groups),
                "total_occurrences":  sum(
                    self.group_codes[g]["total_occurrences"] for g in groups
                ),
            }

        print(f"  type_codes:  {len(self.type_codes)}")

    # ── Отчёт о качестве ─────────────────────────────────────────────────────

    def build_report(self):
        stable     = sum(1 for e in self.full_codes.values() if e["confidence"] >= 0.8)
        unit_conf  = sum(1 for e in self.full_codes.values() if len(e["unit_variants"]) > 1)
        phase_conf = sum(1 for e in self.full_codes.values() if len(e["phase_variants"]) > 1)
        single_occ = sum(1 for e in self.full_codes.values() if e["occurrences"] == 1)

        top_unit_conflicts = sorted(
            [{"code": c, "unit_variants": e["unit_variants"]}
             for c, e in self.full_codes.items() if len(e["unit_variants"]) > 1],
            key=lambda x: -len(x["unit_variants"])
        )[:10]

        top_phase_conflicts = sorted(
            [{"code": c, "phase_variants": e["phase_variants"]}
             for c, e in self.full_codes.items() if len(e["phase_variants"]) > 1],
            key=lambda x: -len(x["phase_variants"])
        )[:10]

        self.report = {
            "summary": {
                "source_files_count":   len(self.source_files),
                "source_files":         self.source_files,
                "total_rows_processed": len(self.all_rows),
                "full_codes_found":     len(self.full_codes),
                "group_codes_found":    len(self.group_codes),
                "type_codes_found":     len(self.type_codes),
            },
            "quality": {
                "stable_codes":              stable,
                "stable_pct":                round(stable / max(len(self.full_codes), 1) * 100, 1),
                "codes_with_unit_conflicts": unit_conf,
                "codes_with_phase_conflicts": phase_conf,
                "single_occurrence_codes":   single_occ,
            },
            "top_unit_conflicts":  top_unit_conflicts,
            "top_phase_conflicts": top_phase_conflicts,
        }

    # ── Сохранение ───────────────────────────────────────────────────────────

    def save_results(self):
        print("\nСохраняю файлы...")

        registry = {
            "meta": {
                "builder_version":   "1.0",
                "source_files":      self.source_files,
                "full_codes_count":  len(self.full_codes),
                "group_codes_count": len(self.group_codes),
                "type_codes_count":  len(self.type_codes),
            },
            "full_codes":  self.full_codes,
            "group_codes": self.group_codes,
            "type_codes":  self.type_codes,
        }

        with open("rsnb_registry.json", "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
        size = Path("rsnb_registry.json").stat().st_size
        print(f"  OK rsnb_registry.json: {size//1024} КБ")

        with open("rsnb_registry_report.json", "w", encoding="utf-8") as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        size = Path("rsnb_registry_report.json").stat().st_size
        print(f"  OK rsnb_registry_report.json: {size//1024} КБ")

    # ── Итоговый вывод ───────────────────────────────────────────────────────

    def print_summary(self):
        s = self.report["summary"]
        q = self.report["quality"]
        print()
        print("=" * 60)
        print("  RSNB REGISTRY BUILDER v1.0 — РЕЗУЛЬТАТ")
        print("=" * 60)
        print(f"  Файлов источников:   {s['source_files_count']}")
        print(f"  Строк обработано:    {s['total_rows_processed']}")
        print()
        print(f"  full_codes:          {s['full_codes_found']}")
        print(f"  group_codes:         {s['group_codes_found']}")
        print(f"  type_codes:          {s['type_codes_found']}")
        print()
        print(f"  Стабильных кодов:    {q['stable_codes']} ({q['stable_pct']}%)")
        print(f"  Конфликты единиц:    {q['codes_with_unit_conflicts']}")
        print(f"  Конфликты фаз:       {q['codes_with_phase_conflicts']}")
        print(f"  Однократные коды:    {q['single_occurrence_codes']}")
        print()

        # Топ type_codes по количеству работ
        top = sorted(self.type_codes.items(),
                     key=lambda x: -x[1]["total_occurrences"])[:8]
        print("  ТОП ТИПОВЫХ КОДОВ:")
        for tc, data in top:
            phase = data.get("canonical_phase", "—")
            print(f"    {tc}  {phase:<35} "
                  f"групп: {data['group_codes_count']:>3}  "
                  f"встреч: {data['total_occurrences']:>4}")
        print()
        print("  Файлы: rsnb_registry.json, rsnb_registry_report.json")
        print("=" * 60)

    # ── Запуск ───────────────────────────────────────────────────────────────

    def run(self):
        self.load_files()
        if not self.all_rows:
            print("Нет данных для обработки.")
            return
        self.build_full_code_registry()
        self.build_group_code_registry()
        self.build_type_code_registry()
        self.build_report()
        self.save_results()
        self.print_summary()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AINTELLECTUM RSNB Registry Builder v1.0"
    )
    parser.add_argument(
        "inputs", nargs="*",
        default=["smeta_works_clean.json"],
        help="Файлы или папки со сметами"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  RSNB REGISTRY BUILDER v1.0 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  Принцип: строим свою нормативную базу из реальных смет")
    print("=" * 60)
    print()

    builder = RSNBRegistryBuilder(args.inputs)
    builder.run()