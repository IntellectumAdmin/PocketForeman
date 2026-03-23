# -*- coding: utf-8 -*-
"""
Materials Extractor v2.0
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

ИЗМЕНЕНИЯ v2.0 vs v1.0:
  - Читает smeta_materials_raw.json (от smeta_core_parser v4.0)
  - 8625 материалов вместо 0
  - Связывает материалы с работами через page/table контекст
  - QA проверка объёмов материалов

Принцип (от Аяна):
  materials_extractor работает на smeta_materials_raw.json
  НЕ ищет 2xxx в smeta_works_v2.json (там их нет по определению)

Входные файлы:
  smeta_materials_raw.json  (от smeta_core_parser v4.0)

Выходные файлы:
  materials_plan.json      — план снабжения по типам и фазам
  materials_summary.json   — сводка для инженера

ИСПОЛЬЗОВАНИЕ:
  python materials_extractor.py
  python materials_extractor.py smeta_materials_raw.json
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict


# ─── Классификатор материалов по коду 2xxx ───────────────────────────────────

# Классификатор по 3-значному префиксу (реальная структура РСНБ РК)
MATERIAL_TYPE_MAP = {
    # Нерудные
    "211": "Нерудные материалы",
    # Бетон и растворы
    "212": "Бетон и растворы",
    "213": "Бетон и растворы",
    # Металлы и метизы
    "214": "Металлы и метизы",
    "217": "Металлы и метизы",
    "222": "Металлы и метизы",
    # Пиломатериалы
    "215": "Пиломатериалы",
    # Вяжущие и сыпучие
    "216": "Вяжущие и сыпучие",
    # Прочие строительные
    "218": "Прочие строительные",
    "219": "Прочие строительные",
    "221": "Прочие строительные",
    # Отделочные
    "231": "Отделочные материалы",
    "232": "Отделочные материалы",
    "233": "Отделочные материалы",
    # Изоляционные и кровельные
    "234": "Изоляционные материалы",
    "235": "Кровельные материалы",
    # Химия
    "236": "Химия и растворители",
    # Трубы и арматура
    "241": "Трубы и трубопроводы",
    "242": "Трубопроводная арматура",
    # Электро
    "243": "Электромонтажные материалы",
    "244": "Электромонтажные материалы",
    "245": "Электромонтажные материалы",
    "247": "Электромонтажные материалы",
    # Вентиляция
    "246": "Вентиляционные изделия",
    # Пожарная защита
    "248": "Противопожарные материалы",
    # Расходные
    "251": "Расходные материалы",
    "261": "Расходные материалы",
    "262": "Расходные материалы",
    "271": "Прочие материалы",
}

# Привязка типа материала к фазе строительства
MATERIAL_TO_PHASE = {
    "211": "Земляные работы",
    "212": "Монолитный каркас",
    "213": "Монолитный каркас",
    "214": "Монолитный каркас",
    "215": "Деревянные конструкции",
    "216": "Монолитный каркас",
    "217": "Монолитный каркас",
    "218": "Прочие работы",
    "221": "Монолитный каркас",
    "222": "Металлические конструкции",
    "231": "Отделочные работы",
    "232": "Отделочные работы",
    "233": "Отделочные работы",
    "234": "Гидро- и пароизоляция",
    "235": "Кровля наружная",
    "236": "Отделочные работы",
    "241": "Водоснабжение и канализация",
    "242": "Водоснабжение и канализация",
    "243": "Электроснабжение",
    "244": "Электроснабжение",
    "245": "Электроснабжение",
    "246": "Вентиляция и кондиционирование",
    "247": "Электроснабжение",
    "248": "Прочие работы",
    "251": "Прочие работы",
    "261": "Прочие работы",
    "271": "Прочие работы",
}

UNIT_NORMALIZE = {
    "м²": "м2", "кв.м": "м2", "кв.м.": "м2",
    "м³": "м3", "куб.м": "м3",
    "п.м": "м", "п.м.": "м", "пог.м": "м",
    "шт.": "шт", "штук": "шт",
    "компл.": "компл", "комплект": "компл",
    "тн": "т", "тонн": "т",
}


def normalize_unit(unit: str) -> str:
    if not unit:
        return ""
    u = unit.strip()
    return UNIT_NORMALIZE.get(u, UNIT_NORMALIZE.get(u.lower(), u))


def classify_material(code: str) -> tuple:
    """Возвращает (type_label, supply_phase) по коду 2xxx.
    Использует 3-значный префикс (реальная структура РСНБ РК).
    """
    if not code or not code.startswith("2"):
        return "Прочие материалы", "Прочие работы"
    # Берём первые 3 цифры: 211-201-0607 → "211"
    prefix3 = code[:3]
    label = MATERIAL_TYPE_MAP.get(prefix3, "Прочие материалы")
    phase = MATERIAL_TO_PHASE.get(prefix3, "Прочие работы")
    return label, phase


# ─── QA проверки объёмов ─────────────────────────────────────────────────────

UNIT_THRESHOLDS = {
    "м3":  (0.001, 50_000),
    "м2":  (0.001, 500_000),
    "м":   (0.001, 1_000_000),
    "т":   (0.001, 100_000),
    "кг":  (0.001, 5_000_000),
    "шт":  (0.001, 2_000_000),
    "компл": (0.001, 10_000),
}

def check_volume_qa(volume, unit: str) -> str:
    """Возвращает qa_status: ok / suspicious / no_volume."""
    if volume is None or volume == 0:
        return "no_volume"
    try:
        v = float(volume)
    except (TypeError, ValueError):
        return "no_volume"
    if v <= 0:
        return "no_volume"
    min_v, max_v = UNIT_THRESHOLDS.get(
        normalize_unit(unit), (0.001, 10_000_000)
    )
    if v > max_v or v < min_v:
        return "suspicious"
    return "ok"


# ─── Основной класс ──────────────────────────────────────────────────────────

class MaterialsExtractor:

    def __init__(self, input_path: str = "smeta_materials_raw.json"):
        self.input_path = input_path
        self.raw_items = []
        self.materials = []

    def load(self):
        print(f"[Materials] Читаю {self.input_path}...")
        with open(self.input_path, encoding="utf-8") as f:
            data = json.load(f)

        # Поддерживаем оба формата
        if isinstance(data, dict):
            for key in ("material_items", "work_items", "items"):
                if key in data and isinstance(data[key], list):
                    self.raw_items = data[key]
                    break
            if not self.raw_items:
                for v in data.values():
                    if isinstance(v, list) and len(v) > 0:
                        self.raw_items = v
                        break
        elif isinstance(data, list):
            self.raw_items = data

        print(f"[Materials] Загружено строк: {len(self.raw_items)}")

    def extract(self):
        print(f"[Materials] Обрабатываю материалы...")

        for row in self.raw_items:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code", "")).strip()
            if not code or not code.startswith("2"):
                continue

            name     = str(row.get("name", "")).strip()
            unit     = normalize_unit(str(row.get("unit", "")).strip())
            volume   = row.get("volume")
            page     = row.get("page")
            tbl_idx  = row.get("source_table_index")
            row_idx  = row.get("row_index_in_table")

            try:
                vol_float = float(volume) if volume is not None else None
                if vol_float is not None and vol_float <= 0:
                    vol_float = None
            except (TypeError, ValueError):
                vol_float = None

            mat_type, supply_phase = classify_material(code)
            qa_status = check_volume_qa(vol_float, unit)

            self.materials.append({
                "code":               code,
                "name":               name[:100],
                "unit":               unit,
                "volume":             vol_float,
                "has_volume":         vol_float is not None,
                "material_type":      mat_type,
                "supply_phase":       supply_phase,
                "qa_status":          qa_status,
                # Контекст для связки с работами (от Аяна)
                "page":               page,
                "source_table_index": tbl_idx,
                "row_index_in_table": row_idx,
            })

        with_vol = sum(1 for m in self.materials if m["has_volume"])
        print(f"[Materials] Обработано:  {len(self.materials)} материалов")
        print(f"[Materials] С объёмом:   {with_vol}")
        print(f"[Materials] Без объёма:  {len(self.materials) - with_vol}")

    def build_plan(self) -> dict:
        """Группирует материалы по типам и фазам."""

        # По типам материалов
        by_type = defaultdict(list)
        for m in self.materials:
            by_type[m["material_type"]].append(m)

        # По фазам снабжения
        by_phase = defaultdict(list)
        for m in self.materials:
            by_phase[m["supply_phase"]].append(m)

        types_plan = []
        for mat_type, items in sorted(by_type.items()):
            # Агрегируем объёмы по единицам
            unit_totals = defaultdict(float)
            for i in items:
                if i["has_volume"] and i["unit"]:
                    unit_totals[i["unit"]] += i["volume"]

            qa_ok   = sum(1 for i in items if i["qa_status"] == "ok")
            qa_susp = sum(1 for i in items if i["qa_status"] == "suspicious")
            qa_none = sum(1 for i in items if i["qa_status"] == "no_volume")

            types_plan.append({
                "material_type":  mat_type,
                "items_count":    len(items),
                "volume_by_unit": {
                    u: round(v, 3) for u, v in sorted(
                        unit_totals.items(), key=lambda x: -x[1])
                },
                "qa": {"ok": qa_ok, "suspicious": qa_susp, "no_volume": qa_none},
                "top_items": sorted(
                    [i for i in items if i["has_volume"]],
                    key=lambda x: -(x["volume"] or 0)
                )[:5],
            })

        phases_plan = []
        for phase, items in sorted(by_phase.items()):
            phases_plan.append({
                "supply_phase":  phase,
                "items_count":   len(items),
                "with_volume":   sum(1 for i in items if i["has_volume"]),
                "material_types": sorted(set(i["material_type"] for i in items)),
            })

        return {
            "types_plan":   sorted(types_plan, key=lambda x: -x["items_count"]),
            "phases_plan":  sorted(phases_plan, key=lambda x: -x["items_count"]),
        }

    def save(self,
             plan_path: str = "materials_plan.json",
             summary_path: str = "materials_summary.json"):

        plan = self.build_plan()

        # materials_plan.json — полный список материалов
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump({
                "extractor_version": "2.0",
                "source":            self.input_path,
                "total_materials":   len(self.materials),
                "types_plan":        plan["types_plan"],
                "phases_plan":       plan["phases_plan"],
                "all_materials":     self.materials,
            }, f, ensure_ascii=False, indent=2)
        size = Path(plan_path).stat().st_size
        print(f"[Materials] ✅ {plan_path} ({size // 1024} КБ)")

        # materials_summary.json — сводка для инженера
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "extractor_version": "2.0",
                "total_materials":   len(self.materials),
                "with_volume":       sum(1 for m in self.materials if m["has_volume"]),
                "types_plan":        plan["types_plan"],
                "phases_plan":       plan["phases_plan"],
            }, f, ensure_ascii=False, indent=2)
        size = Path(summary_path).stat().st_size
        print(f"[Materials] ✅ {summary_path} ({size // 1024} КБ)")

        self._print_summary(plan)

    def _print_summary(self, plan: dict):
        total = len(self.materials)
        with_vol = sum(1 for m in self.materials if m["has_volume"])
        print()
        print("=" * 65)
        print("  MATERIALS EXTRACTOR v2.0 — РЕЗУЛЬТАТ")
        print("=" * 65)
        print(f"  Материалов всего:    {total}")
        print(f"  С объёмом:           {with_vol}")
        print(f"  Без объёма:          {total - with_vol}")
        print()
        print("  ТИПЫ МАТЕРИАЛОВ:")
        for tp in plan["types_plan"]:
            vols = ", ".join(
                f"{round(v, 1)} {u}"
                for u, v in list(tp["volume_by_unit"].items())[:3]
            )
            qa = tp["qa"]
            print(f"  {tp['material_type']:<35} "
                  f"{tp['items_count']:>5} строк  "
                  f"ok:{qa['ok']} susp:{qa['suspicious']}  "
                  f"{vols}")
        print()
        print("  ПО ФАЗАМ СНАБЖЕНИЯ:")
        for pp in plan["phases_plan"]:
            print(f"  {pp['supply_phase']:<35} "
                  f"{pp['items_count']:>5} строк  "
                  f"({pp['with_volume']} с объёмом)")
        print()
        print("  Файлы: materials_plan.json, materials_summary.json")
        print("  Следующий шаг: Finance Layer → cash flow")
        print("=" * 65)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AINTELLECTUM Materials Extractor v2.0"
    )
    parser.add_argument(
        "input", nargs="?",
        default="smeta_materials_raw.json",
        help="Входной файл (smeta_materials_raw.json от smeta_core_parser v4.0)"
    )
    parser.add_argument("--plan",    default="materials_plan.json")
    parser.add_argument("--summary", default="materials_summary.json")
    args = parser.parse_args()

    print("=" * 65)
    print("  MATERIALS EXTRACTOR v2.0 — AINTELLECTUM")
    print("  Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("  Источник: smeta_materials_raw.json (от Core Parser v4.0)")
    print("=" * 65)
    print()

    extractor = MaterialsExtractor(args.input)
    extractor.load()
    extractor.extract()
    extractor.save(args.plan, args.summary)