"""
Volume QA Engine v2.0
AINTELLECTUM | Школа №65, Уральск
Ереке (капитан) | Аян (архитектор) | Claude (разработчик)

Архитектурный принцип (от Аяна):
  Не угадываем смету. Не интерпретируем. Не классифицируем по словам.
  1. Читаем таблицу
  2. Читаем полный код
  3. Строим систему на строгих данных

Задача:
  smeta_works_v2.json  →  smeta_works_clean.json  +  volume_qa_report.json
"""

import json
import re
import statistics
from collections import defaultdict


# ─── Нормализация единиц ─────────────────────────────────────────────────────

UNIT_NORMALIZE_MAP = {
    "м²": "м2", "кв.м": "м2", "кв.м.": "м2", "м^2": "м2", "квм": "м2",
    "m2": "м2", "кв м": "м2",
    "м³": "м3", "куб.м": "м3", "куб.м.": "м3", "м^3": "м3", "куб м": "м3",
    "кубометр": "м3", "m3": "м3",
    "пог.м": "п.м", "п/м": "п.м", "пм": "п.м",
    "погонный метр": "п.м", "п.м.": "п.м",
    "шт.": "шт", "штук": "шт", "штука": "шт",
    "ед": "шт", "ед.": "шт",
    "компл.": "компл", "комплект": "компл",
    "тн": "т", "тонн": "т", "тонна": "т",
}

KM_TO_M = {"км": 1000, "km": 1000}


def normalize_unit(raw_unit: str):
    if not raw_unit:
        return "", 1.0
    u = raw_unit.strip()
    if u.lower() in KM_TO_M:
        return "м", float(KM_TO_M[u.lower()])
    normalized = UNIT_NORMALIZE_MAP.get(u, UNIT_NORMALIZE_MAP.get(u.lower(), u))
    return normalized, 1.0


# ─── Нормализация объёма ─────────────────────────────────────────────────────

def normalize_volume(raw_volume):
    flags = []
    if raw_volume is None:
        return None, ["no_volume"]

    if isinstance(raw_volume, (int, float)):
        v = float(raw_volume)
        if v < 0:
            return None, ["volume_negative"]
        if v == 0:
            return None, ["no_volume"]
        return v, flags

    if isinstance(raw_volume, str):
        s = raw_volume.strip()
        if not s:
            return None, ["no_volume"]
        s = s.replace(" ", "").replace(",", ".")
        s = re.sub(r"[^\d.\-]", "", s)
        if not s:
            return None, ["parse_error"]
        try:
            v = float(s)
            if v < 0:
                return None, ["volume_negative"]
            if v == 0:
                return None, ["no_volume"]
            flags.append("volume_corrected")
            return v, flags
        except ValueError:
            return None, ["parse_error"]

    return None, ["parse_error"]


# ─── Классификация кода ───────────────────────────────────────────────────────

def classify_code(code: str) -> str:
    if not code:
        return "unknown"
    c = code.strip()
    if c.startswith("6"):
        return "work"
    if c.startswith("2"):
        return "material"
    if c.startswith("3"):
        return "equipment"
    return "unknown"


# ─── Основной класс ──────────────────────────────────────────────────────────

class VolumeQAEngine:

    def __init__(self, input_path: str):
        self.input_path = input_path
        self.raw_items = []
        self.clean_items = []
        self.report = {}

    def load(self):
        print(f"[QA] Читаю {self.input_path}...")
        with open(self.input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Поддерживаем оба формата JSON
        if isinstance(data, dict):
            # Ищем список работ по известным ключам
            for key in ("work_items", "works", "items"):
                if key in data and isinstance(data[key], list):
                    self.raw_items = data[key]
                    break
            # Fallback: первый список в значениях
            if not self.raw_items:
                for v in data.values():
                    if isinstance(v, list) and len(v) > 0:
                        self.raw_items = v
                        break
        elif isinstance(data, list):
            self.raw_items = data
        else:
            raise ValueError(f"Неожиданный формат JSON: {type(data)}")

        print(f"[QA] Загружено строк: {len(self.raw_items)}")

    def process_item(self, raw: dict) -> dict:
        # Безопасная копия без dict(w) — через comprehension
        item = {k: v for k, v in raw.items()}
        flags = []

        code = str(item.get("code", "")).strip()

        # Нет кода
        if not code:
            flags.append("invalid_code")
            item["qa_status"] = "error"
            item["qa_flags"] = flags
            return item

        # Тип кода
        code_type = classify_code(code)
        item["code_type"] = code_type

        if code_type == "material":
            item["qa_status"] = "skipped"
            item["qa_flags"] = ["skipped_material"]
            return item

        if code_type == "equipment":
            item["qa_status"] = "skipped"
            item["qa_flags"] = ["skipped_equipment"]
            return item

        if code_type == "unknown":
            flags.append("unknown_code_prefix")

        # Нормализация единицы
        raw_unit = str(item.get("unit", "")).strip()
        norm_unit, multiplier = normalize_unit(raw_unit)

        if raw_unit and norm_unit != raw_unit:
            flags.append("unit_normalized")
            item["unit_original"] = raw_unit
            item["unit"] = norm_unit
        elif not raw_unit:
            flags.append("unit_missing")

        # Нормализация объёма
        raw_volume = item.get("volume")
        volume, vol_flags = normalize_volume(raw_volume)
        flags.extend(vol_flags)

        if volume is not None:
            volume = round(volume * multiplier, 6)
            item["volume"] = volume
            item["has_volume"] = True
            if multiplier != 1.0:
                item["volume_original"] = raw_volume
        else:
            item["volume"] = None
            item["has_volume"] = False

        # Статус
        if "invalid_code" in flags:
            status = "error"
        elif "no_volume" in flags or "parse_error" in flags or flags:
            status = "warning"
        else:
            status = "ok"

        item["qa_status"] = status
        item["qa_flags"] = flags
        return item

    def detect_group_anomalies(self):
        """Ищет выбросы внутри phase+subgroup."""
        groups = defaultdict(list)
        for item in self.clean_items:
            if item.get("qa_status") == "skipped":
                continue
            if not item.get("has_volume"):
                continue
            key = (item.get("phase", ""), item.get("subgroup", ""))
            groups[key].append(item)

        for key, items in groups.items():
            if len(items) < 3:
                continue
            volumes = [it["volume"] for it in items
                       if it.get("volume") and it["volume"] > 0]
            if not volumes:
                continue
            med = statistics.median(volumes)
            if med == 0:
                continue
            for item in items:
                v = item.get("volume", 0) or 0
                if v > med * 50:
                    if "suspicious_large" not in item["qa_flags"]:
                        item["qa_flags"].append("suspicious_large")
                    item["qa_status"] = "warning"
                elif v > 0 and v < med / 50:
                    if "suspicious_small" not in item["qa_flags"]:
                        item["qa_flags"].append("suspicious_small")
                    item["qa_status"] = "warning"

    def add_parallelism_flags(self):
        """Все работы фазы — параллельные. Duration Engine использует max()."""
        for item in self.clean_items:
            if (item.get("code_type") == "work"
                    and item.get("qa_status") != "skipped"):
                item["parallel_in_phase"] = True

    def run(self):
        self.load()
        for raw in self.raw_items:
            if not isinstance(raw, dict):
                continue
            self.clean_items.append(self.process_item(raw))
        self.detect_group_anomalies()
        self.add_parallelism_flags()
        self._build_report()

    def _build_report(self):
        status_counter = defaultdict(int)
        flags_counter = defaultdict(int)
        top_anomalies = []

        for item in self.clean_items:
            status_counter[item.get("qa_status", "unknown")] += 1
            for f in item.get("qa_flags", []):
                flags_counter[f] += 1
            if "suspicious_large" in item.get("qa_flags", []):
                top_anomalies.append({
                    "code":   item.get("code"),
                    "name":   str(item.get("name", ""))[:60],
                    "unit":   item.get("unit"),
                    "volume": item.get("volume"),
                    "phase":  item.get("phase"),
                    "flag":   "suspicious_large",
                })

        total = len(self.clean_items)
        ok = status_counter.get("ok", 0)

        self.report = {
            "meta": {
                "source": self.input_path,
                "total_items": total,
                "engine_version": "2.0",
            },
            "summary": {
                "ok":      ok,
                "warning": status_counter.get("warning", 0),
                "error":   status_counter.get("error", 0),
                "skipped": status_counter.get("skipped", 0),
                "ok_pct":  round(ok / total * 100, 1) if total else 0,
            },
            "flags_count": dict(
                sorted(flags_counter.items(), key=lambda x: -x[1])
            ),
            "top_anomalies": sorted(
                top_anomalies, key=lambda x: -(x["volume"] or 0)
            )[:20],
        }

    def save(self,
             clean_path: str = "smeta_works_clean.json",
             report_path: str = "volume_qa_report.json"):

        works_only = [
            it for it in self.clean_items
            if it.get("qa_status") != "skipped"
        ]

        with open(clean_path, "w", encoding="utf-8") as f:
            json.dump({"work_items": works_only}, f,
                      ensure_ascii=False, indent=2)
        print(f"[QA] ✅ {clean_path} ({len(works_only)} работ)")

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        print(f"[QA] ✅ {report_path}")

        self._print_summary()

    def _print_summary(self):
        s = self.report["summary"]
        total = self.report["meta"]["total_items"]
        print()
        print("=" * 60)
        print("  VOLUME QA REPORT v2.0")
        print("=" * 60)
        print(f"  Всего строк:      {total}")
        print(f"  ok:               {s['ok']}")
        print(f"  warning:          {s['warning']}")
        print(f"  error:            {s['error']}")
        print(f"  skipped (2/3xxx): {s['skipped']}")
        print(f"  Качество данных:  {s['ok_pct']}%")
        print()
        print("  ТОП ФЛАГОВ:")
        for flag, cnt in list(self.report["flags_count"].items())[:8]:
            print(f"    {flag:<30} {cnt:>5}")
        if self.report["top_anomalies"]:
            print()
            print("  АНОМАЛЬНО БОЛЬШИЕ ОБЪЁМЫ:")
            for a in self.report["top_anomalies"][:5]:
                print(f"    {str(a['code']):<22} {str(a['volume']):>12}"
                      f" {str(a['unit']):<6}  {a['phase']}")
        print()
        print("  СЛЕДУЮЩИЙ ШАГ — Duration Engine:")
        print("  phase_duration = max(durations)  # parallel_in_phase=True")
        print("=" * 60)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    input_file  = sys.argv[1] if len(sys.argv) > 1 else "smeta_works_v2.json"
    clean_file  = sys.argv[2] if len(sys.argv) > 2 else "smeta_works_clean.json"
    report_file = sys.argv[3] if len(sys.argv) > 3 else "volume_qa_report.json"

    engine = VolumeQAEngine(input_file)
    engine.run()
    engine.save(clean_file, report_file)