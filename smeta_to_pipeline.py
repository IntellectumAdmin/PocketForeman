"""
SMETA TO PIPELINE CONVERTER v1.0 — AINTELLECTUM
Архитектура: Аян | Разработка: Claude | Капитан: Ереке

Конвертирует smeta_works_v2.json (выход парсера v3.0)
в форматы work_assignment.json + volume_summary.json
для duration_engine.py v6.2

ЦЕПОЧКА PIPELINE:
  smeta_parser_v2.py → smeta_works_v2.json
         ↓
  smeta_to_pipeline.py → work_assignment.json
                       → volume_summary.json
         ↓
  duration_engine.py → duration_estimates.json
                     → duration_summary.json
         ↓
  gpr_builder.py → gpr_schedule.json
         ↓
  gantt_exporter.py → gantt_chart.html
"""

import json
import sys
from pathlib import Path
from collections import defaultdict


def convert(input_path: str = "smeta_works_v2.json"):
    """
    Конвертирует smeta_works_v2.json в work_assignment.json и volume_summary.json
    """
    print("=" * 65)
    print("SMETA TO PIPELINE CONVERTER v1.0 — AINTELLECTUM")
    print("=" * 65)

    # ─── Загрузка ────────────────────────────────────────────
    path = Path(input_path)
    if not path.exists():
        print(f"ОШИБКА: файл не найден: {input_path}")
        sys.exit(1)

    data = json.load(open(path, encoding='utf-8'))
    works = data.get('work_items', [])
    print(f"\nЗагружено работ: {len(works)}")

    # ─── Группировка по фазе и подгруппе ────────────────────
    # Структура: phase → subgroup → {volumes: {unit: total}, count, items}
    phases: dict = {}

    for w in works:
        phase = w.get('phase', 'Прочие работы')
        phase_order = w.get('phase_order', 99)
        subgroup = w.get('subgroup', '') or w.get('name', '')[:60]
        unit = w.get('unit', '') or 'шт'
        volume = w.get('volume', 0.0) or 0.0
        has_vol = w.get('has_volume', False)

        if phase not in phases:
            phases[phase] = {
                'phase': phase,
                'phase_order': phase_order,
                'subsections': {}
            }

        subs = phases[phase]['subsections']
        if subgroup not in subs:
            subs[subgroup] = {
                'name': subgroup,
                'work_items_count': 0,
                'volumes': defaultdict(float),
                'items': []
            }

        sub = subs[subgroup]
        sub['work_items_count'] += 1
        if has_vol and volume > 0:
            sub['volumes'][unit] += volume
        sub['items'].append({
            'name': w.get('name', ''),
            'code': w.get('code', ''),
            'unit': unit,
            'volume': volume,
        })

    # ─── Сортируем фазы по порядку строительства ────────────
    sorted_phases = sorted(phases.values(), key=lambda x: x['phase_order'])

    # ─── Собираем work_assignment.json ──────────────────────
    work_assignment_phases = []
    for ph in sorted_phases:
        subsections = []
        for sub_name, sub_data in ph['subsections'].items():
            subsections.append({
                'name': sub_name,
                'work_items_count': sub_data['work_items_count'],
                'volumes': dict(sub_data['volumes']),
                'items': sub_data['items'][:5],  # первые 5 для примера
            })

        work_assignment_phases.append({
            'phase': ph['phase'],
            'phase_order': ph['phase_order'],
            'subsections': subsections,
        })

    work_assignment = {
        'project': path.stem,
        'version': '1.0',
        'source': str(path),
        'total_works': len(works),
        'phases_count': len(sorted_phases),
        'phases': work_assignment_phases,
    }

    # ─── Собираем volume_summary.json ───────────────────────
    phases_summary = []
    for ph in sorted_phases:
        subs_summary = []
        for sub_name, sub_data in ph['subsections'].items():
            # Основной объём — берём самую большую по значению единицу
            vols = dict(sub_data['volumes'])
            main_unit = max(vols, key=vols.get) if vols else None
            main_vol = vols[main_unit] if main_unit else 0

            subs_summary.append({
                'name': sub_name,
                'work_items_count': sub_data['work_items_count'],
                'main_unit': main_unit,
                'main_volume': round(main_vol, 3),
                'all_volumes': vols,
            })

        phases_summary.append({
            'phase': ph['phase'],
            'phase_order': ph['phase_order'],
            'subsections_count': len(ph['subsections']),
            'subsections': subs_summary,
        })

    volume_summary = {
        'project': path.stem,
        'version': '1.0',
        'source': str(path),
        'phases_count': len(sorted_phases),
        'phases_summary': phases_summary,
    }

    # ─── Сохраняем ──────────────────────────────────────────
    with open('work_assignment.json', 'w', encoding='utf-8') as f:
        json.dump(work_assignment, f, ensure_ascii=False, indent=2)
    wa_size = Path('work_assignment.json').stat().st_size / 1024

    with open('volume_summary.json', 'w', encoding='utf-8') as f:
        json.dump(volume_summary, f, ensure_ascii=False, indent=2)
    vs_size = Path('volume_summary.json').stat().st_size / 1024

    # ─── Статистика ─────────────────────────────────────────
    print(f"\nФАЗЫ ГПР ({len(sorted_phases)}):")
    total_subs = 0
    for ph in sorted_phases:
        n_subs = len(ph['subsections'])
        total_subs += n_subs
        print(f"  {ph['phase_order']:>2}. {ph['phase']:<40} {n_subs:>4} подгрупп")

    print(f"\nИтого подгрупп: {total_subs}")
    print(f"\nСохранено:")
    print(f"  work_assignment.json  — {wa_size:.1f} КБ")
    print(f"  volume_summary.json   — {vs_size:.1f} КБ")
    print(f"\nСледующий шаг:")
    print(f"  python duration_engine.py")
    print(f"\nAINTELLECTUM: smeta_works_v2.json -> Pipeline -> ГПР ✅")


if __name__ == '__main__':
    inp = sys.argv[1] if len(sys.argv) > 1 else 'smeta_works_v2.json'
    convert(inp)