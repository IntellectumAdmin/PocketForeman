# -*- coding: utf-8 -*-
"""
DURATION ENGINE v6.0 — ЭТАП 1
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

ЭТАП 1: Маппинг подразделов к production profiles
  - загрузка work_assignment.json
  - загрузка volume_summary.json
  - загрузка production_rates.json
  - сопоставление подразделов с профилями производительности
  - сохранение mapping_result.json
  - сохранение unmapped_items.json

ЭТАП 2 (следующий): расчёт duration_days
  - volume / rate_per_day
  - duration_estimates.json
  - duration_summary.json

ИСПОЛЬЗОВАНИЕ:
  python duration_engine.py              # полный запуск этапа 1
  python duration_engine.py --verbose    # с детальным выводом

PIPELINE:
  work_assignment.json
  + volume_summary.json
  + production_rates.json
        ↓
  mapping_result.json    (сопоставленные подразделы)
  unmapped_items.json    (несопоставленные → для улучшения справочника)
"""

import json
import argparse
import math
from pathlib import Path
from typing import Dict, List, Any, Optional


# ═══════════════════════════════════════════════════════════════
# DURATION ENGINE
# ═══════════════════════════════════════════════════════════════
class DurationEngine:

    def __init__(
        self,
        work_assignment_path: str = "work_assignment.json",
        volume_summary_path: str  = "volume_summary.json",
        production_rates_path: str = "production_rates.json",
    ):
        self.work_assignment_path  = Path(work_assignment_path)
        self.volume_summary_path   = Path(volume_summary_path)
        self.production_rates_path = Path(production_rates_path)

        self.work_assignment  = {}
        self.volume_summary   = {}
        self.production_rates = {}

        self.mapping_result = {
            "project": None,
            "version": "6.0_stage1",
            "mapped_items": [],
            "unmapped_items": []
        }

    # ═══════════════════════════════════════════════════════════
    # ЗАГРУЗКА
    # ═══════════════════════════════════════════════════════════
    def load_inputs(self):
        print("Загружаю входные файлы...")
        self.work_assignment  = self._load_json(self.work_assignment_path)
        self.volume_summary   = self._load_json(self.volume_summary_path)
        self.production_rates = self._load_json(self.production_rates_path)

        project = (
            self.work_assignment.get("project") or
            self.volume_summary.get("project") or
            "unknown"
        )
        self.mapping_result["project"] = project

        phases_count = len(self.volume_summary.get("phases_summary", []))
        profiles_count = len(self.production_rates.get("profiles", []))
        print(f"  ✓ Проект: {project}")
        print(f"  ✓ Фаз в volume_summary: {phases_count}")
        print(f"  ✓ Профилей в справочнике: {profiles_count}")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ═══════════════════════════════════════════════════════════
    # ЭТАП 1: МАППИНГ
    # ═══════════════════════════════════════════════════════════
    def run_stage_1_mapping(self, verbose: bool = False):
        """
        Проходим по фазам → подразделам из volume_summary.
        Для каждого подраздела ищем подходящий production profile.
        """
        print("\n" + "="*60)
        print("ЭТАП 1: МАППИНГ ПОДРАЗДЕЛОВ К ПРОФИЛЯМ")
        print("="*60)

        phases = self.volume_summary.get("phases_summary", [])

        for phase in phases:
            phase_name = phase.get("phase", "").strip()
            subsections = phase.get("subsections", [])

            if verbose:
                print(f"\n  📁 {phase_name} ({len(subsections)} подразделов)")

            for subsection in subsections:
                # Получаем объёмы из work_assignment для этого подраздела
                volumes = self._get_subsection_volumes(phase_name, subsection.get("name", ""))

                mapped = self._map_subsection(phase_name, subsection, volumes)

                if mapped is not None:
                    self.mapping_result["mapped_items"].append(mapped)
                    if verbose:
                        print(f"    ✓ {subsection.get('name','')[:40]} → {mapped['profile_label']} ({mapped['rate_per_day']}/день)")
                else:
                    self.mapping_result["unmapped_items"].append({
                        "phase": phase_name,
                        "subsection_name": subsection.get("name", ""),
                        "work_items_count": subsection.get("work_items_count", 0),
                        "volumes": volumes,
                        "reason": "no_matching_profile"
                    })
                    if verbose:
                        print(f"    ⚠️ {subsection.get('name','')[:40]} → не сопоставлен")

    def _get_subsection_volumes(self, phase_name: str, subsection_name: str) -> Dict[str, float]:
        """Получает объёмы подраздела из work_assignment."""
        for phase in self.work_assignment.get("phases", []):
            if phase.get("phase", "") == phase_name:
                for sub in phase.get("subsections", []):
                    if sub.get("name", "") == subsection_name:
                        return sub.get("volumes", {})
        return {}

    # ═══════════════════════════════════════════════════════════
    # МАППИНГ: поиск профиля для подраздела
    # ═══════════════════════════════════════════════════════════
    def _map_subsection(
        self,
        phase_name: str,
        subsection: Dict[str, Any],
        volumes: Dict[str, float]
    ) -> Optional[Dict[str, Any]]:
        """
        Ищет подходящий production profile для подраздела.
        Возвращает mapped_item или None если не найдено.
        """
        sub_name = subsection.get("name", "").strip()
        work_count = subsection.get("work_items_count", 0)

        # Определяем основную единицу (с наибольшим объёмом)
        main_unit = None
        main_volume = None
        if volumes:
            main_unit = max(volumes, key=lambda u: volumes[u])
            main_volume = volumes[main_unit]

        # Ищем профиль
        profile = self._find_matching_profile(
            phase_name=phase_name,
            sub_name=sub_name,
            unit=main_unit
        )

        if profile is None:
            # Вторая попытка: без проверки unit
            profile = self._find_matching_profile(
                phase_name=phase_name,
                sub_name=sub_name,
                unit=None
            )
            unit_match = False
        else:
            unit_match = True

        if profile is None:
            return None

        # Рассчитываем confidence
        confidence = self._calc_confidence(
            sub_name=sub_name,
            profile=profile,
            unit_match=unit_match
        )

        # Рассчитываем длительность (уже в этапе 1 — просто и сразу!)
        duration_days = None
        if main_volume and profile.get("rate_per_day"):
            raw = main_volume / profile["rate_per_day"]
            duration_days = max(
                profile.get("min_duration_days", 1),
                math.ceil(raw)
            )

        return {
            "phase": phase_name,
            "subsection_name": sub_name,
            "work_items_count": work_count,
            "main_unit": main_unit,
            "main_volume": main_volume,
            "all_volumes": volumes,
            "matched_profile": profile["profile"],
            "profile_label": profile["label"],
            "rate_per_day": profile["rate_per_day"],
            "unit_match": unit_match,
            "mapping_confidence": round(confidence, 2),
            "duration_days": duration_days,   # уже считаем!
        }

    def _find_matching_profile(
        self,
        phase_name: str,
        sub_name: str,
        unit: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Keyword-matching: ищет первый профиль где keyword встречается
        в названии подраздела или фазы.
        """
        profiles = self.production_rates.get("profiles", [])
        haystack = f"{phase_name} {sub_name}".lower()

        for profile in profiles:
            profile_unit = profile.get("unit")

            # Проверка unit (если задан)
            if unit and profile_unit and unit != profile_unit:
                continue

            # Keyword matching
            for kw in profile.get("match", []):
                if kw.lower() in haystack:
                    return profile

        return None

    def _calc_confidence(
        self,
        sub_name: str,
        profile: Dict[str, Any],
        unit_match: bool
    ) -> float:
        """
        Простой расчёт уверенности маппинга (0.0 - 1.0).
        """
        score = 0.5  # базовый

        # Совпадение unit даёт +0.3
        if unit_match:
            score += 0.3

        # Длина совпавшего keyword относительно названия
        haystack = sub_name.lower()
        best_kw_len = 0
        for kw in profile.get("match", []):
            if kw.lower() in haystack:
                best_kw_len = max(best_kw_len, len(kw))

        if best_kw_len > 0 and len(sub_name) > 0:
            kw_ratio = best_kw_len / len(sub_name)
            score += min(0.2, kw_ratio * 0.5)

        return min(1.0, score)

    # ═══════════════════════════════════════════════════════════
    # СОХРАНЕНИЕ
    # ═══════════════════════════════════════════════════════════
    def save_results(
        self,
        mapping_path: str  = "mapping_result.json",
        unmapped_path: str = "unmapped_items.json"
    ):
        mapped   = self.mapping_result["mapped_items"]
        unmapped = self.mapping_result["unmapped_items"]

        # Mapping result
        self._save_json({
            "project":      self.mapping_result["project"],
            "version":      self.mapping_result["version"],
            "mapped_count": len(mapped),
            "note":         "Подразделы сопоставленные с production profiles",
            "mapped_items": mapped,
        }, mapping_path)

        # Unmapped items
        self._save_json({
            "project":        self.mapping_result["project"],
            "unmapped_count": len(unmapped),
            "note":           "Не сопоставленные подразделы — источник улучшения справочника",
            "unmapped_items": unmapped,
        }, unmapped_path)

    def _save_json(self, data: Any, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size = Path(path).stat().st_size
        print(f"  ✓ {Path(path).name}: {size / 1024:.1f} КБ")

    # ═══════════════════════════════════════════════════════════
    # ОТЧЁТ
    # ═══════════════════════════════════════════════════════════
    def print_summary(self):
        mapped   = self.mapping_result["mapped_items"]
        unmapped = self.mapping_result["unmapped_items"]
        total    = len(mapped) + len(unmapped)

        print()
        print("=" * 60)
        print("DURATION ENGINE v6.0 — ЭТАП 1 ЗАВЕРШЁН")
        print("=" * 60)
        print(f"Проект:           {self.mapping_result['project']}")
        print(f"Всего подразделов:{total:>6}")
        print(f"Сопоставлено:     {len(mapped):>6}")
        print(f"Не сопоставлено:  {len(unmapped):>6}")

        if total > 0:
            coverage = len(mapped) / total * 100
            print(f"Покрытие:         {coverage:>5.1f}%")

        # Топ профили
        if mapped:
            from collections import Counter
            profiles_used = Counter(m["matched_profile"] for m in mapped)
            print()
            print("Топ профили:")
            for profile, count in profiles_used.most_common(5):
                label = next(
                    (m["profile_label"] for m in mapped if m["matched_profile"] == profile),
                    profile
                )
                print(f"  {label}: {count}")

        # Длительности по фазам (предварительные)
        if mapped:
            from collections import defaultdict
            phase_days = defaultdict(int)
            for m in mapped:
                if m.get("duration_days"):
                    phase_days[m["phase"]] += m["duration_days"]

            if phase_days:
                print()
                print("Предварительные длительности по фазам (дни):")
                total_days = 0
                for phase, days in sorted(phase_days.items(), key=lambda x: -x[1]):
                    print(f"  {phase}: {days} дн.")
                    total_days += days
                print(f"  {'─'*40}")
                print(f"  ИТОГО (сумма): {total_days} дн. (~{total_days//30} мес.)")

        print("=" * 60)
        print()
        print("📁 Файлы:")
        print("  - mapping_result.json   (сопоставленные подразделы)")
        print("  - unmapped_items.json   (несопоставленные → улучшить справочник)")
        print()
        print("🚀 Следующий шаг: Этап 2 → duration_estimates.json → ГПР!")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AINTELLECTUM Duration Engine v6.0")
    parser.add_argument("--verbose", "-v", action="store_true", help="Детальный вывод")
    parser.add_argument(
        "--work-assignment", default="work_assignment.json",
        help="Путь к work_assignment.json"
    )
    parser.add_argument(
        "--volume-summary", default="volume_summary.json",
        help="Путь к volume_summary.json"
    )
    parser.add_argument(
        "--production-rates", default="production_rates.json",
        help="Путь к production_rates.json"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("DURATION ENGINE v6.0 - AINTELLECTUM")
    print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("=" * 60)
    print()

    engine = DurationEngine(
        work_assignment_path=args.work_assignment,
        volume_summary_path=args.volume_summary,
        production_rates_path=args.production_rates,
    )

    engine.load_inputs()
    engine.run_stage_1_mapping(verbose=args.verbose)

    print("\nСохраняю файлы:")
    engine.save_results()

    engine.print_summary()