# Анализируем реальные коды из сметы
import json

data = json.load(open('smeta_works_v2.json', encoding='utf-8'))
works = data['work_items']

# Собираем все уникальные префиксы кодов
prefixes = {}
for w in works:
    code = w['code']
    p4 = code[:4]   # первые 4 цифры: 6101
    p8 = code[:9]   # первые 9 цифр: 6101-0101
    
    if p4 not in prefixes:
        prefixes[p4] = {'count': 0, 'sub': {}, 'examples': []}
    prefixes[p4]['count'] += 1
    
    if p8 not in prefixes[p4]['sub']:
        prefixes[p4]['sub'][p8] = {'count': 0, 'names': []}
    prefixes[p4]['sub'][p8]['count'] += 1
    
    if len(prefixes[p4]['sub'][p8]['names']) < 2:
        prefixes[p4]['sub'][p8]['names'].append(w['name'][:60])
    
    if len(prefixes[p4]['examples']) < 2:
        prefixes[p4]['examples'].append(w['name'][:60])

# Выводим иерархию
for p4, info in sorted(prefixes.items()):
    print(f"\n{'='*60}")
    print(f"[{info['count']}] {p4}-xxxx-xxxx")
    for ex in info['examples']:
        print(f"  Пример: {ex}")
    print(f"  Подразделы ({len(info['sub'])}):")
    for p8, sub in sorted(info['sub'].items()):
        print(f"    [{sub['count']:>4}] {p8}-xxxx")
        for name in sub['names'][:1]:
            print(f"           {name}")