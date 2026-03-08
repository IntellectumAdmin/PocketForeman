# -*- coding: utf-8 -*-
"""
АВТОМАТИЧЕСКИЙ извлекатель структуры ГПР из смет
INTELLECTUM - никакой ручной работы!
"""

import re
from typing import List, Tuple, Set
from pathlib import Path

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


# Технический мусор (удаляем)
BLACKLIST = [
    'ЕСН РСНБ РК', 'ЕСЦ РСН', 'ВСЕГО ПО СМЕТЕ',
    'в том числе', 'машины и механизмы', 'материалы',
    'затраты на труд', 'нормативная трудоемкость',
]


def parse_smeta_structure(pdf_path: str) -> List[Tuple[int, str]]:
    """
    АВТОМАТИЧЕСКИ извлекает структуру ГПР
    """
    if not HAS_PDF:
        raise ImportError("Установи pdfplumber")
    
    raw_sections = []
    seen: Set[str] = set()
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            
            for table in tables:
                if not table:
                    continue
                
                for row in table:
                    if not row:
                        continue
                    
                    for cell in row:
                        cell_text = str(cell or '').strip()
                        
                        if is_section_header(cell_text):
                            clean_name = clean_section_name(cell_text)
                            
                            if clean_name and clean_name not in seen:
                                raw_sections.append(clean_name)
                                seen.add(clean_name)
    
    # НОВОЕ: группируем подпозиции (ФП-1, ФП-2 → Фундамент плита)
    grouped = group_subsections(raw_sections)
    
    # Постобработка: иерархия
    structure = build_hierarchy(grouped)
    
    return structure


def group_subsections(sections: List[str]) -> List[str]:
    """
    Группирует подпозиции в общие разделы
    
    Пример:
    - Фундамент плита ФП-1
    - Фундамент плита ФП-2
    → Фундамент плита
    """
    grouped = []
    seen_parents = set()
    
    for section in sections:
        # Проверяем, есть ли код позиции в конце (ФП-1, В1, К3)
        match = re.search(r'^(.+?)\s+[А-ЯЁ]{1,4}-?\d+$', section)
        
        if match:
            # Это подпозиция → берём родителя
            parent = match.group(1).strip()
            if parent not in seen_parents:
                grouped.append(parent)
                seen_parents.add(parent)
        else:
            # Обычный раздел
            if section not in seen_parents:
                grouped.append(section)
                seen_parents.add(section)
    
    return grouped

def is_section_header(text: str) -> bool:
    """
    СТРОГИЙ фильтр разделов
    """
    if not text or len(text) < 5:
        return False
    
    if len(text) > 60:
        return False
    
    # Технический мусор
    blacklist_phrases = [
        'Затраты труда', 'средний разряд', 'ГОСТ', 'ЕСН РСНБ',
        'марки', 'диаметром', 'толщиной', 'мощность', 'Электрод',
        '=КОЛОННА', '=ПЛИТА', '=ЛЕСТНИЦА', '/лист', 'лист',
        'E11-', 'C1222-', 'Уб105-', 'F(49)', 'г.т*', 'т*',
        'SKC-105', 'object-cipher', 'construction=',
        # НОВОЕ: оборудование
        'плиткорез', 'точило', 'маятник', 'магнит разборный',
        'подставк', 'изделия',
    ]
    
    if any(bp.lower() in text.lower() for bp in blacklist_phrases):
        return False
    
    # Игнорируем коды работ
    if re.search(r'\d{4}-\d{4}-\d{4}', text):
        return False
    
    if re.search(r'\d{3,}', text):
        return False
    
    if '(' in text and len(text.split('(')[1]) > 30:
        return False
    
    # БЕЛЫЙ СПИСОК
    good_sections = [
        'Земляные работы', 'Конструкции железобетонные',
        'Архитектурная часть', 'Водопровод', 'Канализация',
        'Отопление', 'Вентиляция', 'Электроосвещение',
        'Электроэнергия', 'Благоустройство', 'Наружные сети',
        'Фундамент', 'Кровля', 'Фасады', 'Котельная',
        'Тепломеханическая часть', 'Строительная часть',
    ]
    
    # Проверяем вхождение (без учёта префикса "Р")
    clean_text = text.lstrip('РП ')
    if clean_text in good_sections:
        return True
    
    # Ключевые слова
    keywords = [
        'работы', 'Конструкции', 'часть', 'Водопровод',
        'Канализация', 'Отопление', 'Вентиляция',
        'Электро', 'Благоустройство', 'сети', 'Котельная',
        'Здание', 'Наружные', 'Фундамент', 'Кровля',
    ]
    
    has_keyword = any(kw in text for kw in keywords)
    return has_keyword

def clean_section_name(text: str) -> str:
    """
    ФИНАЛЬНАЯ очистка: убираем ВСЕ префиксы
    """
    # Убираем "Раздел X."
    text = re.sub(r'Раздел\s+\d+\.\s*', '', text)
    
    # Убираем префиксы П, П2, П3, Р, ПР (БЕЗ пробела после)
    text = re.sub(r'^П\d*', '', text)  # П2Земляные → Земляные
    text = re.sub(r'^Р', '', text)     # РКанализация → Канализация
    text = re.sub(r'^ПР', '', text)
    
    # Убираем коды в конце
    text = re.sub(r'\s+[А-Я]{2,4}\s+\d+$', '', text)
    text = re.sub(r'\s+\d{5,}$', '', text)
    
    # Убираем звёздочки
    text = text.replace('*', '')
    
    # Убираем скобки с кодами
    text = re.sub(r'\s*\([^\)]{3,10}\)\s*', ' ', text)
    
    # Убираем "шт"
    text = re.sub(r',?\s*\d+шт$', '', text)
    
    # Убираем лишние пробелы
    text = ' '.join(text.split())
    
    return text.strip()


def build_hierarchy(sections: List[str]) -> List[Tuple[int, str]]:
    """
    Определяет иерархию разделов (уровни вложенности)
    """
    hierarchy = []
    
    for section in sections:
        level = detect_level(section)
        hierarchy.append((level, section))
    
    return hierarchy


def detect_level(text: str) -> int:
    """
    Определяет уровень вложенности (0 = корень, 1 = раздел, 2 = подраздел)
    """
    # Уровень 0 - главные объекты
    level0 = ['Здание школы', 'Котельная', 'Наружные сети', 'Благоустройство']
    if any(kw in text for kw in level0):
        return 0
    
    # Уровень 1 - основные разделы работ
    level1 = [
        'Земляные работы', 'Конструкции железобетонные',
        'Конструкции металлические', 'Архитектурная часть',
        'Водопровод', 'Канализация', 'Отопление', 'Вентиляция',
        'Электроосвещение', 'Силовое электрооборудование',
        'Тепломеханические', 'Фундамент', 'Электроснабжение',
        'Наружное освещение', 'Тепловые сети', 'Вертикальная планировка',
    ]
    
    for kw in level1:
        if kw in text:
            return 1
    
    # Уровень 2 - подразделы
    return 2


def save_structure_txt(structure: List[Tuple[int, str]], output_path: str):
    """
    Сохраняет в формат structure.txt
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        for level, name in structure:
            indent = '  ' * level
            f.write(f"{indent}{name}/\n")
    
    print(f"✅ Файл сохранён: {output_path}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Использование: python structure_extractor.py <смета.pdf>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_path = "structure_auto.txt"
    
    print(f"📄 Автоматическое извлечение структуры из: {pdf_path}")
    print()
    
    structure = parse_smeta_structure(pdf_path)
    
    print(f"✅ Найдено разделов: {len(structure)}")
    print()
    
    # Показываем результат
    for level, name in structure:
        indent = '  ' * level
        print(f"{indent}{name}")
    
    print()
    save_structure_txt(structure, output_path)
    print()
    print("🎯 Готово! Структура извлечена АВТОМАТИЧЕСКИ.")