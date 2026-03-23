"""Диагностика кодов материалов — смотрим реальную структуру 2xxx"""
import json, sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else "smeta_materials_raw.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

items = data.get("material_items", data.get("work_items", []))
if not items:
    for v in data.values():
        if isinstance(v, list): items = v; break

print(f"Всего строк: {len(items)}\n")

# Смотрим первые 3 цифры кода (prefix)
prefix3 = Counter(i.get("code","")[:3] for i in items if i.get("code","").startswith("2"))
print("ТОП-20 ПРЕФИКСОВ (первые 3 цифры):")
for code, cnt in prefix3.most_common(20):
    # Найдём пример названия
    example = next((i.get("name","")[:50] for i in items
                    if i.get("code","").startswith(code)), "")
    print(f"  {code}  {cnt:>5} строк  {example}")

print()
# Смотрим структуру кода
print("ПРИМЕРЫ РЕАЛЬНЫХ КОДОВ (первые 15):")
seen = set()
for i in items[:200]:
    code = i.get("code","")
    prefix = code[:5]
    if prefix not in seen:
        seen.add(prefix)
        print(f"  {code:<25} {i.get('name','')[:50]}")
    if len(seen) >= 15:
        break