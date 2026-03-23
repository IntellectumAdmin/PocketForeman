# -*- coding: utf-8 -*-
"""
SMETA CORE PARSER v4.0 — AINTELLECTUM
Архитектура: Аян | Разработка: Claude | Капитан: Ереке

ЭВОЛЮЦИЯ v3.0 → v4.0:
  Один проход по PDF → три датасета:
    smeta_works_raw.json       (6xxx — работы)
    smeta_materials_raw.json   (2xxx — материалы)
    smeta_equipment_raw.json   (3xxx — оборудование)
    smeta_parse_report.json    (отчёт)

  Каждая строка сохраняет контекст:
    row_type, page, source_table_index, row_index_in_table
  Это позволит потом связать: работа ↔ материал ↔ оборудование

  Обратная совместимость:
    smeta_works_v2.json — по-прежнему создаётся (для старого pipeline)
"""

import pdfplumber
import json
import re
import sys
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# КЛАССИФИКАТОР ВИДОВ РАБОТ ПО КОДУ ЕСЦ РСНБ РК (из v3.0)
# ═══════════════════════════════════════════════════════════════

WORK_CLASSIFIER = {
    '6101': {'phase': 'Земляные работы',                  'phase_order': 1,  'sub': {'6101-0101': 'Разработка грунта экскаватором (котлованы)', '6101-0102': 'Разработка грунта экскаватором (траншеи)', '6101-0106': 'Засыпка траншей и котлованов', '6101-0107': 'Уплотнение грунта', '6101-0104': 'Разработка грунта бульдозерами', '6101-0201': 'Разработка грунта вручную (траншеи)', '6101-0205': 'Копание ям вручную',}},
    '6103': {'phase': 'Монолитный каркас',                'phase_order': 3,  'sub': {'6103-0101': 'Фундаментные плиты', '6103-0201': 'Опалубка и бетонирование колонн', '6103-0301': 'Опалубка и бетонирование стен', '6103-0401': 'Опалубка и бетонирование балок', '6103-0501': 'Опалубка и бетонирование перекрытий', '6103-0601': 'Лестничные площадки и марши', '6103-0701': 'Бетонная подготовка',}},
    '6104': {'phase': 'Каменные работы',                  'phase_order': 4,  'sub': {}},
    '6105': {'phase': 'Металлические конструкции',        'phase_order': 5,  'sub': {}},
    '6106': {'phase': 'Деревянные конструкции',           'phase_order': 6,  'sub': {}},
    '6107': {'phase': 'Кровля',                           'phase_order': 7,  'sub': {}},
    '6108': {'phase': 'Окна и двери',                     'phase_order': 8,  'sub': {'6108-0102': 'Установка блоков оконных из ПВХ профилей', '6108-0204': 'Установка блока дверного металлического',}},
    '6109': {'phase': 'Полы',                             'phase_order': 9,  'sub': {'6109-0101': 'Уплотнение грунта щебнем', '6109-0201': 'Устройство стяжки цементной', '6109-0306': 'Устройство покрытий из плиток керамических', '6109-0308': 'Устройство покрытий из линолеума',}},
    '6110': {'phase': 'Кровля наружная',                  'phase_order': 10, 'sub': {}},
    '6111': {'phase': 'Гидро- и пароизоляция',            'phase_order': 11, 'sub': {}},
    '6112': {'phase': 'Отделочные работы',                'phase_order': 12, 'sub': {'6112-0202': 'Штукатурка поверхности внутри зданий', '6112-0302': 'Покраска', '6112-0401': 'Облицовка фасада металлосайдингом', '6112-0501': 'Облицовка потолка плитами из минерального волокна',}},
    '6113': {'phase': 'Благоустройство',                  'phase_order': 13, 'sub': {'6113-0112': 'Подготовка почвы для газона', '6113-0301': 'Устройство покрытия дорожек', '6113-0401': 'Устройство спортивных покрытий',}},
    '6114': {'phase': 'Водоснабжение и канализация',      'phase_order': 14, 'sub': {}},
    '6115': {'phase': 'Сантехника (санузлы)',              'phase_order': 15, 'sub': {}},
    '6116': {'phase': 'Отопление и теплоснабжение',       'phase_order': 16, 'sub': {}},
    '6118': {'phase': 'Вентиляция и кондиционирование',   'phase_order': 17, 'sub': {}},
    '6119': {'phase': 'Электроснабжение',                 'phase_order': 18, 'sub': {}},
    '6120': {'phase': 'Лифтовое оборудование',            'phase_order': 19, 'sub': {}},
    '6121': {'phase': 'Наружные сети водоснабжения',      'phase_order': 20, 'sub': {}},
    '6122': {'phase': 'Наружная канализация',             'phase_order': 21, 'sub': {}},
    '6123': {'phase': 'Слаботочные системы',              'phase_order': 22, 'sub': {}},
    '6124': {'phase': 'Электроснабжение',                 'phase_order': 18, 'sub': {}},
    '6125': {'phase': 'Слаботочные системы',              'phase_order': 22, 'sub': {}},
}

# ═══════════════════════════════════════════════════════════════
# КЛАССИФИКАТОР МАТЕРИАЛОВ ПО КОДУ 2xxx
# ═══════════════════════════════════════════════════════════════

MATERIAL_CLASSIFIER = {
    '21': 'Строительные материалы',
    '22': 'Отделочные материалы',
    '23': 'Изоляционные материалы',
    '24': 'Трубы и арматура',
    '25': 'Электротехнические материалы',
    '26': 'Сантехническое оборудование',
    '27': 'Прочие материалы',
    '28': 'Кровельные материалы',
    '29': 'Специальные материалы',
}

# ═══════════════════════════════════════════════════════════════
# КЛАССИФИКАТОР ОБОРУДОВАНИЯ ПО КОДУ 3xxx
# ═══════════════════════════════════════════════════════════════

EQUIPMENT_CLASSIFIER = {
    '31': 'Технологическое оборудование',
    '32': 'Электрооборудование',
    '33': 'Сантехническое оборудование',
    '34': 'Вентиляционное оборудование',
    '35': 'Прочее оборудование',
}


# ═══════════════════════════════════════════════════════════════
# ПАТТЕРНЫ КОДОВ
# ═══════════════════════════════════════════════════════════════

RE_WORK     = re.compile(r'^6\d{3}-\d{4}-\d{4}')
RE_MATERIAL = re.compile(r'^2\d{2,3}-\d{3,4}-\d{4}')
RE_EQUIP    = re.compile(r'^3\d{2,3}-')
RE_ANY_CODE = re.compile(r'^[236]\d{2,3}-\d{3,4}')


def classify_row_type(code: str) -> str:
    """Определяет тип строки по первой цифре кода."""
    if not code:
        return 'noise'
    if code.startswith('6'):
        return 'work'
    if code.startswith('2'):
        return 'material'
    if code.startswith('3'):
        return 'equipment'
    return 'noise'


def classify_work(code: str) -> dict:
    p4 = code[:4]
    p9 = code[:9]
    info = WORK_CLASSIFIER.get(p4, {})
    return {
        'phase':       info.get('phase', f'Прочие ({p4})'),
        'phase_order': info.get('phase_order', 99),
        'subgroup':    info.get('sub', {}).get(p9, ''),
    }


def classify_material(code: str) -> dict:
    prefix = code[1:3] if len(code) >= 3 else ''
    return {
        'material_type': MATERIAL_CLASSIFIER.get(prefix, 'Прочие материалы'),
        'material_group': prefix,
    }


def classify_equipment(code: str) -> dict:
    prefix = code[1:3] if len(code) >= 3 else ''
    return {
        'equipment_type': EQUIPMENT_CLASSIFIER.get(prefix, 'Прочее оборудование'),
        'equipment_group': prefix,
    }


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (из v3.0)
# ═══════════════════════════════════════════════════════════════

def extract_code(cell: str) -> str:
    m = re.match(r'^(\d{4}-\d{4}-\d{4}|\d{3}-\d{3}-\d{4}|\d{4}-\d{4}|\d{3}-\d{4})', (cell or '').strip())
    return m.group(1) if m else ''


def parse_volume(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ('-', '—', '–', 'x', 'х', 'X'):
        return None
    s = re.sub(r'(\d)\s+(\d)', r'\1\2', s)
    s = s.replace(',', '.')
    s = re.sub(r'[^\d.]', '', s)
    if not s:
        return None
    try:
        val = float(s)
        return val if val > 0 else None
    except ValueError:
        return None


UNIT_MAP = {
    'м2': 'м2', 'м²': 'м2', 'кв.м': 'м2', 'кв.м.': 'м2', 'm2': 'м2',
    'м3': 'м3', 'м³': 'м3', 'куб.м': 'м3', 'куб.м.': 'м3', 'm3': 'м3',
    'м': 'м', 'п.м': 'м', 'пог.м': 'м', 'п.м.': 'м',
    'т': 'т', 'тн': 'т', 'тонн': 'т',
    'кг': 'кг', 'шт': 'шт', 'шт.': 'шт', 'штук': 'шт',
    'компл': 'компл', 'компл.': 'компл', 'комплект': 'компл',
    'яма': 'яма', 'набор': 'набор', 'чел-час': 'чел-час',
}

def normalize_unit(unit: str) -> tuple:
    u = (unit or '').strip().lower()
    if u in ('км', 'km'):
        return 'м', 1000.0
    u_first = u.split()[0] if u else u
    return UNIT_MAP.get(u_first, UNIT_MAP.get(u, u)), 1.0


def find_code_column(table: list) -> int | None:
    for row in table[:30]:
        if not row:
            continue
        for j, cell in enumerate(row):
            code = extract_code(str(cell or ''))
            if RE_ANY_CODE.match(code):
                return j
    return None


# ═══════════════════════════════════════════════════════════════
# ОСНОВНОЙ КЛАСС ПАРСЕРА
# ═══════════════════════════════════════════════════════════════

class SmetaCoreParser:

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.works      = []   # 6xxx
        self.materials  = []   # 2xxx
        self.equipment  = []   # 3xxx
        self.skipped = {'noise': 0, 'no_volume': 0, 'parse_error': 0}
        self.parse_errors = []

    def run(self) -> dict:
        pdf_path = Path(self.pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"Файл не найден: {self.pdf_path}")

        print("=" * 65)
        print("SMETA CORE PARSER v4.0 — AINTELLECTUM")
        print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
        print("Один проход → works + materials + equipment")
        print("=" * 65)
        print(f"\nФайл: {pdf_path.name}")

        with pdfplumber.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"Страниц: {total_pages}")
            print(f"Обработка...", end='', flush=True)
            for page_num, page in enumerate(pdf.pages, 1):
                if page_num % 100 == 0:
                    print(f" {page_num}", end='', flush=True)
                self._process_page(page, page_num)
            print(f" {total_pages} готово!")

        return self._build_result()

    def _process_page(self, page, page_num: int):
        try:
            tables = page.extract_tables()
            if not tables:
                return
            for table_idx, table in enumerate(tables):
                self._process_table(table, page_num, table_idx)
        except Exception as e:
            self.skipped['parse_error'] += 1
            self.parse_errors.append({'page': page_num, 'error': str(e)})

    def _process_table(self, table: list, page_num: int, table_idx: int):
        if not table:
            return
        code_col = find_code_column(table)

        for row_idx, row in enumerate(table):
            if not row:
                continue

            def c(offset=0) -> str:
                if code_col is None:
                    return ''
                idx = code_col + offset
                return str(row[idx] or '').strip() if idx < len(row) else ''

            if code_col is not None:
                raw_code = c(0)
                name     = c(1)
                unit_raw = c(2)
                qty_raw  = c(3)
            else:
                raw_code, name, unit_raw, qty_raw = self._scan_row(row)

            code = extract_code(raw_code)
            if not code:
                self.skipped['noise'] += 1
                continue

            row_type = classify_row_type(code)
            if row_type == 'noise':
                self.skipped['noise'] += 1
                continue

            unit_norm, coeff = normalize_unit(unit_raw)
            volume = parse_volume(qty_raw)
            if volume is not None and coeff != 1.0:
                volume *= coeff

            # Базовый контекст — одинаковый для всех типов (по совету Аяна)
            base = {
                'code':               code,
                'name':               (name or '')[:120],
                'unit':               unit_norm,
                'volume':             volume or 0.0,
                'has_volume':         volume is not None,
                'page':               page_num,
                'row_type':           row_type,
                'source_table_index': table_idx,
                'row_index_in_table': row_idx,
            }

            if row_type == 'work':
                cl = classify_work(code)
                base.update({
                    'phase':       cl['phase'],
                    'phase_order': cl['phase_order'],
                    'subgroup':    cl['subgroup'],
                })
                self.works.append(base)

            elif row_type == 'material':
                cl = classify_material(code)
                base.update({
                    'material_type':  cl['material_type'],
                    'material_group': cl['material_group'],
                })
                self.materials.append(base)

            elif row_type == 'equipment':
                cl = classify_equipment(code)
                base.update({
                    'equipment_type':  cl['equipment_type'],
                    'equipment_group': cl['equipment_group'],
                })
                self.equipment.append(base)

    def _scan_row(self, row: list) -> tuple:
        for i, cell in enumerate(row):
            code = extract_code(str(cell or ''))
            if RE_ANY_CODE.match(code):
                g = lambda o: str(row[i+o] or '').strip() if i+o < len(row) else ''
                return str(cell or '').strip(), g(1), g(2), g(3)
        return '', '', '', ''

    def _build_result(self) -> dict:
        phases = {}
        for w in self.works:
            p = w['phase']
            if p not in phases:
                phases[p] = {'count': 0, 'order': w['phase_order']}
            phases[p]['count'] += 1
        phases_sorted = dict(sorted(phases.items(), key=lambda x: x[1]['order']))

        mat_types = {}
        for m in self.materials:
            t = m['material_type']
            mat_types[t] = mat_types.get(t, 0) + 1

        return {
            'meta': {
                'parser_version':    '4.0',
                'source':            str(self.pdf_path),
                'total_works':       len(self.works),
                'total_materials':   len(self.materials),
                'total_equipment':   len(self.equipment),
                'skipped':           self.skipped,
                'phases_count':      len(phases),
            },
            'works_summary':     {k: v['count'] for k, v in phases_sorted.items()},
            'materials_summary': mat_types,
            'equipment_count':   len(self.equipment),
            'parse_errors':      self.parse_errors,
        }

    def print_summary(self, result: dict):
        meta = result['meta']
        print("\n" + "=" * 65)
        print("SMETA CORE PARSER v4.0 — РЕЗУЛЬТАТ")
        print("=" * 65)
        print(f"\n  Работ (6xxx):        {meta['total_works']:>6}")
        print(f"  Материалов (2xxx):   {meta['total_materials']:>6}")
        print(f"  Оборудование (3xxx): {meta['total_equipment']:>6}")
        print(f"  Шум/итоги:           {self.skipped['noise']:>6}")
        print(f"  Ошибки парсинга:     {self.skipped['parse_error']:>6}")
        print(f"\n  Фаз ГПР: {meta['phases_count']}")
        print(f"\nФАЗЫ (работы):")
        for phase, cnt in result['works_summary'].items():
            print(f"  {cnt:>5} | {phase}")
        if result['materials_summary']:
            print(f"\nТИПЫ МАТЕРИАЛОВ:")
            for mat_type, cnt in sorted(
                    result['materials_summary'].items(), key=lambda x: -x[1]):
                print(f"  {cnt:>5} | {mat_type}")


# ═══════════════════════════════════════════════════════════════
# СОХРАНЕНИЕ ФАЙЛОВ
# ═══════════════════════════════════════════════════════════════

def save_outputs(parser: SmetaCoreParser, result: dict):
    outputs = []

    # 1. smeta_works_raw.json — работы (6xxx)
    works_data = {
        'meta':         result['meta'],
        'work_items':   parser.works,
        'phases_summary': result['works_summary'],
        'parse_errors': result['parse_errors'],
    }
    _save_json(works_data, 'smeta_works_raw.json')
    outputs.append('smeta_works_raw.json')

    # 2. smeta_works_v2.json — обратная совместимость со старым pipeline
    _save_json(works_data, 'smeta_works_v2.json')
    outputs.append('smeta_works_v2.json  (обратная совместимость)')

    # 3. smeta_materials_raw.json — материалы (2xxx)
    _save_json({
        'meta':            result['meta'],
        'material_items':  parser.materials,
        'types_summary':   result['materials_summary'],
    }, 'smeta_materials_raw.json')
    outputs.append('smeta_materials_raw.json')

    # 4. smeta_equipment_raw.json — оборудование (3xxx)
    _save_json({
        'meta':             result['meta'],
        'equipment_items':  parser.equipment,
        'count':            len(parser.equipment),
    }, 'smeta_equipment_raw.json')
    outputs.append('smeta_equipment_raw.json')

    # 5. smeta_parse_report.json — полный отчёт
    _save_json({
        'meta':              result['meta'],
        'works_summary':     result['works_summary'],
        'materials_summary': result['materials_summary'],
        'equipment_count':   result['equipment_count'],
        'parse_errors':      result['parse_errors'],
    }, 'smeta_parse_report.json')
    outputs.append('smeta_parse_report.json')

    print(f"\nФайлы сохранены:")
    for o in outputs:
        p = o.split()[0]
        if Path(p).exists():
            size = Path(p).stat().st_size // 1024
            print(f"  OK {o}  ({size} КБ)")

    return outputs


def _save_json(data: dict, path: str):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Использование: python smeta_core_parser.py <путь.pdf>")
        sys.exit(1)

    parser = SmetaCoreParser(sys.argv[1])
    try:
        result = parser.run()
    except FileNotFoundError as e:
        print(f"\nОШИБКА: {e}")
        sys.exit(1)

    save_outputs(parser, result)
    parser.print_summary(result)
    print(f"\nAINTELLECTUM: PDF → works + materials + equipment ✅")


if __name__ == '__main__':
    main()