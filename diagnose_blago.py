"""Диагностика фазы Благоустройство — по совету Аяна"""
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "duration_estimates.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

items = [e for e in data.get("estimates", [])
         if "лагоустройств" in e.get("phase", "")]
items.sort(key=lambda x: -(x.get("duration_days") or 0))

print(f"Всего строк в Благоустройстве: {len(items)}")
print(f"Топ по длительности:\n")
print(f"{'Дней':>6}  {'Код':<22} {'Объём':>10} {'Ед':>5}  Название")
print("─" * 95)
for e in items[:20]:
    print(f"{e.get('duration_days',0):>6}  "
          f"{e.get('code',''):<22} "
          f"{str(e.get('volume','')):>10} "
          f"{str(e.get('unit','')):>5}  "
          f"{str(e.get('name',''))[:45]}")

print()
codes = sorted(set(e.get('code','')[:7] for e in items))
print(f"Группы кодов: {codes}")
print()

# Делим на критичное / некритичное
critical_keywords = ['покрыти', 'асфальт', 'тротуар', 'отмостк', 'проезд',
                     'входн', 'бордюр', 'плитк', 'дорожк', 'мощени']
non_critical_keywords = ['газон', 'дерев', 'кустарник', 'посадк', 'озелен',
                         'мaf', 'малая форм', 'урн', 'скамь', 'игровой',
                         'тартан', 'яма']

crit = []
non_crit = []
unclear = []

for e in items:
    name = e.get('name', '').lower()
    if any(k in name for k in non_critical_keywords):
        non_crit.append(e)
    elif any(k in name for k in critical_keywords):
        crit.append(e)
    else:
        unclear.append(e)

print(f"Обязательное (покрытия, проезды):  {len(crit)} строк")
print(f"Некритичное (газоны, озеленение):  {len(non_crit)} строк")
print(f"Неопределённое:                     {len(unclear)} строк")
print()
print("НЕОПРЕДЕЛЁННЫЕ (нужна ручная классификация):")
for e in unclear[:10]:
    print(f"  {e.get('code',''):<22} {str(e.get('duration_days',0)):>4} дн.  {e.get('name','')[:50]}")