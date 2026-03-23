#!/usr/bin/env python3
"""
STRUCTURAL SMETA PARSER v1.0 — AINTELLECTUM
Архитектура: Аян | Разработка: Claude | Капитан: Ереке

Принцип: объёмы извлекаются из таблицы алгоритмически, без AI.
AI используется ТОЛЬКО для классификации работ (в следующих модулях).

Структура казахстанской сметы (7 колонок):
  [0] num   — Номер по порядку
  [1] code  — Шифр позиции норматива
  [2] name  — Наименование работ и затрат
  [3] unit  — Единица измерения
  [4] qty   — Количество (ОБЪЁМ)
  [5] price — Стоимость единицы (игнорируем)
  [6] total — Общая стоимость   (игнорируем)

Типы строк:
  WORK_ITEM  : num = целое число + есть unit + есть qty → ИЗВЛЕКАЕМ
  SUB_CAT    : num = "N.M"     (затраты на труд, машины...)  → пропуск
  SUB_ITEM   : num = "N.M.K"  (ресурсы: чел.-ч, маш.-ч...) → пропуск
  HEADER     : num = "1", col2 = "3"                          → пропуск
  SERVICE    : "из них:", "в том числе...", итоговые строки   → пропуск
  ANNOTATION : текст в num без unit/qty (комментарии)         → контекст
"""

import pdfplumber
import re
import json
import sys
import os
from pathlib import Path
from datetime import datetime


# ─── КОНФИГ ──────────────────────────────────────────────────────────────────

# Строки-сервисы которые всегда пропускаем
SERVICE_NAMES = {
    "из них:", "в том числе оплата труда рабочих",
    "в том числе оплата труда машинистов",
    "в т.ч. затраты труда машинистов, экипаж 1 чел.",
    "в т.ч. затраты труда машинистов, экипаж 2 чел.",
    "затраты на труд рабочих", "машины и механизмы",
    "материалы, изделия и конструкции",
    "нормативная трудоемкость", "сметная трудоемкость",
    "оплата труда рабочих", "затраты труда рабочих",
}

# Ключевые слова суммарных строк (пропускаем)
TOTAL_KEYWORDS = [
    "ВСЕГО ПО СМЕТЕ", "ИТОГО ПО", "Итого по", "всего по смете",
    "из них:", "оплата труда", "эксплуатация машин",
]

# Единицы измерения ресурсов (пропускаем строки с такими единицами у субпозиций)
RESOURCE_UNITS = {"чел.-ч", "маш.-ч", "маш-ч", "чел-ч"}

# Паттерны для определения раздела
SECTION_PATTERNS = [
    r"Раздел\s+\d+",
    r"РАЗДЕЛ\s+\d+",
    r"Глава\s+\d+",
    r"^[А-ЯЁ][А-ЯЁ\s]+$",  # Полностью заглавные буквы
]


# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────────────────────

def clean(val) -> str:
    """Очистка значения ячейки."""
    if val is None:
        return ""
    return str(val).strip().replace("\n", " ").replace("\r", "")


def parse_number(val: str) -> float | None:
    """Парсим число: '18 000' → 18000.0, '1 981,35' → 1981.35"""
    if not val:
        return None
    # Убираем пробелы (разделитель тысяч в казахстанском формате)
    s = val.replace(" ", "").replace("\xa0", "")
    # Казахстанский формат: запятая как десятичный разделитель
    s = s.replace(",", ".")
    try:
        result = float(s)
        return result if result > 0 else None
    except ValueError:
        return None


def is_header_row(row: list) -> bool:
    """Строка с номерами колонок (1, 2, 3, 4, 5, 6, 7) или заголовком."""
    c0 = clean(row[0]) if len(row) > 0 else ""
    c2 = clean(row[2]) if len(row) > 2 else ""
    c3 = clean(row[3]) if len(row) > 3 else ""

    # "Номер\nпо\nпорядку" в col0
    if "порядку" in c0 or "Номер" in c0:
        return True
    # Строка с номерами колонок: col0="1", col2="3", col3="4"
    if c0 == "1" and c2 == "3" and c3 in ("4", ""):
        return True
    return False


def is_service_row(name: str) -> bool:
    """Сервисная строка которую пропускаем."""
    name_lower = name.lower().strip()
    for svc in SERVICE_NAMES:
        if name_lower == svc.lower():
            return True
    for kw in TOTAL_KEYWORDS:
        if kw.lower() in name_lower:
            return True
    return False


def classify_num(num: str) -> str:
    """
    Классифицируем значение col0:
      'WORK'       — целое число (главная работа)
      'SUBCAT'     — N.M (подкатегория)
      'SUBITEM'    — N.M.K (ресурс)
      'ANNOTATION' — текст (комментарий/раздел)
      'EMPTY'      — пустая строка
    """
    if not num:
        return "EMPTY"
    # Целое число
    if re.match(r'^\d+$', num):
        return "WORK"
    # N.M (одна точка)
    if re.match(r'^\d+\.\d+$', num):
        return "SUBCAT"
    # N.M.K или глубже (две+ точки)
    if re.match(r'^\d+\.\d+\.\d+', num):
        return "SUBITEM"
    return "ANNOTATION"


def detect_section_from_text(text: str) -> str | None:
    """Определяем является ли текст заголовком раздела."""
    text = text.strip()
    if not text:
        return None
    # Явные паттерны разделов
    for pattern in SECTION_PATTERNS:
        if re.search(pattern, text):
            return text
    # Короткий текст без цифр — возможно раздел
    if len(text) > 3 and len(text) < 80 and not any(c.isdigit() for c in text):
        # Начинается с заглавной буквы, нет спецсимволов
        if text[0].isupper():
            return text
    return None


def extract_smeta_name_from_page(page) -> str | None:
    """Ищем название сметы на странице (обычно в заголовке)."""
    text = page.extract_text() or ""
    # Ищем строки с "Раздел N."
    for line in text.split('\n'):
        line = line.strip()
        if re.search(r'Раздел\s+\d+', line, re.IGNORECASE):
            return line[:100]
    return None


# ─── ОСНОВНОЙ ПАРСЕР ─────────────────────────────────────────────────────────

def parse_smeta(pdf_path: str, verbose: bool = True) -> dict:
    """
    Основная функция парсинга.
    Возвращает словарь с work_items и метаданными.
    """
    if verbose:
        print("=" * 65)
        print("STRUCTURAL SMETA PARSER v1.0 — AINTELLECTUM")
        print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
        print("=" * 65)
        print(f"\nФайл: {Path(pdf_path).name}")

    work_items = []
    skipped = {"header": 0, "service": 0, "subcat": 0, "subitem": 0, "no_qty": 0}
    errors = []

    current_smeta = None       # Название текущей сметы
    current_section = None     # Текущий раздел
    current_annotation = None  # Последняя аннотация (Фундамент Фп-1 и т.п.)
    smeta_count = 0

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if verbose:
            print(f"Страниц в PDF: {total_pages}")
            print("\nОбработка...", end="", flush=True)

        for page_idx, page in enumerate(pdf.pages):
            if verbose and page_idx % 100 == 0 and page_idx > 0:
                print(f" {page_idx}", end="", flush=True)

            # Ищем название сметы на каждой странице
            smeta_name = extract_smeta_name_from_page(page)
            if smeta_name:
                current_smeta = smeta_name
                current_section = smeta_name
                smeta_count += 1

            # Извлекаем таблицы
            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                for row in table:
                    # Нормализуем длину строки до 7 ячеек
                    while len(row) < 7:
                        row.append(None)

                    # Пропускаем строку заголовка
                    if is_header_row(row):
                        skipped["header"] += 1
                        continue

                    col0 = clean(row[0])
                    col1 = clean(row[1])
                    col2 = clean(row[2])
                    col3 = clean(row[3])
                    col4 = clean(row[4])

                    # Пропускаем пустые строки
                    if not col0 and not col2:
                        continue

                    # Пропускаем сервисные строки по имени
                    if is_service_row(col2):
                        skipped["service"] += 1
                        continue

                    # Классифицируем строку по col0
                    row_type = classify_num(col0)

                    if row_type == "SUBCAT":
                        skipped["subcat"] += 1
                        continue

                    if row_type == "SUBITEM":
                        skipped["subitem"] += 1
                        continue

                    if row_type == "ANNOTATION":
                        # Обновляем контекст раздела если это раздел
                        section_hint = detect_section_from_text(col0)
                        if section_hint:
                            current_section = section_hint
                        else:
                            # Иначе это просто аннотация/комментарий
                            current_annotation = col0 if col0 else col2
                        continue

                    if row_type == "EMPTY":
                        # Проверяем col2 на аннотацию раздела
                        if col2:
                            section_hint = detect_section_from_text(col2)
                            if section_hint:
                                current_section = section_hint
                        continue

                    # row_type == "WORK" — главная работа
                    # Проверяем наличие единицы и количества
                    if not col3:
                        skipped["no_qty"] += 1
                        continue
                    if not col4:
                        skipped["no_qty"] += 1
                        continue

                    # Парсим объём
                    volume = parse_number(col4)
                    if volume is None:
                        skipped["no_qty"] += 1
                        errors.append({
                            "page": page_idx + 1,
                            "num": col0,
                            "name": col2[:60],
                            "raw_qty": col4,
                            "issue": "cant_parse_number"
                        })
                        continue

                    # Дополнительная фильтрация: пропускаем ресурсы
                    # (чел.-ч и маш.-ч иногда могут иметь целый номер)
                    if col3.strip() in RESOURCE_UNITS:
                        skipped["subitem"] += 1
                        continue

                    # ✅ Это основная работа — сохраняем
                    work_item = {
                        "num": col0,
                        "code": col1 if col1 else None,
                        "name": col2,
                        "unit": col3,
                        "volume": volume,
                        "raw_volume": col4,
                        "section": current_section,
                        "annotation": current_annotation,
                        "smeta": current_smeta,
                        "page": page_idx + 1,
                    }
                    work_items.append(work_item)

    if verbose:
        print(f" готово!\n")

    # ─── СТАТИСТИКА ───────────────────────────────────────────────────────────
    units_count = {}
    for item in work_items:
        u = item["unit"]
        units_count[u] = units_count.get(u, 0) + 1

    sections_count = {}
    for item in work_items:
        s = item["section"] or "Без раздела"
        sections_count[s] = sections_count.get(s, 0) + 1

    result = {
        "meta": {
            "parser": "structural_smeta_parser_v1.0",
            "source_file": Path(pdf_path).name,
            "parsed_at": datetime.now().isoformat(),
            "total_pages": total_pages,
            "smeta_sections_found": smeta_count,
            "work_items_extracted": len(work_items),
            "skipped": skipped,
            "errors_count": len(errors),
        },
        "units_distribution": dict(sorted(units_count.items(), key=lambda x: -x[1])[:20]),
        "sections_distribution": dict(sorted(sections_count.items(), key=lambda x: -x[1])[:30]),
        "work_items": work_items,
        "parse_errors": errors[:50],  # Первые 50 ошибок
    }

    if verbose:
        print("=" * 65)
        print("РЕЗУЛЬТАТ ПАРСИНГА")
        print("=" * 65)
        print(f"  Извлечено работ:    {len(work_items):,}")
        print(f"  Пропущено заголовков: {skipped['header']:,}")
        print(f"  Пропущено сервисных:  {skipped['service']:,}")
        print(f"  Пропущено подкатегорий: {skipped['subcat']:,}")
        print(f"  Пропущено ресурсов:   {skipped['subitem']:,}")
        print(f"  Без объёма:           {skipped['no_qty']:,}")
        print(f"  Ошибок парсинга:      {len(errors):,}")
        print(f"\n  Разделов найдено: {smeta_count}")
        print(f"\nРаспределение единиц измерения (топ-10):")
        for unit, cnt in list(result["units_distribution"].items())[:10]:
            print(f"    {unit:<20} {cnt:>5} работ")
        print(f"\nРазделы (топ-10):")
        for sec, cnt in list(result["sections_distribution"].items())[:10]:
            print(f"    {str(sec)[:50]:<52} {cnt:>4} работ")
        print()

        # Примеры работ
        print("Примеры извлечённых работ:")
        for item in work_items[:5]:
            print(f"  [{item['num']}] {item['name'][:55]}")
            print(f"       unit={item['unit']} | vol={item['volume']} | section={str(item['section'])[:40]}")

    return result


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Путь к PDF
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        # Ищем PDF автоматически
        candidates = [
            "analytics/data/8._локальные.pdf",
            "8._локальные.pdf",
            "8. локальные.pdf",
        ]
        pdf_path = None
        for c in candidates:
            if Path(c).exists():
                pdf_path = c
                break
        if not pdf_path:
            # Ищем любой PDF
            pdfs = list(Path(".").glob("**/*.pdf"))
            if pdfs:
                pdf_path = str(pdfs[0])
            else:
                print("ERROR: PDF файл не найден. Укажите путь: python structural_smeta_parser.py <путь.pdf>")
                sys.exit(1)

    # Парсим
    result = parse_smeta(pdf_path, verbose=True)

    # Сохраняем JSON
    out_path = "structural_smeta.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Сохранено: {out_path}")
    print(f"   Размер: {Path(out_path).stat().st_size / 1024:.1f} КБ")
    print(f"\n🚀 AINTELLECTUM: PDF → Структурный парсер → точные объёмы ✅")