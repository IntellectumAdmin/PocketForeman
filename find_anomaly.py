"""Быстрый анализ duration_estimates.json — ищем 569-дневный элемент"""
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "duration_estimates.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

estimates = data.get("estimates", [])

# Топ-20 самых долгих работ
top = sorted(estimates, key=lambda x: -(x.get("duration_days") or 0))[:20]

print(f"{'Дней':>6}  {'Код':<22} {'Объём':>10} {'Ед':>5}  {'Фаза':<28} Расчёт")
print("─" * 110)
for e in top:
    print(f"{e.get('duration_days',0):>6}  "
          f"{e.get('code',''):<22} "
          f"{str(e.get('volume','')):>10} "
          f"{str(e.get('unit','')):>5}  "
          f"{e.get('phase',''):<28} "
          f"{e.get('calculation','')}")