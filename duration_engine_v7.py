"""
Duration Engine v7.0
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

Архитектурный принцип (от Аяна):
  Читаем smeta_works_clean.json (канонический формат)
  Опираемся на полный код, а не keywords
  Параллельность внутри фазы: phase_duration = max(), не sum()

Изменения v7.0 vs v6.2:
  - Читает smeta_works_clean.json (от Volume QA Engine)
  - НЕ требует work_assignment.json / volume_summary.json
  - Параллельность через parallel_in_phase флаг
  - Полный шифр как основа расчёта
  - Fallback по group_code и type_code

ИСПОЛЬЗОВАНИЕ:
  python duration_engine.py
  python duration_engine.py smeta_works_clean.json --verbose
"""

import json
import math
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Optional


# ─── Справочник норм выработки по типовым кодам ──────────────────────────────
#
# Структура:
#   "full_code"  или  "group_code"  или  "type_code"  →  { unit, rate_per_day, label }
#
# Логика разрешения (от Аяна):
#   1. full_code  (6103-0201-0114)  — точное совпадение
#   2. group_code (6103-0201)       — fallback
#   3. type_code  (6103)            — последний fallback
#
# Значения rate_per_day — усреднённые нормы для бригады ~6-8 человек
# ──────────────────────────────────────────────────────────────────────────────

PRODUCTION_RATES = {
    # ── Земляные работы (61xx) ─────────────────────────────────────────────
    "6101": {"label": "Земляные работы",           "unit": "м3",  "rate": 800},
    "6101-01": {"label": "Разработка грунта экск.", "unit": "м3",  "rate": 1200},
    "6101-02": {"label": "Разработка грунта вручн.","unit": "м3",  "rate": 40},
    "6101-03": {"label": "Обратная засыпка",        "unit": "м3",  "rate": 600},
    "6101-04": {"label": "Планировка территории",   "unit": "м2",  "rate": 2000},
    "6101-05": {"label": "Уплотнение грунта",       "unit": "м2",  "rate": 1500},

    # ── Фундаменты (6102) ───────────────────────────────────────────────────
    "6102": {"label": "Фундаменты",                 "unit": "м3",  "rate": 25},
    "6102-01": {"label": "Бетонирование фундамента","unit": "м3",  "rate": 30},
    "6102-02": {"label": "Опалубка фундаментов",    "unit": "м2",  "rate": 80},
    "6102-03": {"label": "Армирование фундаментов", "unit": "т",   "rate": 2},

    # ── Монолитный каркас (6103) ────────────────────────────────────────────
    "6103": {"label": "Монолитный каркас",          "unit": "м3",  "rate": 20},
    "6103-01": {"label": "Бетонирование колонн",    "unit": "м3",  "rate": 15},
    "6103-02": {"label": "Бетонирование стен",      "unit": "м3",  "rate": 18},
    "6103-03": {"label": "Бетонирование балок",     "unit": "м3",  "rate": 12},
    "6103-04": {"label": "Бетонирование плит",      "unit": "м3",  "rate": 25},
    "6103-05": {"label": "Опалубка",                "unit": "м2",  "rate": 120},
    "6103-06": {"label": "Армирование",             "unit": "т",   "rate": 1.5},
    "6103-07": {"label": "Монолитные работы общие", "unit": "м3",  "rate": 20},

    # ── Кирпичная кладка (6104) ─────────────────────────────────────────────
    "6104": {"label": "Кирпичная кладка",           "unit": "м3",  "rate": 8},
    "6104-01": {"label": "Кладка наружных стен",    "unit": "м3",  "rate": 7},
    "6104-02": {"label": "Кладка внутренних стен",  "unit": "м3",  "rate": 8},
    "6104-03": {"label": "Кладка перегородок",      "unit": "м2",  "rate": 30},

    # ── Металлоконструкции (6105) ────────────────────────────────────────────
    "6105": {"label": "Металлоконструкции",          "unit": "т",   "rate": 3},
    "6105-01": {"label": "Монтаж металлокаркаса",    "unit": "т",   "rate": 4},
    "6105-02": {"label": "Антикоррозийная защита",   "unit": "м2",  "rate": 200},
    "6105-03": {"label": "Сварочные работы",         "unit": "м",   "rate": 15},
    "6105-04": {"label": "Металлические конструкции","unit": "м2",  "rate": 60},
    "6105-0101": {"label": "Монтаж металлокаркаса т","unit": "т",   "rate": 4},
    "6105-0101-1102": {"label": "Металлокаркас м3→т","unit": "м3",  "rate": 3},

    # ── Кровля (6106, 6111) ─────────────────────────────────────────────────
    "6106": {"label": "Кровля",                     "unit": "м2",  "rate": 150},
    "6106-01": {"label": "Кровельное покрытие",     "unit": "м2",  "rate": 180},
    "6106-02": {"label": "Утепление кровли",        "unit": "м2",  "rate": 200},
    "6111": {"label": "Гидро- и пароизоляция",      "unit": "м2",  "rate": 300},
    "6111-04": {"label": "Гидроизоляция",           "unit": "м2",  "rate": 350},

    # ── Окна и двери (6107) ─────────────────────────────────────────────────
    "6107": {"label": "Окна и двери",               "unit": "м2",  "rate": 25},
    "6107-01": {"label": "Монтаж окон",             "unit": "м2",  "rate": 20},
    "6107-02": {"label": "Монтаж дверей",           "unit": "шт",  "rate": 8},

    # ── Отделочные работы (6108) ─────────────────────────────────────────────
    "6108": {"label": "Отделочные работы",          "unit": "м2",  "rate": 80},
    "6108-01": {"label": "Штукатурка стен",         "unit": "м2",  "rate": 60},
    "6108-02": {"label": "Шпатлёвка стен",          "unit": "м2",  "rate": 100},
    "6108-03": {"label": "Покраска стен",           "unit": "м2",  "rate": 150},
    "6108-04": {"label": "Облицовка плиткой",       "unit": "м2",  "rate": 20},
    "6108-05": {"label": "Подвесные потолки",       "unit": "м2",  "rate": 40},

    # ── Полы (6109) ──────────────────────────────────────────────────────────
    "6109": {"label": "Полы",                       "unit": "м2",  "rate": 50},
    "6109-01": {"label": "Стяжка пола",             "unit": "м2",  "rate": 80},
    "6109-02": {"label": "Напольное покрытие",      "unit": "м2",  "rate": 60},
    "6109-03": {"label": "Керамическая плитка пол", "unit": "м2",  "rate": 15},

    # ── Электрика (6110, 6119) ───────────────────────────────────────────────
    "6110": {"label": "Электромонтажные работы",    "unit": "м",   "rate": 200},
    "6110-01": {"label": "Прокладка кабеля",        "unit": "м",   "rate": 300},
    "6110-02": {"label": "Монтаж щитов",            "unit": "шт",  "rate": 2},
    "6119": {"label": "Электроснабжение",           "unit": "м",   "rate": 250},
    "6119-01": {"label": "Кабельные линии",         "unit": "м",   "rate": 400},

    # ── Сантехника (6112) ────────────────────────────────────────────────────
    "6112": {"label": "Сантехнические работы",       "unit": "м",   "rate": 100},
    "6112-01": {"label": "Трубопроводы",             "unit": "м",   "rate": 120},
    "6112-02": {"label": "Штукатурка/покраска стен",  "unit": "м2", "rate": 80},
    "6112-03": {"label": "Покраска поверхностей",       "unit": "м2","rate": 120},
    "6112-04": {"label": "Трубопроводы внутренние",  "unit": "м",   "rate": 80},
    "6112-05": {"label": "Сантехприборы",            "unit": "шт",  "rate": 5},
    "6112-0401": {"label": "Облицовка фасада",       "unit": "м2",  "rate": 40},
    "6112-0501": {"label": "Подвесные потолки",      "unit": "м2",  "rate": 50},

    # ── Вентиляция (6113) ────────────────────────────────────────────────────
    "6113": {"label": "Вентиляция и кондиционирование","unit": "м2", "rate": 30},
    "6113-01": {"label": "Воздуховоды",             "unit": "м2",  "rate": 25},
    "6113-02": {"label": "Оборудование вентиляции", "unit": "шт",  "rate": 1},
    "6113-03": {"label": "Благоустройство",         "unit": "м2",  "rate": 100},

    # ── Благоустройство (6114) ───────────────────────────────────────────────
    "6114": {"label": "Наружные трубопроводы",      "unit": "м",   "rate": 30},
    "6114-01": {"label": "Водоснабжение наружное",  "unit": "м",   "rate": 35},
    "6114-02": {"label": "Водоснабжение стальное",  "unit": "м",   "rate": 30},
    "6114-03": {"label": "Водосн./канализация",     "unit": "м",   "rate": 30},
    "6114-04": {"label": "Гидравл. испытания",      "unit": "м",   "rate": 500},
    "6114-05": {"label": "Теплоснабжение наружное", "unit": "м",   "rate": 25},
    "6114-06": {"label": "Канализация наружная",    "unit": "м",   "rate": 25},
    "6114-07": {"label": "Водоснабжение напорное",  "unit": "м",   "rate": 30},
    "6114-08": {"label": "Водоснабжение из труб",   "unit": "м",   "rate": 30},

    # ── Прочие строительные работы (6115-6118) ───────────────────────────────
    "6115": {"label": "Фасадные работы",            "unit": "м2",  "rate": 40},
    "6116": {"label": "Лестницы и площадки",        "unit": "м2",  "rate": 15},
    "6117": {"label": "Перегородки",                "unit": "м2",  "rate": 35},
    "6118": {"label": "Прочие работы",              "unit": "м2",  "rate": 50},
}


def resolve_rate(code: str) -> Optional[dict]:
    """
    Разрешает норму выработки по коду с fallback по уровням.
    Уровень 1: полный код    6103-0201-0114
    Уровень 2: групповой код 6103-0201  →  6103-02
    Уровень 3: типовой код   6103
    """
    if not code:
        return None

    parts = code.split("-")

    # Уровень 1: полный код как есть
    if code in PRODUCTION_RATES:
        return {**PRODUCTION_RATES[code], "match_level": "full"}

    # Уровень 2: групповой код — берём первые два сегмента
    if len(parts) >= 2:
        group = f"{parts[0]}-{parts[1]}"
        # Сокращаем второй сегмент: 6103-0201 → 6103-02
        group_short = f"{parts[0]}-{parts[1][:2]}"
        for g in (group, group_short):
            if g in PRODUCTION_RATES:
                return {**PRODUCTION_RATES[g], "match_level": "group"}

    # Уровень 3: типовой код
    type_code = parts[0]
    if type_code in PRODUCTION_RATES:
        return {**PRODUCTION_RATES[type_code], "match_level": "type"}

    return None


# ─── Карта: код → правильная фаза (переопределяет фазу из парсера) ───────────
#
# Принцип Аяна: КОД определяет фазу, а не название строки.
# Если парсер поставил неверную фазу — код побеждает.
#
# Формат: "type_code" → ("Фаза", phase_order)
# ──────────────────────────────────────────────────────────────────────────────

CODE_TO_PHASE = {
    "6101": ("Земляные работы",                  1),
    "6102": ("Фундаменты",                       2),
    "6103": ("Монолитный каркас",                3),
    "6104": ("Каменные работы",                  4),
    "6105": ("Металлические конструкции",         5),
    "6106": ("Деревянные конструкции",            6),
    "6107": ("Окна и двери",                     7),
    "6108": ("Отделочные работы",                8),
    "6109": ("Полы",                             9),
    "6110": ("Кровля наружная",                 10),
    "6111": ("Гидро- и пароизоляция",           11),
    "6112": ("Отделочные работы",                  8),   # default: штукатурка, покраска
    "6112-01": ("Отделочные работы",               8),   # штукатурка
    "6112-02": ("Отделочные работы",               8),   # штукатурка/покраска
    "6112-03": ("Отделочные работы",               8),   # покраска
    "6112-04": ("Отделочные работы",               8),   # покраска
    "6112-05": ("Отделочные работы",               8),   # прочая отделка
    "6112-0401": ("Фасадные работы",              14),   # облицовка фасада
    "6112-0501": ("Отделочные работы",             8),   # подвесные потолки
    "6113": ("Благоустройство некритичное",      14),  # default → некритично
    "6113-01": ("Благоустройство некритичное",   14),  # газоны, посев — НЕКРИТИЧНО
    "6113-02": ("Благоустройство некритичное",   14),  # посадочные места
    "6113-03": ("Благоустройство обязательное",  13),  # дорожки, брусчатка — ОБЯЗАТЕЛЬНО
    "6113-04": ("Благоустройство обязательное",  13),  # спортивные покрытия — ОБЯЗАТЕЛЬНО
    "6113-05": ("Благоустройство некритичное",   14),  # прочее озеленение
    "6114": ("Водоснабжение и канализация",      21),  # наружные трубопроводы
    "6114-01": ("Водоснабжение и канализация",    21),  # водоснабжение наружное
    "6114-02": ("Водоснабжение и канализация",    21),  # водоснабжение наружное
    "6114-03": ("Водоснабжение и канализация",    21),  # водоснабжение/канализация
    "6114-04": ("Водоснабжение и канализация",    21),  # гидравлические испытания
    "6114-05": ("Отопление и теплоснабжение",     19),  # теплоснабжение наружное
    "6114-06": ("Водоснабжение и канализация",    21),  # канализация наружная
    "6114-07": ("Водоснабжение и канализация",    21),  # водоснабжение
    "6114-08": ("Водоснабжение и канализация",    21),  # водоснабжение
    "6115": ("Фасадные работы",                 14),
    "6116": ("Лестницы и площадки",             15),
    "6117": ("Перегородки",                     16),
    "6118": ("Прочие работы",                   17),
    "6119": ("Электроснабжение",                18),
    "6120": ("Отопление и теплоснабжение",      19),
    "6121": ("Вентиляция и кондиционирование",  20),
    "6122": ("Водоснабжение и канализация",     21),
    "6123": ("Слаботочные системы",             22),
    "6124": ("Электроснабжение",                18),  # слаботочка/электро
    "6125": ("Слаботочные системы",             22),
}


def resolve_phase(code: str, phase_from_parser: str, phase_order_from_parser: int):
    """
    Определяет правильную фазу по коду (CODE_TO_PHASE).
    Если код известен — переопределяет фазу из парсера.
    Возвращает (phase, phase_order, was_corrected).
    """
    if not code:
        return phase_from_parser, phase_order_from_parser, False
    type_code = code.split("-")[0]
    if type_code in CODE_TO_PHASE:
        correct_phase, correct_order = CODE_TO_PHASE[type_code]
        was_corrected = (correct_phase != phase_from_parser)
        return correct_phase, correct_order, was_corrected
    return phase_from_parser, phase_order_from_parser, False


def normalize_unit(unit: str) -> str:
    """Нормализация единиц для сравнения."""
    if not unit:
        return ""
    aliases = {
        "м²": "м2", "кв.м": "м2", "кв.м.": "м2",
        "м³": "м3", "куб.м": "м3",
        "п.м": "м", "п.м.": "м", "пог.м": "м", "пм": "м",
        "шт.": "шт", "штук": "шт",
        "компл": "шт", "компл.": "шт",
        "тн": "т",
    }
    u = unit.strip().lower()
    return aliases.get(u, u)


def calc_duration(volume: float, rate: float, min_days: int = 1) -> int:
    """Рассчитывает длительность с минимальным порогом."""
    if rate <= 0:
        return min_days
    raw = volume / rate
    return max(min_days, math.ceil(raw))


# ─── Основной движок ─────────────────────────────────────────────────────────

class DurationEngineV7:

    def __init__(self, input_path: str = "smeta_works_clean.json"):
        self.input_path = input_path
        self.works: list = []
        self.results: list = []
        self.unresolved: list = []

    def load(self):
        print(f"[Duration] Читаю {self.input_path}...")
        with open(self.input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            for key in ("work_items", "works", "items"):
                if key in data and isinstance(data[key], list):
                    self.works = data[key]
                    break
            if not self.works:
                for v in data.values():
                    if isinstance(v, list):
                        self.works = v
                        break
        elif isinstance(data, list):
            self.works = data

        # Только работы с объёмом
        valid = [w for w in self.works
                 if w.get("has_volume") and w.get("volume")
                 and w.get("qa_status") != "skipped"]
        print(f"[Duration] Загружено: {len(self.works)} строк "
              f"→ с объёмом: {len(valid)}")
        self.works = valid

    def process(self, verbose: bool = False):
        print(f"[Duration] Расчёт длительностей...")
        phase_corrections = 0

        for w in self.works:
            code    = w.get("code", "")
            name    = w.get("name", "")
            unit    = normalize_unit(w.get("unit", ""))
            volume  = w.get("volume", 0)
            subgroup = w.get("subgroup", "")
            page    = w.get("page")

            # КОД определяет фазу (принцип Аяна) — переопределяем фазу из парсера
            phase, phase_order, phase_corrected = resolve_phase(
                code,
                w.get("phase", ""),
                w.get("phase_order", 99),
            )
            if phase_corrected:
                phase_corrections += 1

            rate_info = resolve_rate(code)

            if rate_info is None:
                self.unresolved.append({
                    "code": code, "name": name[:60],
                    "unit": unit, "volume": volume,
                    "phase": phase,
                })
                continue

            # Проверка совместимости единиц
            expected_unit = normalize_unit(rate_info.get("unit", ""))
            unit_ok = (unit == expected_unit) or not unit

            # Расчёт
            days = calc_duration(volume, rate_info["rate"])

            result = {
                "code":          code,
                "name":          name[:80],
                "unit":          unit,
                "volume":        volume,
                "phase":         phase,
                "phase_order":   phase_order,
                "phase_corrected": phase_corrected,
                "phase_original": w.get("phase", "") if phase_corrected else None,
                "subgroup":      subgroup,
                "page":          page,
                "parallel_in_phase": w.get("parallel_in_phase", True),
                "qa_status":     w.get("qa_status", "ok"),
                # Норма
                "rate_label":    rate_info["label"],
                "rate_per_day":  rate_info["rate"],
                "rate_unit":     rate_info.get("unit"),
                "match_level":   rate_info["match_level"],
                "unit_match":    unit_ok,
                # Результат
                "duration_days": days,
                "calculation":   f"{volume} {unit} / {rate_info['rate']} = {days} дн.",
            }

            self.results.append(result)

            if verbose:
                lvl = {"full": "✓✓", "group": "✓~", "type": "~"}[rate_info["match_level"]]
                corr = " ✏️" if phase_corrected else ""
                print(f"  {lvl} {code:<20} {str(volume):>8} {unit:<4} → {days:>4} дн.  "
                      f"[{rate_info['match_level']}]  {phase[:20]}{corr}")

        if phase_corrections:
            print(f"[Duration] ✏️  Фаз исправлено по коду: {phase_corrections}")

    def build_phase_summary(self) -> list:
        """
        ПАРАЛЛЕЛЬНОСТЬ (принцип Аяна):
        Внутри фазы работы идут параллельно → phase_duration = max(), не sum()
        """
        phase_map = defaultdict(list)
        for r in self.results:
            phase_map[(r["phase"], r.get("phase_order", 99))].append(r["duration_days"])

        summary = []
        for (phase, order), durations in sorted(phase_map.items(), key=lambda x: x[0][1]):
            # КЛЮЧЕВОЕ: max() не sum()
            phase_duration = max(durations)
            summary.append({
                "phase":            phase,
                "phase_order":      order,
                "work_count":       len(durations),
                "duration_days":    phase_duration,
                "duration_months":  round(phase_duration / 30, 1),
                # Для прозрачности — показываем что было бы при sum
                "sum_if_sequential": sum(durations),
                "parallel_saving_days": sum(durations) - phase_duration,
                "note":             "parallel_in_phase=True → max(durations)",
            })

        return summary

    def save(self,
             estimates_path: str = "duration_estimates.json",
             summary_path:   str = "duration_summary.json",
             unresolved_path: str = "duration_unresolved.json"):

        phase_summary = self.build_phase_summary()

        # duration_estimates.json — детально по каждой работе
        with open(estimates_path, "w", encoding="utf-8") as f:
            json.dump({
                "engine_version": "7.0",
                "total_works":    len(self.results),
                "estimates":      self.results,
            }, f, ensure_ascii=False, indent=2)
        print(f"[Duration] ✅ {estimates_path} ({len(self.results)} работ)")

        # duration_summary.json — итог по фазам
        total_seq      = sum(p["sum_if_sequential"] for p in phase_summary)
        total_parallel = sum(p["duration_days"] for p in phase_summary)
        critical_path  = max((p["duration_days"] for p in phase_summary), default=0)

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "engine_version": "7.0",
                "duration": {
                    "sequential_days":  total_seq,
                    "sequential_months": round(total_seq / 30, 1),
                    "parallel_days":    total_parallel,
                    "parallel_months":  round(total_parallel / 30, 1),
                    "critical_path_days": critical_path,
                    "note": "parallel_days = сумма max() по каждой фазе",
                },
                "phases": phase_summary,
            }, f, ensure_ascii=False, indent=2)
        print(f"[Duration] ✅ {summary_path}")

        # duration_unresolved.json
        with open(unresolved_path, "w", encoding="utf-8") as f:
            json.dump({
                "count": len(self.unresolved),
                "note":  "Коды не найдены в PRODUCTION_RATES — добавь нормы",
                "items": self.unresolved,
            }, f, ensure_ascii=False, indent=2)
        print(f"[Duration] ℹ️  {unresolved_path} ({len(self.unresolved)} без нормы)")

        self._print_summary(phase_summary, total_seq, total_parallel, critical_path)

    def _print_summary(self, phases, total_seq, total_parallel, critical):
        print()
        print("=" * 65)
        print("  DURATION ENGINE v7.0 — РЕЗУЛЬТАТ")
        print("=" * 65)
        print(f"  Работ рассчитано:    {len(self.results)}")
        print(f"  Без нормы (пропущ.): {len(self.unresolved)}")
        print()
        print("  ДЛИТЕЛЬНОСТИ ПО ФАЗАМ (parallel_in_phase = max):")
        print(f"  {'Фаза':<35} {'max':>6}  {'(sum)':>8}  {'экономия':>9}")
        print(f"  {'─'*63}")
        for p in phases:
            saving = p["parallel_saving_days"]
            bar = "█" * min(20, p["duration_days"] // 15)
            print(f"  {p['phase']:<35} {p['duration_days']:>6}  "
                  f"({p['sum_if_sequential']:>6})  -{saving:>6} дн.  {bar}")
        print(f"  {'─'*63}")
        print(f"  {'ИТОГО (сумма фаз)':<35} {total_parallel:>6}  ({total_seq:>6})")
        print(f"  {'Критический путь (макс. фаза)':<35} {critical:>6} дн.")
        print()
        print(f"  Последовательно: {total_seq} дн. = {round(total_seq/30,1)} мес.")
        print(f"  С параллельностью: {total_parallel} дн. = {round(total_parallel/30,1)} мес.")
        print()
        print("  СЛЕДУЮЩИЙ ШАГ: GPR Builder → gpr_builder.py")
        print("=" * 65)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AINTELLECTUM Duration Engine v7.0")
    parser.add_argument("input",   nargs="?", default="smeta_works_clean.json")
    parser.add_argument("--verbose", "-v",    action="store_true")
    parser.add_argument("--estimates",  default="duration_estimates.json")
    parser.add_argument("--summary",    default="duration_summary.json")
    parser.add_argument("--unresolved", default="duration_unresolved.json")
    args = parser.parse_args()

    print("=" * 65)
    print("  DURATION ENGINE v7.0 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  Параллельность: phase_duration = max(), не sum()")
    print("=" * 65)

    engine = DurationEngineV7(args.input)
    engine.load()
    engine.process(verbose=args.verbose)
    engine.save(args.estimates, args.summary, args.unresolved)