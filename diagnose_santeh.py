"""
Диагностика по фазе "Сантехника (санузлы)" — по совету Аяна
Смотрим какие full_code дали 252 дня
"""
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "duration_estimates.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

# Топ-10 по фазе Сантехника
santeh = [e for e in data.get("estimates", [])
          if "антехник" in e.get("phase", "") or "санузл" in e.get("phase", "").lower()]
santeh.sort(key=lambda x: -(x.get("duration_days") or 0))

print(f"Всего строк в фазе Сантехника: {len(santeh)}")
print()
print(f"{'Дней':>6}  {'Код':<22} {'Объём':>10} {'Ед':>5}  Название")
print("─" * 90)
for e in santeh[:15]:
    print(f"{e.get('duration_days',0):>6}  "
          f"{e.get('code',''):<22} "
          f"{str(e.get('volume','')):>10} "
          f"{str(e.get('unit','')):>5}  "
          f"{str(e.get('name',''))[:40]}")

print()
# Уникальные type_code
codes = set(e.get('code','')[:4] for e in santeh)
print(f"Типовые коды в фазе: {sorted(codes)}")
print()
# Сколько 6112 vs остальные
c6112 = [e for e in santeh if e.get('code','').startswith('6112')]
other = [e for e in santeh if not e.get('code','').startswith('6112')]
print(f"6112-коды: {len(c6112)} строк")
print(f"Другие:    {len(other)} строк")