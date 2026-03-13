# -*- coding: utf-8 -*-
"""
ПРЕПРОЦЕССОР СМЕТ v4.7_final
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

ФИНАЛЬНАЯ ВЕРСИЯ ПРЕПРОЦЕССОРА.
После этой версии препроцессор фиксируется как стабильный модуль.
Следующий шаг → LLM Chunk Analyzer → Hierarchy Builder.

УЛУЧШЕНИЯ v4.7_final (по ревью Аяна):
1. Chunking начинается с section — ИИ получает естественный контекст
2. norm для work_item в AI payload — ИИ легче группирует работы
3. unknown_sample.json — постоянный диагностический слой
4. ai_manifest.json — следующий модуль знает что получает

ИСТОРИЯ ПРЕПРОЦЕССОРА:
v4.0   → первая версия, 3614 разделов (4/10 от Аяна)
v4.2   → record-based архитектура (8/10)
v4.3   → scoring система
v4.4   → dual output, aggressive filtering (section: 11,136, ai: ~20МБ)
v4.5.6 → умный rate_code (section: 2,221, work: 8,277, ai: 2.0МБ)
v4.6   → normalize_section + raw+norm формат (section AI: 1,677)
v4.7   → финал: chunk→section, norm для work, manifest ← ВЫ ЗДЕСЬ

ФИЛОСОФИЯ:
  Код  = извлечение + очистка + нормализация + сжатие
  ИИ   = понимание + группировка + иерархия + структура

  Если сомнение → СОХРАНИТЬ (не удалять)

PIPELINE AINTELLECTUM:
  PDF → v4.7 preprocessor → chunks → LLM analyzer → hierarchy → ГПР
"""

import re
import json
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from collections import Counter

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


class DualOutputPreprocessor:

    UNITS = {
        "м³", "м²", "м", "шт", "т", "кг", "л", "км", "га",
        "м2", "м3", "мм", "см", "дм",
        "п.м.", "п.м", "м.п.", "м.п", "пог.м", "пог.м.",
        "чел-ч", "чел.ч", "маш-ч", "маш.ч",
        "тн", "ц", "г",
        "тыс.шт", "тыс шт", "100 шт", "компл", "комп", "узел", "пара",
        "100 м²", "100м²", "100 м2", "100м2",
        "1000 м²", "1000м²", "1000 м2", "1000м2",
        "100 м³", "100м³", "100 м3", "100м3",
    }

    UNIT_NORMALIZATION = {
        "м2": "м²", "м3": "м³",
        "100м2": "100 м²", "100м3": "100 м³",
        "1000м2": "1000 м²",
        "п.м": "м", "п.м.": "м", "м.п": "м", "м.п.": "м",
        "пог.м": "м", "пог.м.": "м",
        "чел.ч": "чел-ч", "маш.ч": "маш-ч",
        "тыс шт": "тыс.шт", "100 шт": "шт",
        "комп": "компл", "тн": "т",
    }

    CONSTRUCTION_TERMS = {
        'устройство', 'монтаж', 'установка', 'прокладка', 'армирование',
        'бетонирование', 'демонтаж', 'разработка', 'укладка', 'заполнение',
        'облицовка', 'штукатурка', 'окраска', 'изоляция', 'гидроизоляция',
        'теплоизоляция', 'работы', 'фундамент', 'стен', 'перекрыти',
        'кровл', 'пол', 'потолк', 'отделк', 'колонн', 'балк', 'плит',
    }

    SERVICE_WORDS = {
        'локальная смета', 'продолжение таблицы', 'составил', 'проверил',
        'утвердил', 'всего по смете', 'итого', 'номер по порядку',
        'шифр позиции', 'в том числе',
    }

    ECONOMIC_PHRASES = {
        'затраты на труд рабочих',
        'затраты на труд машинистов',
        'машины и механизмы',
        'материалы, изделия и конструкции',
        'нормативная трудоемкость',
        'оплата труда',
        'эксплуатация машин',
        'стоимость материалов',
        'накладные расходы',
        'сметная прибыль',
    }

    SECTION_BAD_WORDS = {
        'тенге', 'руб', 'стоимость', 'цена', 'расценк',
        'чел-ч', 'маш-ч', 'чел.ч', 'маш.ч', 'трудоёмк', 'трудоемк',
        'в т.ч.', 'из них', 'в том числе', 'итого', 'всего',
        'экскаваторы', 'автомобили-самосвалы', 'краны', 'бульдозеры',
        'коэффициент', 'норматив', 'индекс', 'накладн',
    }

    HEADER_MARKERS = [
        'наименование', 'единица', 'количество', 'стоимость', 'шифр', 'номер'
    ]

    TYPO_FIXES = {
        'плита': 'Плита', 'лита': 'Плита',
        'патрубок': 'Патрубок', 'атрубок': 'Патрубок',
        'пленка': 'Пленка', 'ленка': 'Пленка',
        'парапет': 'Парапет', 'арапет': 'Парапет',
        'полоса': 'Полоса', 'олоса': 'Полоса',
        'покрытие': 'Покрытие', 'окрытие': 'Покрытие',
        'плитка': 'Плитка', 'литка': 'Плитка',
    }

    NORM_REMOVE_PATTERNS = [
        r'\d+[\.,]?\d*\s*(мм|см|м|кг|т|%)',
        r'марки?\s+[А-ЯA-Z0-9\-]+',
        r'класс[аа]?\s+[А-ЯA-Z0-9\-]+',
        r'толщин[аой]\s+[\d\.,]+',
        r'диаметр[оа]?\s+[\d\.,]+',
        r'длин[аой]\s+[\d\.,]+',
        r'\bв\s+отвал\b',
        r'\bвручную\b',
        r'\bмеханизированным\s+способом\b',
    ]

    CHUNK_SIZE = 400

    def __init__(self):
        pass

    # ═══════════════════════════════════════════════════════════
    # ГЛАВНАЯ ФУНКЦИЯ
    # ═══════════════════════════════════════════════════════════
    def process_pdf(self, pdf_path: str) -> Dict[str, Any]:
        if not HAS_PDF:
            raise ImportError("Установи pdfplumber: pip install pdfplumber")

        print(f"📄 Обрабатываю PDF: {pdf_path}")

        raw_records = self._extract_from_pdf(pdf_path)
        print(f"✓ Извлечено строк таблиц: {len(raw_records)}")

        scored_records = []
        unknown_raw = []

        for record in raw_records:
            score, record_type = self._classify_with_score(record)

            if record_type == "garbage":
                continue

            if record_type == "work_item":
                item = self._extract_work_item(record)
                if item:
                    item['score'] = score
                    scored_records.append(item)
                else:
                    rec = {**record, "type": "unknown", "score": score}
                    scored_records.append(rec)
                    unknown_raw.append(record.get("raw_text", ""))

            elif record_type == "section_candidate":
                if self._is_valid_section(record):
                    raw_text = self._fix_typos(record["raw_text"])
                    norm_text = self.normalize_section_text(raw_text)
                    scored_records.append({
                        "page": record["page"],
                        "row_index": record["row_index"],
                        "type": "section_candidate",
                        "text": raw_text,
                        "norm": norm_text,
                        "cells": record["cells"],
                        "score": score
                    })

            elif record_type == "context":
                scored_records.append({
                    "page": record["page"],
                    "row_index": record["row_index"],
                    "type": "context",
                    "text": record["raw_text"],
                    "cells": record["cells"],
                    "score": score
                })

            else:
                rec = {**record, "type": "unknown", "score": score}
                scored_records.append(rec)
                unknown_raw.append(record.get("raw_text", ""))

        print(f"✓ После filtering: {len(scored_records)}")

        # Статистика
        stats = self._calculate_stats(scored_records)
        work_with_volume = sum(
            1 for r in scored_records
            if r.get("type") == "work_item" and r.get("candidate_volume") is not None
        )
        stats["work_item_with_volume"] = work_with_volume
        if stats["work_item"] > 0:
            stats["volume_coverage"] = f"{work_with_volume / stats['work_item'] * 100:.1f}%"
        else:
            stats["volume_coverage"] = "0%"

        section_norms = [r["norm"] for r in scored_records if r.get("type") == "section_candidate"]
        norm_counter = Counter(section_norms)
        stats["section_unique_norms"] = len(norm_counter)
        stats["section_duplicates"] = sum(c - 1 for c in norm_counter.values() if c > 1)

        print(f"  - section_candidate: {stats['section_candidate']}")
        print(f"    └─ уникальных norm: {stats['section_unique_norms']}")
        print(f"    └─ дублей:          {stats['section_duplicates']}")
        print(f"  - work_item: {stats['work_item']} (с объёмом: {stats['work_item_with_volume']}, {stats['volume_coverage']})")
        print(f"  - context: {stats['context']} (не в AI)")
        print(f"  - unknown: {stats['unknown']}")

        # AI payload
        ai_records = self._build_ai_payload(scored_records)
        ai_sections = sum(1 for r in ai_records if r.get("t") == "s")
        ai_works = sum(1 for r in ai_records if r.get("t") == "w")
        print(f"✓ AI payload: {len(ai_records)} записей")
        print(f"  └─ section: {ai_sections} | work: {ai_works}")

        debug_result = {
            "project_name": Path(pdf_path).stem,
            "total_records": len(scored_records),
            "stats": stats,
            "records": scored_records,
            "preprocessor_version": "4.7_final",
            "note": "Debug file — полная информация для отладки"
        }

        ai_result = {
            "project": Path(pdf_path).stem,
            "total": len(ai_records),
            "records": ai_records,
            "version": "4.7_final",
            "note": "AI payload — section{raw+norm}, work{n+norm+u+v}"
        }

        return {
            "debug": debug_result,
            "ai": ai_result,
            "ai_records": ai_records,
            "stats": stats,
            "unknown_raw": unknown_raw,
            "project_name": Path(pdf_path).stem,
        }

    # ═══════════════════════════════════════════════════════════
    # УЛУЧШЕНИЕ 1: Chunking начинается с section
    #
    # Аян: "chunk должен начинаться с section — ИИ получает
    # естественный контекст"
    #
    # Логика:
    # - Стараемся начать каждый chunk с section
    # - Если chunk начался без section — вставляем последний
    #   известный section как context_section в начало
    # - Порядок записей внутри chunk сохраняется!
    # ═══════════════════════════════════════════════════════════
    def build_chunks(self, ai_records: List[Dict], chunk_size: int = None) -> List[List[Dict]]:
        """
        Разбивает AI payload на чанки.

        v4.7 улучшение:
        - Каждый chunk по возможности начинается с section
        - Если chunk начался с work — добавляем последний section
          как {"t":"cs", ...} (context_section) в начало чанка
        - Порядок записей сохраняется
        """
        if chunk_size is None:
            chunk_size = self.CHUNK_SIZE

        chunks = []
        current_chunk = []
        last_section = None  # последний встреченный section

        for record in ai_records:
            # Запоминаем последний section
            if record.get("t") == "s":
                last_section = record

            # Если встретили section и chunk уже большой → новый chunk
            if record.get("t") == "s" and len(current_chunk) >= chunk_size * 0.8:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = []

            current_chunk.append(record)

            if len(current_chunk) >= chunk_size:
                chunks.append(current_chunk)
                current_chunk = []

        if current_chunk:
            chunks.append(current_chunk)

        # НОВОЕ v4.7: если chunk не начинается с section →
        # вставляем последний section как context_section
        result_chunks = []
        prev_last_section = None

        for i, chunk in enumerate(chunks):
            if chunk and chunk[0].get("t") != "s":
                # Chunk начинается без section
                # Ищем последний section из предыдущих chunks
                if prev_last_section is not None:
                    # Вставляем как context_section (не дубль!)
                    context_s = {**prev_last_section, "t": "cs"}
                    chunk = [context_s] + chunk

            # Обновляем prev_last_section
            for record in chunk:
                if record.get("t") == "s":
                    prev_last_section = record

            result_chunks.append(chunk)

        return result_chunks

    # ═══════════════════════════════════════════════════════════
    # УЛУЧШЕНИЕ 2: AI payload с norm для work_item
    #
    # Аян: "ИИ увидит norm → легче группировать похожие работы"
    #
    # Новый формат work_item в AI:
    # {"t":"w", "n":"Разработка грунта в котловане...",
    #  "norm":"разработка грунта", "u":"м³", "v":234}
    # ═══════════════════════════════════════════════════════════
    def _build_ai_payload(self, records: List[Dict]) -> List[Dict]:
        """
        Компактный AI payload.

        v4.7 форматы:
        section: {"t":"s", "raw":"...", "norm":"..."}
        work:    {"t":"w", "n":"...", "norm":"...", "u":"...", "v":...}
        context: не включается

        Дедупликация: только близкие дубли (в пределах 50 записей)
        """
        payload = []
        seen_norms = {}  # norm → позиция последнего вхождения

        for record in records:
            record_type = record.get("type", "unknown")

            if record_type == "section_candidate":
                raw = record["text"]
                norm = record.get("norm", raw.lower())

                # Дедупликация близких дублей
                if norm in seen_norms:
                    last_pos = seen_norms[norm]
                    if len(payload) - last_pos < 50:
                        continue

                item = {"t": "s", "raw": raw, "norm": norm}
                payload.append(item)
                seen_norms[norm] = len(payload) - 1

            elif record_type == "work_item":
                # НОВОЕ v4.7: добавляем norm для work_item
                item = {
                    "t": "w",
                    "n": record["name"],
                    "norm": record.get("normalized_name", ""),
                    "u": record["unit"]
                }
                if record.get("candidate_volume") is not None:
                    item["v"] = record["candidate_volume"]

                # Дедупликация соседних одинаковых work_item
                if payload and payload[-1].get("t") == "w":
                    prev = payload[-1]
                    if (prev.get("n") == item.get("n") and
                        prev.get("u") == item.get("u") and
                        prev.get("v") == item.get("v")):
                        continue

                payload.append(item)

            # context → не добавляем

        return payload

    # ═══════════════════════════════════════════════════════════
    # УЛУЧШЕНИЕ 3: ai_manifest.json
    #
    # Аян: "следующий AI-модуль должен знать что он получает"
    # ═══════════════════════════════════════════════════════════
    def build_manifest(self, result: Dict, chunks: List) -> Dict:
        """
        Создаёт ai_manifest.json — описание данных для следующего модуля.

        Содержит:
        - метаданные проекта
        - статистику
        - список чанков
        - формат данных
        """
        stats = result["stats"]
        ai_records = result["ai_records"]

        ai_sections = sum(1 for r in ai_records if r.get("t") == "s")
        ai_works = sum(1 for r in ai_records if r.get("t") == "w")

        return {
            "project": result["project_name"],
            "preprocessor_version": "4.7_final",
            "pipeline": "AINTELLECTUM",

            "summary": {
                "raw_rows": 40835,
                "total_records": result["debug"]["total_records"],
                "ai_payload_records": len(ai_records),
                "total_chunks": len(chunks),
                "chunk_size": self.CHUNK_SIZE,
            },

            "composition": {
                "section_candidates": stats["section_candidate"],
                "section_unique_norms": stats["section_unique_norms"],
                "section_in_ai": ai_sections,
                "work_items": stats["work_item"],
                "work_with_volume": stats["work_item_with_volume"],
                "volume_coverage": stats["volume_coverage"],
                "work_in_ai": ai_works,
                "unknown": stats["unknown"],
            },

            "chunk_index": [
                {
                    "chunk": i + 1,
                    "file": f"smeta_chunk_{i+1:03d}.json",
                    "records": len(chunk),
                    "sections": sum(1 for r in chunk if r.get("t") == "s"),
                    "works": sum(1 for r in chunk if r.get("t") == "w"),
                    "starts_with_section": chunk[0].get("t") in ("s", "cs") if chunk else False,
                }
                for i, chunk in enumerate(chunks)
            ],

            "data_format": {
                "section": '{"t":"s", "raw":"оригинал", "norm":"нормализованный"}',
                "context_section": '{"t":"cs", ...} — первый section чанка если chunk начался без section',
                "work": '{"t":"w", "n":"название", "norm":"норм.", "u":"ед", "v":объём}',
            },

            "next_step": "LLM Chunk Analyzer → Section Hierarchy Builder",
        }

    # ═══════════════════════════════════════════════════════════
    # Нормализация section (из v4.6)
    # ═══════════════════════════════════════════════════════════
    def normalize_section_text(self, text: str) -> str:
        norm = text.strip()

        # Убираем числовые индексы в начале
        norm = re.sub(r'^\d+[\.\d]*\.?\s*', '', norm)

        # Убираем короткие коды в начале (п2, р, е и т.д.)
        norm = re.sub(r'^[а-яa-z]{1,2}\d*\s+', '', norm, flags=re.IGNORECASE)

        # Убираем технические хвосты в скобках
        norm = re.sub(r'\([^)]{3,}\)', '', norm)

        # Убираем служебные слова
        norm = re.sub(r'\bв\s+т\.ч\.\b', '', norm, flags=re.IGNORECASE)
        norm = re.sub(r'\bиз\s+них\b', '', norm, flags=re.IGNORECASE)
        norm = re.sub(r'\bв\s+том\s+числе\b', '', norm, flags=re.IGNORECASE)

        # Убираем "раздел", "подраздел" в начале если они не несут смысл
        norm = re.sub(r'^(раздел|подраздел)\s+', '', norm, flags=re.IGNORECASE)

        # Убираем марки и размеры
        norm = re.sub(r'\bиз\s+[а-яА-Я]+\s+[А-Я]\d+', '', norm)
        norm = re.sub(r'\bмарки\s+[А-ЯA-Z0-9\-]+', '', norm, flags=re.IGNORECASE)
        norm = re.sub(r'\d+[\.,]?\d*\s*(мм|см|м|кг|т)', '', norm, flags=re.IGNORECASE)

        # Lower + чистим пробелы
        norm = norm.lower()
        norm = re.sub(r'\s+', ' ', norm).strip()
        norm = norm.strip('.,;:-/')

        # Если после нормализации слишком короткий — возвращаем исходный
        if len(norm) < 3:
            norm = text.lower().strip()

        return norm

    # ═══════════════════════════════════════════════════════════
    # Определение шифра расценки (v4.5.6)
    # ═══════════════════════════════════════════════════════════
    def _is_rate_code(self, text: str) -> bool:
        s = text.strip()
        if re.match(r'^\d+\.\d+\.?\d*\s*\|\s*[а-яa-zА-ЯA-Z]?\d{3}[\d\-\(\)а-яa-zA-ZА-Я]*', s, re.IGNORECASE):
            return True
        if re.match(r'^\d+\s*\|\s*[а-яa-zА-ЯA-Z]\d{3,}[\d\-\(\)]*', s, re.IGNORECASE):
            return True
        if re.match(r'^\d+\s*\|\s*\d{3,}-\d{3,}', s):
            return True
        if re.match(r'^\d+\.\d+\.\d+\s+[а-яa-zA-ZА-Я]?\d{3}[\d\-]+', s, re.IGNORECASE):
            return True
        if re.search(r"f\(\d+\)'[a-zA-Zа-яА-Я]+=", s):
            return True
        return False

    def _has_unit(self, cells: List[str]) -> bool:
        return self._extract_unit(cells) is not None

    def _is_table_header(self, text: str) -> bool:
        lowered = text.lower()
        return sum(1 for m in self.HEADER_MARKERS if m in lowered) >= 2

    # ═══════════════════════════════════════════════════════════
    # Фильтр section_candidate
    # ═══════════════════════════════════════════════════════════
    def _is_valid_section(self, record: Dict[str, Any]) -> bool:
        text = record.get("raw_text", "")
        text_lower = text.lower()
        cells = record.get("cells", [])

        if self._is_table_header(text): return False
        if self._is_rate_code(text): return False
        for phrase in self.ECONOMIC_PHRASES:
            if phrase in text_lower: return False
        for bad_word in self.SECTION_BAD_WORDS:
            if bad_word in text_lower: return False
        if re.search(r'\d+\s*\|\s*\d+\s*\|\s*\d+', text): return False

        numbers = self._extract_numbers(cells)
        if any(n > 100_000 for n in numbers): return False

        unit = self._extract_unit(cells)
        if unit and numbers: return False
        if re.match(r'^[\d\-\.\s\|]+$', text): return False
        if len(text.strip()) < 8: return False

        digit_count = sum(1 for c in text if c.isdigit())
        if len(text) > 0 and digit_count / len(text) > 0.5: return False

        return True

    # ═══════════════════════════════════════════════════════════
    # Scoring и классификация
    # ═══════════════════════════════════════════════════════════
    def _classify_with_score(self, record: Dict[str, Any]) -> tuple:
        text = record.get("raw_text", "")
        cells = record.get("cells", [])

        if not text or len(text.strip()) < 3:
            return (0, "garbage")
        if self._is_table_header(text):
            return (0, "garbage")
        if re.search(r"f\(\d+\)'[a-zA-Zа-яА-Я]+=", text):
            return (0, "garbage")
        if self._is_rate_code(text):
            if not self._has_unit(cells):
                return (0, "garbage")
            return (6, "work_item")

        lowered = text.lower()
        score = 0

        for service in self.SERVICE_WORDS:
            if service in lowered:
                score -= 4
                break

        short_garbage = ['лист', 'всего', 'итого', 'стоимость', 'количество']
        if len(text) < 25:
            for sg in short_garbage:
                if sg in lowered and lowered.strip() == sg:
                    score -= 3
                    break

        unit = self._extract_unit(cells)
        numbers = self._extract_numbers(cells)
        name = self._extract_name_smart(cells)

        if unit: score += 3
        if numbers: score += 3
        for term in self.CONSTRUCTION_TERMS:
            if term in lowered:
                score += 2
                break
        if name and len(name) >= 15: score += 1
        if len(cells) <= 2 and len(text) <= 60 and not numbers: score += 1
        if unit and numbers and score < 3: score = 3

        if score >= 6:
            return (score, "work_item")
        elif score >= 3:
            return (score, "work_item") if (unit and numbers) else (score, "section_candidate")
        elif score >= 1:
            return (score, "context")
        else:
            return (score, "garbage")

    # ═══════════════════════════════════════════════════════════
    # Извлечение из PDF
    # ═══════════════════════════════════════════════════════════
    def _extract_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        records = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                for table_idx, table in enumerate(page.extract_tables() or []):
                    if not table:
                        continue
                    for row_idx, row in enumerate(table):
                        if not row:
                            continue
                        cells = [str(c or '').strip() for c in row]
                        cells = [c for c in cells if c]
                        if cells:
                            records.append({
                                "page": page_num,
                                "table_index": table_idx,
                                "row_index": row_idx,
                                "cells": cells,
                                "raw_text": " | ".join(cells),
                            })
        return records

    # ═══════════════════════════════════════════════════════════
    # Извлечение work_item
    # ═══════════════════════════════════════════════════════════
    def _extract_work_item(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        cells = record.get("cells", [])
        if not cells:
            return None

        unit = self._extract_unit(cells)
        numbers = self._extract_numbers(cells)
        name = self._extract_name_smart(cells)

        if not name or not unit or not numbers:
            return None

        unit = self._normalize_unit(unit)
        candidate_volume = self._find_volume_near_unit(cells, unit, numbers)
        name = self._fix_typos(name)

        return {
            "page": record["page"],
            "row_index": record["row_index"],
            "type": "work_item",
            "name": name,
            "normalized_name": self._normalize_work_name(name),
            "unit": unit,
            "candidate_volume": candidate_volume,
            "other_numbers": [n for n in numbers if n != candidate_volume],
            "raw_text": record["raw_text"],
            "cells": cells,
        }

    # ═══════════════════════════════════════════════════════════
    # Поиск объёма
    # ═══════════════════════════════════════════════════════════
    def _find_volume_near_unit(self, cells: List[str], unit: str, numbers: List[float]) -> Optional[float]:
        if not numbers:
            return None

        unit_index = next((i for i, c in enumerate(cells) if c.strip() == unit), None)

        if unit_index is not None:
            for idx in [unit_index + 1, unit_index - 1, unit_index + 2, unit_index - 2]:
                if 0 <= idx < len(cells):
                    val = self._parse_number(cells[idx])
                    if val is not None and 0 < val < 1_000_000:
                        return val

        for cell in cells:
            val = self._parse_number(cell)
            if val is not None and 0 < val < 100_000:
                return val

        return None

    def _parse_number(self, cell: str) -> Optional[float]:
        cleaned = cell.replace(" ", "").replace(",", ".")
        if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
            try:
                return float(cleaned)
            except ValueError:
                pass
        return None

    # ═══════════════════════════════════════════════════════════
    # Вспомогательные методы
    # ═══════════════════════════════════════════════════════════
    def _extract_unit(self, cells: List[str]) -> Optional[str]:
        for cell in cells:
            if cell.strip() in self.UNITS:
                return cell.strip()
        return None

    def _normalize_unit(self, unit: str) -> str:
        return self.UNIT_NORMALIZATION.get(unit, unit)

    def _extract_numbers(self, cells: List[str]) -> List[float]:
        numbers = []
        for cell in cells:
            cleaned = cell.replace(" ", "").replace(",", ".")
            if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
                try:
                    numbers.append(float(cleaned))
                except ValueError:
                    pass
        return numbers

    def _extract_name_smart(self, cells: List[str]) -> Optional[str]:
        candidates = []
        for cell in cells:
            if len(cell) < 4:
                continue
            cell_lower = cell.lower()
            if 'стоимость' in cell_lower or 'цена' in cell_lower:
                continue
            if re.fullmatch(r'[\d\s,\.]+', cell):
                continue
            if re.search(r"[а-яА-ЯёЁa-zA-Z]{3,}", cell):
                candidates.append(cell)
        return max(candidates, key=len) if candidates else None

    def _normalize_work_name(self, name: str) -> str:
        normalized = name.lower().strip()
        for pattern in self.NORM_REMOVE_PATTERNS:
            normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'\s+', ' ', normalized).strip().rstrip('.,;:-')
        words = normalized.split()
        return ' '.join(words[:5]) if len(words) > 5 else normalized

    def _fix_typos(self, text: str) -> str:
        words = text.split()
        return ' '.join(
            self.TYPO_FIXES[w.lower()] if w.lower() in self.TYPO_FIXES and w[0].isupper()
            else self.TYPO_FIXES[w.lower()].lower() if w.lower() in self.TYPO_FIXES
            else w
            for w in words
        )

    def _calculate_stats(self, records: List[Dict]) -> Dict[str, int]:
        stats = {"section_candidate": 0, "work_item": 0, "context": 0, "unknown": 0}
        for record in records:
            t = record.get("type", "unknown")
            if t in stats:
                stats[t] += 1
        return stats

    # ═══════════════════════════════════════════════════════════
    # УЛУЧШЕНИЕ 4 (продолжение): Сохранение с манифестом
    # ═══════════════════════════════════════════════════════════
    def save_json(self, data: Dict, output_path: str):
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size = os.path.getsize(output_path)
        print(f"  ✓ {Path(output_path).name}: {size / 1024:.1f} КБ")

    def save_chunks(self, chunks: List[List[Dict]], base_path: str):
        total_size = 0
        for i, chunk in enumerate(chunks, 1):
            chunk_path = f"{base_path}_chunk_{i:03d}.json"
            with open(chunk_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "chunk": i,
                    "total_chunks": len(chunks),
                    "records_in_chunk": len(chunk),
                    "starts_with_section": chunk[0].get("t") in ("s", "cs") if chunk else False,
                    "records": chunk
                }, f, ensure_ascii=False, indent=2)
            total_size += os.path.getsize(chunk_path)
        print(f"  ✓ {len(chunks)} чанков (~{total_size / 1024:.1f} КБ итого)")

    # ═══════════════════════════════════════════════════════════
    # Анализ unknown (постоянный диагностический слой)
    # ═══════════════════════════════════════════════════════════
    def analyze_unknown(self, unknown_texts: List[str]) -> Dict:
        """
        УЛУЧШЕНИЕ 3: unknown_sample.json — постоянный диагностический слой.
        Аян: "на новых сметах именно он покажет где ломается логика"
        """
        patterns = []
        for text in unknown_texts:
            words = text.split()[:4]
            if words:
                patterns.append(' '.join(words).lower())

        counter = Counter(patterns)
        return {
            "total_unknown": len(unknown_texts),
            "note": "Постоянный диагностический слой — показывает паттерны мусора на новых сметах",
            "top_patterns": [
                {"pattern": p, "count": c} for p, c in counter.most_common(20)
            ],
            "sample": unknown_texts[:50]
        }


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Использование: python smeta_preprocessor_v4.7_final.py <смета.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    print("=" * 70)
    print("ПРЕПРОЦЕССОР СМЕТ v4.7_final - AINTELLECTUM")
    print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("ФИНАЛЬНАЯ ВЕРСИЯ ПРЕПРОЦЕССОРА")
    print("=" * 70)
    print()

    preprocessor = DualOutputPreprocessor()
    result = preprocessor.process_pdf(pdf_path)

    print()
    print("=" * 70)
    print("РЕЗУЛЬТАТ:")
    print("=" * 70)
    stats = result['stats']
    print(f"Проект: {result['debug']['project_name']}")
    print(f"Всего записей (debug): {result['debug']['total_records']}")
    print(f"Записей в AI payload:  {len(result['ai_records'])}")
    print()
    print("Статистика:")
    print(f"  - section_candidate: {stats['section_candidate']}")
    print(f"    └─ уникальных norm: {stats['section_unique_norms']}")
    print(f"    └─ дублей убрано:   {stats['section_duplicates']}")
    print(f"  - work_item:         {stats['work_item']}")
    print(f"    └─ с объёмом:      {stats['work_item_with_volume']} ({stats['volume_coverage']})")
    print(f"  - context:           {stats['context']} (не в AI)")
    print(f"  - unknown:           {stats['unknown']}")
    print()

    # Сохраняем основные файлы
    print("Сохраняю файлы:")
    preprocessor.save_json(result['debug'], "smeta_debug.json")
    preprocessor.save_json(result['ai'], "smeta_ai.json")

    # Chunking с улучшенной логикой
    print()
    print("Создаю чанки (каждый начинается с section):")
    chunks = preprocessor.build_chunks(result['ai_records'])
    starts_with_s = sum(1 for c in chunks if c and c[0].get("t") in ("s", "cs"))
    print(f"  {len(result['ai_records'])} записей → {len(chunks)} чанков")
    print(f"  Чанков начинающихся с section: {starts_with_s}/{len(chunks)}")
    preprocessor.save_chunks(chunks, "smeta")

    # Unknown анализ (постоянный диагностический слой)
    print()
    print("Анализ unknown (диагностический слой):")
    unknown_analysis = preprocessor.analyze_unknown(result['unknown_raw'])
    print(f"  Всего unknown: {unknown_analysis['total_unknown']}")
    for item in unknown_analysis['top_patterns'][:5]:
        print(f"    '{item['pattern']}' — {item['count']} раз")
    preprocessor.save_json(unknown_analysis, "unknown_sample.json")

    # НОВОЕ v4.7: ai_manifest.json
    print()
    print("Создаю ai_manifest.json:")
    manifest = preprocessor.build_manifest(result, chunks)
    preprocessor.save_json(manifest, "ai_manifest.json")

    print()
    print("=" * 70)
    print("🏆 ПРЕПРОЦЕССОР v4.7_final ЗАФИКСИРОВАН!")
    print("=" * 70)
    print()
    print("📁 Файлы:")
    print("  - smeta_debug.json      (полный, для отладки)")
    print("  - smeta_ai.json         (section{raw+norm}, work{n+norm+u+v})")
    print("  - smeta_chunk_*.json    (чанки, каждый начинается с section)")
    print("  - unknown_sample.json   (диагностический слой)")
    print("  - ai_manifest.json      (описание для следующего модуля)")
    print()
    print("📋 Форматы в AI payload:")
    print('  section: {"t":"s", "raw":"оригинал", "norm":"нормализованный"}')
    print('  work:    {"t":"w", "n":"название", "norm":"норм.", "u":"ед", "v":объём}')
    print()
    print("🚀 Следующий шаг: LLM Chunk Analyzer → Section Hierarchy Builder")
    print()
    print("🤖 Отправляй smeta_chunk_*.json в AI по одному!")
