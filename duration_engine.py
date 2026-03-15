# -*- coding: utf-8 -*-
"""
DURATION ENGINE v6.2
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

ПРАВИЛО AINTELLECTUM: Никаких ручных исправлений.
Всё что выглядит как ошибка — автоматически диагностируется
и исправляется кодом с сохранением audit trail.

НОВОЕ в v6.2:
1. Автодиагностика подозрительных единиц (кг/т, мм/м и др.)
2. Автокоррекция при явных аномалиях (с флагом auto_corrected)
3. duration_estimates.json — детальный расчёт с трассировкой
4. duration_summary.json — читаемый итог для инженера
5. unit_diagnostics.json — полный отчёт по подозрительным данным
6. duration_status: ok / suspicious / auto_corrected / no_volume
7. calculation_trace: полная трассировка расчёта

ИСПРАВЛЕНИЯ из v6.1:
- if sel_volume is not None (не if sel_volume)
- volume_resolved вместо unit_matched
- unit_direct_match отдельно

ИСПОЛЬЗОВАНИЕ:
  python duration_engine.py              # полный запуск
  python duration_engine.py --verbose    # детальный вывод
"""

import json
import math
import argparse
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from collections import Counter, defaultdict


class DurationEngine:

    # ═══════════════════════════════════════════════════════
    # НОРМАЛИЗАЦИЯ ЕДИНИЦ
    # ═══════════════════════════════════════════════════════
    UNIT_ALIASES = {
        "м": "м", "м.": "м",
        "м.п.": "м", "п.м.": "м", "пог.м": "м",
        "пог.м.": "м", "погонный метр": "м",
        "м2": "м2", "м²": "м2", "кв.м": "м2",
        "кв м": "м2", "кв.м.": "м2",
        "100 м2": "100м2", "100м²": "100м2",
        "м3": "м3", "м³": "м3", "куб.м": "м3",
        "куб м": "м3", "куб.м.": "м3",
        "т": "т", "тонн": "т", "тонна": "т",
        "тонны": "т", "тн": "т",
        "кг": "кг", "кг.": "кг",
        "шт": "шт", "шт.": "шт",
        "компл": "шт", "комплект": "шт", "компл.": "шт",
        "л": "л", "мм": "мм", "см": "см",
    }

    UNIT_CONVERSIONS = {
        ("кг", "т"):     lambda x: x / 1000.0,
        ("т",  "кг"):    lambda x: x * 1000.0,
        ("мм", "м"):     lambda x: x / 1000.0,
        ("см", "м"):     lambda x: x / 100.0,
        ("л",  "м3"):    lambda x: x / 1000.0,
        ("100м2", "м2"): lambda x: x * 100.0,
        ("м2", "100м2"): lambda x: x / 100.0,
    }

    # ═══════════════════════════════════════════════════════
    # АВТОДИАГНОСТИКА: правила для обнаружения аномалий
    #
    # Каждое правило:
    #   profile_id    — к какому профилю применяется
    #   declared_unit — какая единица вызывает подозрение
    #   max_realistic — максимально реальное значение
    #   likely_real   — скорее всего реальная единица
    #   reason        — объяснение для audit trail
    # ═══════════════════════════════════════════════════════
    SANITY_RULES = [
        {
            "profile_id":    "metal_structures_installation",
            "declared_unit": "т",
            "max_realistic": 5000,
            "likely_real":   "кг",
            "reason":        "Объём металлоконструкций >5000 т нереалистичен для одного объекта. Вероятно кг."
        },
        {
            "profile_id":    "reinforcement",
            "declared_unit": "т",
            "max_realistic": 10000,
            "likely_real":   "кг",
            "reason":        "Объём армирования >10000 т нереалистичен. Вероятно кг."
        },
        {
            "profile_id":    "roofing_soft",
            "declared_unit": "м2",
            "max_realistic": 50000,
            "likely_real":   None,
            "reason":        "Площадь кровли >50000 м² нереалистична для стандартного объекта."
        },
        {
            "profile_id":    "concreting_structural",
            "declared_unit": "м3",
            "max_realistic": 100000,
            "likely_real":   None,
            "reason":        "Объём бетона >100000 м³ нереалистичен. Возможно ошибка."
        },
        {
            "profile_id":    "electrical_cable",
            "declared_unit": "м",
            "max_realistic": 500000,
            "likely_real":   None,
            "reason":        "Длина кабельных линий >500км — проверить данные."
        },
    ]

    def __init__(
        self,
        work_assignment_path:  str = "work_assignment.json",
        volume_summary_path:   str = "volume_summary.json",
        production_rates_path: str = "production_rates.json",
    ):
        self.work_assignment_path  = Path(work_assignment_path)
        self.volume_summary_path   = Path(volume_summary_path)
        self.production_rates_path = Path(production_rates_path)

        self.work_assignment  = {}
        self.volume_summary   = {}
        self.production_rates = {}

        self.mapped_items     = []
        self.unmapped_items   = []
        self.diagnostics      = []
        self.project_name     = "unknown"

    # ═══════════════════════════════════════════════════════
    # ЗАГРУЗКА
    # ═══════════════════════════════════════════════════════
    def load_inputs(self):
        print("Загружаю входные файлы...")
        self.work_assignment  = self._load_json(self.work_assignment_path)
        self.volume_summary   = self._load_json(self.volume_summary_path)
        self.production_rates = self._load_json(self.production_rates_path)
        self._extend_production_rates()

        self.project_name = (
            self.work_assignment.get("project") or
            self.volume_summary.get("project") or "unknown"
        )
        print(f"  Проект: {self.project_name}")
        print(f"  Фаз: {len(self.volume_summary.get('phases_summary', []))} | "
              f"Профилей: {len(self.production_rates.get('profiles', []))}")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ═══════════════════════════════════════════════════════
    # РАСШИРЕНИЕ СПРАВОЧНИКА
    # ═══════════════════════════════════════════════════════
    def _extend_production_rates(self):
        profiles = self.production_rates.get("profiles", [])

        extensions = {
            "masonry_block": [
                "стены подвал", "стены подвала", "стены этаж",
                "наружные стены", "внутренние стены", "перегородки",
                "кладка стен", "кладка перегородок", "каменная кладка",
            ],
            "concreting_structural": [
                "плита перекрытия", "плиты перекрытия",
                "монолитная плита", "перекрытие",
                "участок перекрытия", "лестничная площадка",
                "лестничный марш", "перекрытия безбалочные",
                "плита на отм",
            ],
            "landscaping": [
                "газон", "деревья", "посадка деревьев",
                "посадка кустарников", "кустарник", "кустарники",
                "покрытие тартановое", "покрытие игровых",
                "бетонное покрытие",
            ],
            "earthworks_excavation": [
                "устройство плодородного", "плодородный грунт",
            ],
            "concreting_foundations": [
                "фундамент плита", "фундамент монолитный",
                "устройство плиты фундаментной",
                "железобетонная плита", "фп-", "фм-", "фмл-",
            ],
            "roofing_soft": [
                "кровля", "парапет", "утепление кровли",
            ],
        }

        for p in profiles:
            if p["profile"] in extensions:
                existing = set(p["match"])
                for kw in extensions[p["profile"]]:
                    if kw not in existing:
                        p["match"].append(kw)

        profiles.append({
            "profile": "interior_finishing_general",
            "label": "Внутренняя отделка помещений",
            "match": [
                "пищеблок", "кладовая", "моечная", "санузел",
                "кабинет", "раздаточная", "горячий цех",
                "административн", "медицинск", "спортивн",
                "актовый зал", "внутренняя отделка",
            ],
            "unit": "м2", "rate_per_day": 120, "min_duration_days": 1
        })
        profiles.append({
            "profile": "elevator_installation",
            "label": "Монтаж лифтов",
            "match": ["лифт", "лифтовое оборудование", "подъёмник"],
            "unit": "шт", "rate_per_day": 1, "min_duration_days": 30
        })

        self.production_rates["profiles"] = profiles

    # ═══════════════════════════════════════════════════════
    # НОРМАЛИЗАЦИЯ И КОНВЕРТАЦИЯ
    # ═══════════════════════════════════════════════════════
    def _normalize_unit(self, unit: Optional[str]) -> Optional[str]:
        if not unit:
            return None
        return self.UNIT_ALIASES.get(str(unit).strip().lower(), str(unit).strip().lower())

    def _convert_volume(self, value: float, from_unit: str, to_unit: str) -> Optional[float]:
        fn = self.UNIT_CONVERSIONS.get(
            (self._normalize_unit(from_unit), self._normalize_unit(to_unit))
        )
        return fn(value) if fn else None

    def _pick_volume_for_profile(
        self,
        volumes: Dict[str, float],
        profile_unit: Optional[str]
    ) -> Tuple[Optional[str], Optional[float], Optional[Dict]]:
        if not volumes or not profile_unit:
            return None, None, None

        punit = self._normalize_unit(profile_unit)

        norm_vols: Dict[str, float] = {}
        for unit, value in volumes.items():
            n = self._normalize_unit(unit)
            norm_vols[n] = norm_vols.get(n, 0.0) + value

        # Прямое совпадение
        if punit in norm_vols:
            return punit, norm_vols[punit], {
                "converted": False,
                "source_unit": punit,
                "target_unit": punit,
            }

        # Конвертация
        for src_unit, value in norm_vols.items():
            conv = self._convert_volume(value, src_unit, punit)
            if conv is not None:
                return punit, conv, {
                    "converted": True,
                    "source_unit": src_unit,
                    "target_unit": punit,
                    "original_value": round(value, 3),
                }

        return None, None, None

    # ═══════════════════════════════════════════════════════
    # АВТОДИАГНОСТИКА И АВТОКОРРЕКЦИЯ (НОВОЕ в v6.2)
    #
    # Логика:
    # 1. После выбора объёма проверяем SANITY_RULES
    # 2. Если объём нереалистичен — записываем в diagnostics
    # 3. Если есть likely_real — автоматически конвертируем
    # 4. Сохраняем полный audit trail (было/стало/причина)
    #
    # НИКАКИХ ручных вмешательств — всё автоматически!
    # ═══════════════════════════════════════════════════════
    def _apply_sanity_check(
        self,
        profile_id:   str,
        unit:         Optional[str],
        volume:       Optional[float],
        phase_name:   str,
        sub_name:     str
    ) -> Tuple[Optional[float], Optional[str], str]:
        """
        Проверяет реалистичность объёма.
        Возвращает: (скорректированный объём, скорректированная единица, статус)

        Статусы:
          ok              — всё нормально
          suspicious      — подозрительно, но не корректируем
          auto_corrected  — автоматически исправлено
          no_volume       — нет объёма
        """
        if volume is None:
            return volume, unit, "no_volume"

        norm_unit = self._normalize_unit(unit)

        for rule in self.SANITY_RULES:
            if (rule["profile_id"] == profile_id and
                    self._normalize_unit(rule["declared_unit"]) == norm_unit and
                    volume > rule["max_realistic"]):

                likely_real = rule.get("likely_real")

                if likely_real:
                    # Автоматически конвертируем
                    converted = self._convert_volume(volume, norm_unit, likely_real)
                    if converted is not None:
                        diag = {
                            "phase":              phase_name,
                            "subsection":         sub_name,
                            "profile_id":         profile_id,
                            "declared_unit":      unit,
                            "declared_volume":    volume,
                            "auto_corrected":     True,
                            "corrected_unit":     likely_real,
                            "corrected_volume":   round(converted, 3),
                            "reason":             rule["reason"],
                            "rule":               f"volume > {rule['max_realistic']} {rule['declared_unit']}"
                        }
                        self.diagnostics.append(diag)
                        return converted, likely_real, "auto_corrected"
                else:
                    # Подозрительно, но не знаем как конвертировать
                    diag = {
                        "phase":           phase_name,
                        "subsection":      sub_name,
                        "profile_id":      profile_id,
                        "declared_unit":   unit,
                        "declared_volume": volume,
                        "auto_corrected":  False,
                        "reason":          rule["reason"],
                        "rule":            f"volume > {rule['max_realistic']} {rule['declared_unit']}"
                    }
                    self.diagnostics.append(diag)
                    return volume, unit, "suspicious"

        return volume, unit, "ok"

    # ═══════════════════════════════════════════════════════
    # ПОИСК ПРОФИЛЯ (SCORING)
    # ═══════════════════════════════════════════════════════
    def _find_matching_profile(self, phase_name: str, sub_name: str) -> Optional[Dict[str, Any]]:
        profiles = self.production_rates.get("profiles", [])
        haystack = f"{phase_name} {sub_name}".lower()
        best_profile, best_score = None, 0

        for profile in profiles:
            score = sum(
                max(1, len(kw) // 3)
                for kw in profile.get("match", [])
                if kw.lower() in haystack
            )
            if score > best_score:
                best_score, best_profile = score, profile

        return best_profile if best_score > 0 else None

    # ═══════════════════════════════════════════════════════
    # МАППИНГ ПОДРАЗДЕЛА
    # ═══════════════════════════════════════════════════════
    def _map_subsection(
        self,
        phase_name: str,
        subsection: Dict[str, Any],
        volumes: Dict[str, float]
    ) -> Optional[Dict[str, Any]]:

        sub_name   = subsection.get("name", "").strip()
        work_count = subsection.get("work_items_count", 0)

        profile = self._find_matching_profile(phase_name, sub_name)
        if profile is None:
            return None

        sel_unit, sel_volume, conv_info = self._pick_volume_for_profile(
            volumes, profile.get("unit")
        )

        # АВТОДИАГНОСТИКА — проверяем реалистичность
        final_volume, final_unit, duration_status = self._apply_sanity_check(
            profile_id=profile["profile"],
            unit=sel_unit,
            volume=sel_volume,
            phase_name=phase_name,
            sub_name=sub_name
        )

        # Расчёт длительности (ФИКС: is not None!)
        duration_days = None
        calculation_trace = None
        if final_volume is not None and profile.get("rate_per_day"):
            raw = final_volume / profile["rate_per_day"]
            duration_days = max(profile.get("min_duration_days", 1), math.ceil(raw))
            calculation_trace = {
                "formula":          f"ceil({round(final_volume, 3)} / {profile['rate_per_day']})",
                "raw_result":       round(raw, 4),
                "min_duration":     profile.get("min_duration_days", 1),
                "final_days":       duration_days,
                "unit":             final_unit,
                "volume":           round(final_volume, 3),
                "rate_per_day":     profile["rate_per_day"],
            }

        # Confidence
        haystack  = f"{phase_name} {sub_name}".lower()
        best_kw   = max(
            (len(kw) for kw in profile.get("match", []) if kw.lower() in haystack),
            default=0
        )
        confidence = min(1.0,
            0.4 +
            (0.3 if conv_info is not None else 0) +
            min(0.3, best_kw / max(len(sub_name), 1) * 0.6)
        )

        return {
            "phase":             phase_name,
            "subsection_name":   sub_name,
            "work_items_count":  work_count,
            "all_volumes":       volumes,

            "matched_profile":   profile["profile"],
            "profile_label":     profile["label"],
            "profile_unit":      profile.get("unit"),
            "rate_per_day":      profile["rate_per_day"],

            # ФИКС v6.2: is not None + правильные имена
            "selected_unit":     sel_unit,
            "selected_volume":   round(sel_volume, 3) if sel_volume is not None else None,
            "volume_resolved":   conv_info is not None,
            "unit_direct_match": conv_info is not None and not (conv_info or {}).get("converted", False),
            "conversion_info":   conv_info,

            # Автодиагностика
            "final_unit":        final_unit,
            "final_volume":      round(final_volume, 3) if final_volume is not None else None,
            "duration_status":   duration_status,

            "mapping_confidence":  round(confidence, 2),
            "duration_days":       duration_days,
            "calculation_trace":   calculation_trace,
        }

    def _get_subsection_volumes(self, phase_name: str, sub_name: str) -> Dict[str, float]:
        for phase in self.work_assignment.get("phases", []):
            if phase.get("phase", "") == phase_name:
                for sub in phase.get("subsections", []):
                    if sub.get("name", "") == sub_name:
                        return sub.get("volumes", {})
        return {}

    # ═══════════════════════════════════════════════════════
    # ОСНОВНОЙ ПРОГОН
    # ═══════════════════════════════════════════════════════
    def run_mapping(self, verbose: bool = False):
        print("\n" + "="*60)
        print("МАППИНГ + АВТОДИАГНОСТИКА")
        print("="*60)

        for phase in self.volume_summary.get("phases_summary", []):
            phase_name  = phase.get("phase", "").strip()
            subsections = phase.get("subsections", [])

            if verbose:
                print(f"\n  📁 {phase_name} ({len(subsections)} подразделов)")

            for sub in subsections:
                sub_name = sub.get("name", "").strip()
                volumes  = self._get_subsection_volumes(phase_name, sub_name)
                result   = self._map_subsection(phase_name, sub, volumes)

                if result:
                    self.mapped_items.append(result)
                    if verbose:
                        status = result["duration_status"]
                        icon   = "✓" if status == "ok" else ("🔧" if status == "auto_corrected" else "⚠️")
                        vol    = f"{result['final_volume']} {result['final_unit']}" if result["final_volume"] is not None else "—"
                        dur    = f"{result['duration_days']} дн." if result["duration_days"] else "—"
                        status_str = f" [{status}]" if status != "ok" else ""
                        print(f"    {icon} {sub_name[:34]:<34} → {result['profile_label'][:20]} | {vol} | {dur}{status_str}")
                else:
                    self.unmapped_items.append({
                        "phase":           phase_name,
                        "subsection_name": sub_name,
                        "normalized_name": sub_name.lower(),
                        "available_units": list(volumes.keys()),
                        "all_volumes":     volumes,
                        "reason":          "no_matching_profile",
                    })
                    if verbose:
                        print(f"    ⚠️ {sub_name[:34]:<34} → не сопоставлен")

    # ═══════════════════════════════════════════════════════
    # СОХРАНЕНИЕ ФАЙЛОВ
    # ═══════════════════════════════════════════════════════
    def save_results(self):
        print("\nСохраняю файлы:")

        # 1. mapping_result.json — полные данные маппинга
        self._save_json({
            "project":      self.project_name,
            "version":      "6.2",
            "mapped_count": len(self.mapped_items),
            "mapped_items": self.mapped_items,
        }, "mapping_result.json")

        # 2. unmapped_items.json
        self._save_json({
            "project":        self.project_name,
            "unmapped_count": len(self.unmapped_items),
            "note":           "Добавь keywords в production_rates.json для этих подразделов",
            "unmapped_items": self.unmapped_items,
        }, "unmapped_items.json")

        # 3. unit_diagnostics.json — автодиагностика аномалий
        auto_fixed   = sum(1 for d in self.diagnostics if d.get("auto_corrected"))
        suspicious   = len(self.diagnostics) - auto_fixed
        self._save_json({
            "project":          self.project_name,
            "version":          "6.2",
            "total_issues":     len(self.diagnostics),
            "auto_corrected":   auto_fixed,
            "suspicious":       suspicious,
            "note":             "Автоматически найденные аномалии единиц измерения",
            "diagnostics":      self.diagnostics,
        }, "unit_diagnostics.json")

        # 4. duration_estimates.json — детальный расчёт
        estimates = [
            {
                "phase":               m["phase"],
                "subsection_name":     m["subsection_name"],
                "matched_profile":     m["matched_profile"],
                "profile_label":       m["profile_label"],
                "selected_volume":     m["final_volume"],
                "selected_unit":       m["final_unit"],
                "rate_per_day":        m["rate_per_day"],
                "duration_days":       m["duration_days"],
                "duration_status":     m["duration_status"],
                "mapping_confidence":  m["mapping_confidence"],
                "calculation_trace":   m.get("calculation_trace"),
            }
            for m in self.mapped_items
            if m.get("duration_days") is not None
        ]
        self._save_json({
            "project":   self.project_name,
            "version":   "6.2",
            "total":     len(estimates),
            "note":      "Детальный расчёт длительностей с трассировкой",
            "estimates": estimates,
        }, "duration_estimates.json")

        # 5. duration_summary.json — читаемый итог
        self._save_json(self._build_summary(), "duration_summary.json")

    def _build_summary(self) -> Dict[str, Any]:
        phase_data: Dict[str, Dict] = {}

        for m in self.mapped_items:
            ph = m["phase"]
            if ph not in phase_data:
                phase_data[ph] = {
                    "phase":               ph,
                    "subsections_total":   0,
                    "subsections_with_duration": 0,
                    "duration_days_sequential": 0,
                    "auto_corrected_count": 0,
                    "suspicious_count":    0,
                }
            pd = phase_data[ph]
            pd["subsections_total"] += 1

            if m.get("duration_days") is not None:
                pd["subsections_with_duration"] += 1
                pd["duration_days_sequential"]  += m["duration_days"]

            if m.get("duration_status") == "auto_corrected":
                pd["auto_corrected_count"] += 1
            elif m.get("duration_status") == "suspicious":
                pd["suspicious_count"] += 1

        phases_summary = sorted(
            phase_data.values(),
            key=lambda x: -x["duration_days_sequential"]
        )

        total_seq  = sum(p["duration_days_sequential"] for p in phases_summary)
        max_phase  = max((p["duration_days_sequential"] for p in phases_summary), default=0)
        total_auto = sum(p["auto_corrected_count"] for p in phases_summary)
        total_susp = sum(p["suspicious_count"] for p in phases_summary)

        # Грубая параллельность: ~35% от последовательного
        parallel_rough = int(total_seq * 0.35)

        return {
            "project":   self.project_name,
            "version":   "6.2",
            "stats": {
                "total_subsections":         len(self.mapped_items) + len(self.unmapped_items),
                "mapped_subsections":        len(self.mapped_items),
                "unmapped_subsections":      len(self.unmapped_items),
                "coverage_pct":              round(len(self.mapped_items) / max(1, len(self.mapped_items) + len(self.unmapped_items)) * 100, 1),
                "auto_corrected_units":      total_auto,
                "suspicious_units":          total_susp,
            },
            "duration": {
                "total_sequential_days":     total_seq,
                "total_sequential_months":   round(total_seq / 30, 1),
                "critical_path_rough_days":  max_phase,
                "parallel_rough_days":       parallel_rough,
                "parallel_rough_months":     round(parallel_rough / 30, 1),
                "note": "Параллельный расчёт ~35% от последовательного. Уточнит GPR Builder."
            },
            "phases": [
                {
                    "phase":               p["phase"],
                    "duration_days":       p["duration_days_sequential"],
                    "duration_months":     round(p["duration_days_sequential"] / 30, 1),
                    "subsections":         p["subsections_total"],
                    "auto_corrected":      p["auto_corrected_count"],
                }
                for p in phases_summary
                if p["duration_days_sequential"] > 0
            ],
            "note": "Читаемый итог для инженера. Основа для GPR Builder."
        }

    def _save_json(self, data: Any, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size = Path(path).stat().st_size
        print(f"  ✓ {path}: {size/1024:.1f} КБ")

    # ═══════════════════════════════════════════════════════
    # ИТОГОВЫЙ ОТЧЁТ
    # ═══════════════════════════════════════════════════════
    def print_summary(self):
        total  = len(self.mapped_items) + len(self.unmapped_items)
        mapped = len(self.mapped_items)

        print()
        print("=" * 60)
        print("DURATION ENGINE v6.2 — РЕЗУЛЬТАТ")
        print("=" * 60)
        print(f"Подразделов:      {total}")
        print(f"Сопоставлено:     {mapped}  ({mapped/total*100:.1f}%)")
        print(f"Не сопоставлено:  {len(self.unmapped_items)}")

        auto_fixed = sum(1 for m in self.mapped_items if m.get("duration_status") == "auto_corrected")
        suspicious = sum(1 for m in self.mapped_items if m.get("duration_status") == "suspicious")
        if auto_fixed or suspicious:
            print()
            print("Автодиагностика единиц:")
            if auto_fixed:
                print(f"  🔧 Автоисправлено: {auto_fixed}  (audit trail в unit_diagnostics.json)")
            if suspicious:
                print(f"  ⚠️ Подозрительных: {suspicious}  (проверь unit_diagnostics.json)")

        # Топ профили
        top = Counter(m["matched_profile"] for m in self.mapped_items)
        print()
        print("Топ профили:")
        for pid, cnt in top.most_common(5):
            lbl = next((m["profile_label"] for m in self.mapped_items if m["matched_profile"] == pid), pid)
            print(f"  {lbl}: {cnt}")

        # Длительности
        phase_days: Dict[str, int] = defaultdict(int)
        for m in self.mapped_items:
            if m.get("duration_days"):
                phase_days[m["phase"]] += m["duration_days"]

        if phase_days:
            total_days = sum(phase_days.values())
            max_days   = max(phase_days.values())
            print()
            print("Длительности по фазам:")
            for phase, days in sorted(phase_days.items(), key=lambda x: -x[1]):
                bar = "█" * min(25, days // 30)
                print(f"  {phase:<35} {days:>6} дн. {bar}")
            print(f"  {'─'*55}")
            print(f"  {'ИТОГО (последовательно)':<35} {total_days:>6} дн. (~{total_days/30:.0f} мес.)")
            print()
            print(f"  Критический путь:   ~{max_days} дн. (~{max_days/30:.0f} мес.)")
            print(f"  С параллельностью:  ~{int(total_days*0.35)} дн. (~{int(total_days*0.35/30)} мес.)")

        print()
        print("📁 Файлы:")
        print("  - mapping_result.json      (полный маппинг)")
        print("  - duration_estimates.json  (расчёт с трассировкой)")
        print("  - duration_summary.json    (читаемый итог)")
        print("  - unit_diagnostics.json    (автодиагностика единиц)")
        print("  - unmapped_items.json      (несопоставлено)")
        print()
        print("🚀 Следующий шаг: GPR Builder → ГПР!")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AINTELLECTUM Duration Engine v6.2")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--work-assignment",  default="work_assignment.json")
    parser.add_argument("--volume-summary",   default="volume_summary.json")
    parser.add_argument("--production-rates", default="production_rates.json")
    args = parser.parse_args()

    print("=" * 60)
    print("DURATION ENGINE v6.2 — AINTELLECTUM")
    print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("Принцип: Никаких ручных правок — всё автоматически!")
    print("=" * 60)
    print()

    engine = DurationEngine(
        work_assignment_path=args.work_assignment,
        volume_summary_path=args.volume_summary,
        production_rates_path=args.production_rates,
    )
    engine.load_inputs()
    engine.run_mapping(verbose=args.verbose)
    engine.save_results()
    engine.print_summary()