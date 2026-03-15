# -*- coding: utf-8 -*-
"""
HIERARCHY BUILDER v5.0
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

НАЗНАЧЕНИЕ:
  Принимает результат препроцессора v4.7_final и строит иерархию сметы через LLM.

PIPELINE:
  smeta_chunk_*.json
         ↓
  [A] Chunk Analysis   → ИИ анализирует каждый чанк → chunk_analysis_*.json
         ↓
  [B] Merge Results    → код технически объединяет → chunk_analysis_merged.json
         ↓
  [C] Final Hierarchy  → ИИ строит общую структуру → section_hierarchy.json
         ↓
  section_hierarchy_summary.json

ФИЛОСОФИЯ:
  Код  = загрузить + отправить + сохранить + объединить + валидировать
  ИИ   = понять + различить + сгруппировать + построить иерархию

  Если ИИ сомневается → сохранить как отдельный подраздел (не терять!)
  Если work_item не привязан → класть в unassigned_work_items

ИСПОЛЬЗОВАНИЕ:
  python hierarchy_builder.py                    # полный прогон (A+B+C)
  python hierarchy_builder.py --step A           # только анализ чанков
  python hierarchy_builder.py --step B           # только merge
  python hierarchy_builder.py --step C           # только финальная иерархия
  python hierarchy_builder.py --chunk 5          # только один чанк (для теста)
"""

import os
import re
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

import anthropic

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════
MODEL = "claude-opus-4-5"
MAX_TOKENS = 16000
DELAY_BETWEEN_CHUNKS = 2  # секунды между запросами (rate limit)
MAX_RETRIES = 3            # повторных попыток при ошибке

# Файлы ввода (из препроцессора v4.7_final)
MANIFEST_FILE   = "ai_manifest.json"
CHUNKS_PATTERN  = "smeta_chunk_*.json"

# Файлы вывода
CHUNK_ANALYSIS_PATTERN  = "chunk_analysis_{:03d}.json"
MERGED_FILE             = "chunk_analysis_merged.json"
HIERARCHY_FILE          = "section_hierarchy.json"
SUMMARY_FILE            = "section_hierarchy_summary.json"


# ═══════════════════════════════════════════════════════════════
# ПРОМПТЫ ДЛЯ ИИ
# ═══════════════════════════════════════════════════════════════

CHUNK_ANALYSIS_PROMPT = """Ты анализируешь фрагмент строительной сметы.
Определи ТОЛЬКО структуру разделов. Работы перечислять НЕ НУЖНО.

ДАННЫЕ ФРАГМЕНТА:
{chunk_data}

ПРАВИЛА:
1. Определи разделы (level:1) и подразделы (level:2) по смыслу
2. Строки [РАБОТА] в ответ НЕ включай — только структуру разделов!
3. section с t="cs" — контекстный заголовок для ориентации
4. Если сомневаешься — создай отдельный подраздел
5. Отвечай ТОЛЬКО JSON без markdown, без ```, без пояснений

ФОРМАТ (строго):
{{"chunk_id": {chunk_id}, "sections": [{{"title_raw": "текст из данных", "title_norm": "норм текст", "level": 1, "children": [{{"title_raw": "текст", "title_norm": "норм", "level": 2}}]}}]}}"""


FINAL_HIERARCHY_PROMPT = """Проект: {project_name}. Строительная смета.
Ниже список разделов из {total_chunks} фрагментов сметы (формат: "raw" norm: "норм" подразделы: ...):

{merged_sections}

Объедини одинаковые разделы и построй иерархию строительных работ.
Порядок: логика строительства (земля→фундамент→каркас→стены→кровля→инженерия→отделка).
Только JSON, без markdown, без пояснений:
{{"project":"{project_name}","phases":[{{"phase":"название","norm":"норм","subsections":[{{"name":"подраздел","norm":"норм"}}]}}],"stats":{{"total_phases":0,"total_subsections":0}}}}"""


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def load_json(path: str) -> Optional[Dict]:
    """Загружает JSON файл."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  ⚠️ Файл не найден: {path}")
        return None
    except json.JSONDecodeError as e:
        print(f"  ⚠️ Ошибка JSON в {path}: {e}")
        return None


def save_json(data: Dict, path: str):
    """Сохраняет JSON файл."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(path)
    print(f"  ✓ {Path(path).name}: {size / 1024:.1f} КБ")


def find_chunks(pattern: str = CHUNKS_PATTERN) -> List[str]:
    """Находит все файлы чанков."""
    import glob
    files = sorted(glob.glob(pattern))
    return files


def extract_json_from_response(text: str) -> Optional[Dict]:
    # Убираем markdown блоки
    text = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    # Пробуем напрямую
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Ищем от { до }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass

    return None


def call_llm(client: anthropic.Anthropic, prompt: str, context: str = "") -> Optional[str]:
    """
    Вызывает LLM с повторными попытками.
    Код только оркестрирует — смысл остаётся за ИИ.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return message.content[0].text

        except anthropic.RateLimitError:
            wait = 30 * attempt
            print(f"    ⏳ Rate limit, жду {wait}с (попытка {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)

        except anthropic.APIError as e:
            print(f"    ⚠️ API ошибка (попытка {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(10)

    print(f"    ❌ Все {MAX_RETRIES} попытки исчерпаны")
    return None


def compact_chunk_for_prompt(chunk_data: Dict) -> str:
    """
    Компактный формат чанка для промпта.
    Убираем лишние технические поля, оставляем только нужное ИИ.
    """
    records = chunk_data.get("records", [])
    lines = []

    for r in records:
        t = r.get("t")
        if t == "s":
            lines.append(f'[РАЗДЕЛ] raw="{r.get("raw","")}" norm="{r.get("norm","")}"')
        elif t == "cs":
            lines.append(f'[КОНТЕКСТ] raw="{r.get("raw","")}" norm="{r.get("norm","")}"')
        elif t == "w":
            vol = r.get("v", "")
            vol_str = f' объём={vol}' if vol else ''
            lines.append(f'[РАБОТА] name="{r.get("n","")}" norm="{r.get("norm","")}" unit={r.get("u","")}{vol_str}')

    return "\n".join(lines)


def count_work_items_in_hierarchy(hierarchy: Dict) -> int:
    """Считает все work_item в иерархии."""
    count = 0
    for phase in hierarchy.get("phases", []):
        for sub in phase.get("subsections", []):
            count += len(sub.get("work_items", []))
    count += len(hierarchy.get("unassigned_work_items", []))
    return count


# ═══════════════════════════════════════════════════════════════
# ЭТАП A: АНАЛИЗ ЧАНКОВ
# ═══════════════════════════════════════════════════════════════

def step_a_analyze_chunks(
    client: anthropic.Anthropic,
    chunk_files: List[str],
    only_chunk: Optional[int] = None
) -> List[str]:
    """
    Этап A: отправляет каждый чанк в ИИ, получает локальную иерархию.

    Код только:
    - загружает чанк
    - форматирует промпт
    - вызывает ИИ
    - валидирует JSON
    - сохраняет результат

    ИИ делает:
    - понимает структуру
    - строит локальную иерархию
    """
    print("\n" + "="*60)
    print("ЭТАП A: АНАЛИЗ ЧАНКОВ")
    print("="*60)

    result_files = []
    total = len(chunk_files)

    for i, chunk_file in enumerate(chunk_files, 1):
        chunk_num = i

        # Если тестируем один чанк
        if only_chunk is not None and chunk_num != only_chunk:
            continue

        # Проверяем — уже обработан?
        output_file = CHUNK_ANALYSIS_PATTERN.format(chunk_num)
        if os.path.exists(output_file):
            if only_chunk is None:
                # Полный прогон — пропускаем уже обработанные
                print(f"  [{chunk_num:2d}/{total}] ⏭️ Пропускаю (уже есть): {output_file}")
                result_files.append(output_file)
                continue
            else:
                # --chunk N — всегда перезаписываем принудительно
                os.remove(output_file)
                print(f"  [{chunk_num:2d}/{total}] 🔄 Перезаписываю: {output_file}")

        print(f"  [{chunk_num:2d}/{total}] Анализирую: {chunk_file}")

        # Загружаем чанк
        chunk_data = load_json(chunk_file)
        if not chunk_data:
            print(f"    ⚠️ Пропускаю — не удалось загрузить")
            continue

        records_count = chunk_data.get("records_in_chunk", len(chunk_data.get("records", [])))
        print(f"    Записей в чанке: {records_count}")

        # Форматируем данные для промпта
        compact_data = compact_chunk_for_prompt(chunk_data)

        # Строим промпт
        prompt = CHUNK_ANALYSIS_PROMPT.format(
            chunk_id=chunk_num,
            chunk_data=compact_data
        )

        # Вызываем ИИ
        print(f"    🤖 Отправляю в LLM...")
        response_text = call_llm(client, prompt)

        if not response_text:
            print(f"    ❌ Нет ответа от LLM")
            # Сохраняем fallback — пустой результат
            fallback = {
                "chunk_id": chunk_num,
                "error": "no_response",
                "sections": [],
                "unassigned_work_items": []
            }
            # Собираем все work_item чанка в unassigned
            for r in chunk_data.get("records", []):
                if r.get("t") == "w":
                    fallback["unassigned_work_items"].append({
                        "name": r.get("n", ""),
                        "norm": r.get("norm", ""),
                        "unit": r.get("u", ""),
                        "volume": r.get("v")
                    })
            save_json(fallback, output_file)
            result_files.append(output_file)
            continue

        # Парсим JSON из ответа
        analysis = extract_json_from_response(response_text)

        if not analysis:
            print(f"    ⚠️ Не удалось распарсить JSON, сохраняю raw ответ")
            analysis = {
                "chunk_id": chunk_num,
                "error": "json_parse_failed",
                "raw_response": response_text[:500],
                "sections": [],
                "unassigned_work_items": []
            }

        # Убеждаемся что chunk_id правильный
        analysis["chunk_id"] = chunk_num
        analysis["source_file"] = chunk_file

        # Считаем работы
        work_count = sum(
            len(sub.get("work_items", []))
            for sec in analysis.get("sections", [])
            for sub in sec.get("children", [])
        ) + len(analysis.get("unassigned_work_items", []))
        print(f"    ✓ Разделов: {len(analysis.get('sections', []))}, работ: {work_count}")

        save_json(analysis, output_file)
        result_files.append(output_file)

        # Пауза между запросами
        if i < total and only_chunk is None:
            time.sleep(DELAY_BETWEEN_CHUNKS)

    print(f"\n  ✅ Этап A завершён: обработано {len(result_files)} чанков")
    return result_files


# ═══════════════════════════════════════════════════════════════
# ЭТАП B: ОБЪЕДИНЕНИЕ РЕЗУЛЬТАТОВ
# ═══════════════════════════════════════════════════════════════

def step_b_merge_results(
    result_files: List[str],
    manifest: Dict
) -> Optional[Dict]:
    """
    Этап B: технически объединяет результаты всех чанков.

    Код НЕ делает смысловых решений — только:
    - загружает все chunk_analysis_*.json
    - собирает в единый merged объект
    - группирует section по norm (кандидаты для объединения)
    - считает статистику
    """
    print("\n" + "="*60)
    print("ЭТАП B: ОБЪЕДИНЕНИЕ РЕЗУЛЬТАТОВ")
    print("="*60)

    if not result_files:
        # Автоматически ищем файлы
        import glob
        result_files = sorted(glob.glob("chunk_analysis_*.json"))
        print(f"  Найдено файлов: {len(result_files)}")

    chunk_results = []
    all_sections_by_norm = {}  # norm → [вхождения из разных чанков]
    total_works = 0
    total_unassigned = 0

    for f in result_files:
        data = load_json(f)
        if not data:
            continue

        chunk_id = data.get("chunk_id", "?")
        print(f"  Обрабатываю chunk {chunk_id}: {f}")

        # Собираем уникальные section_norms для анализа
        for section in data.get("sections", []):
            norm = section.get("title_norm", "").lower().strip()
            if norm:
                if norm not in all_sections_by_norm:
                    all_sections_by_norm[norm] = []
                all_sections_by_norm[norm].append({
                    "chunk_id": chunk_id,
                    "title_raw": section.get("title_raw", ""),
                    "children_count": len(section.get("children", []))
                })

            # Считаем работы
            for child in section.get("children", []):
                total_works += len(child.get("work_items", []))

        total_unassigned += len(data.get("unassigned_work_items", []))
        chunk_results.append(data)

    # Находим дублирующиеся разделы (встречаются в 2+ чанках)
    duplicate_sections = {
        norm: entries
        for norm, entries in all_sections_by_norm.items()
        if len(entries) > 1
    }

    merged = {
        "project": manifest.get("project", "unknown"),
        "preprocessor_version": manifest.get("preprocessor_version", "4.7_final"),
        "hierarchy_version": "5.0",
        "chunks_processed": len(chunk_results),
        "stats": {
            "total_works_assigned": total_works,
            "total_works_unassigned": total_unassigned,
            "total_works": total_works + total_unassigned,
            "unique_section_norms": len(all_sections_by_norm),
            "duplicate_section_norms": len(duplicate_sections),
        },
        "duplicate_sections_info": [
            {
                "norm": norm,
                "appears_in_chunks": [e["chunk_id"] for e in entries],
                "count": len(entries)
            }
            for norm, entries in sorted(
                duplicate_sections.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:20]  # топ 20 дублей
        ],
        "chunk_results": chunk_results,
    }

    print(f"\n  Статистика merge:")
    print(f"  - Чанков обработано: {len(chunk_results)}")
    print(f"  - Работ распределено: {total_works}")
    print(f"  - Работ unassigned:   {total_unassigned}")
    print(f"  - Уникальных section norm: {len(all_sections_by_norm)}")
    print(f"  - Дублирующихся section:   {len(duplicate_sections)}")

    save_json(merged, MERGED_FILE)
    print(f"\n  ✅ Этап B завершён: {MERGED_FILE}")

    return merged


# ═══════════════════════════════════════════════════════════════
# ЭТАП C: ФИНАЛЬНАЯ ИЕРАРХИЯ
# ═══════════════════════════════════════════════════════════════

def step_c_build_final_hierarchy(
    client: anthropic.Anthropic,
    merged: Dict
) -> Optional[Dict]:
    """
    Этап C: финальный ИИ-проход строит общую иерархию всей сметы.

    Код:
    - готовит компактное представление merged данных для промпта
    - вызывает ИИ
    - валидирует результат
    - сохраняет section_hierarchy.json и summary

    ИИ:
    - объединяет одинаковые разделы из разных чанков
    - строит общую иерархию фаз/разделов/подразделов
    - распределяет все work_item
    """
    print("\n" + "="*60)
    print("ЭТАП C: ФИНАЛЬНАЯ ИЕРАРХИЯ")
    print("="*60)

    # ОПТИМИЗАЦИЯ v5.0: отправляем ТОЛЬКО уникальные norm разделов
    # Вместо 86КБ → ~5КБ промпт
    seen_norms = {}
    for chunk_result in merged.get("chunk_results", []):
        chunk_id = chunk_result.get("chunk_id")
        for section in chunk_result.get("sections", []):
            norm = section.get("title_norm", "").strip()
            raw = section.get("title_raw", "").strip()
            if norm not in seen_norms:
                seen_norms[norm] = {"raw": raw, "chunks": [chunk_id], "children": []}
            else:
                seen_norms[norm]["chunks"].append(chunk_id)
            for child in section.get("children", []):
                child_norm = child.get("title_norm", "").strip()
                if child_norm and child_norm not in seen_norms[norm]["children"]:
                    seen_norms[norm]["children"].append(child_norm)

    # Строим компактный список для промпта
    compact_lines = []
    for norm, info in seen_norms.items():
        chunks_str = f"чанки {info['chunks'][:3]}"
        children_str = ", ".join(info["children"][:5]) if info["children"] else "—"
        compact_lines.append(f'- "{info["raw"]}" (norm: "{norm}", {chunks_str}, подразделы: {children_str})')

    merged_sections_str = "\n".join(compact_lines)

    # Строим промпт
    prompt = FINAL_HIERARCHY_PROMPT.format(
        total_chunks=merged.get("chunks_processed", 0),
        project_name=merged.get("project", "unknown"),
        merged_sections=merged_sections_str
    )

    print(f"  🤖 Отправляю в LLM финальный промпт...")
    print(f"  Размер промпта: ~{len(prompt) // 1000} КБ")

    response_text = call_llm(client, prompt)

    if not response_text:
        print("  ❌ Нет ответа от LLM на финальный промпт")
        return None

    # Парсим результат
    hierarchy = extract_json_from_response(response_text)

    if not hierarchy:
        print("  ⚠️ Не удалось распарсить JSON финальной иерархии")
        # Сохраняем raw ответ для диагностики
        with open("hierarchy_raw_response.txt", 'w', encoding='utf-8') as f:
            f.write(response_text)
        print("  Сырой ответ сохранён: hierarchy_raw_response.txt")
        return None

    # Считаем финальную статистику
    total_phases = len(hierarchy.get("phases", []))
    total_subsections = sum(
        len(p.get("subsections", []))
        for p in hierarchy.get("phases", [])
    )
    total_works = count_work_items_in_hierarchy(hierarchy)
    unassigned_count = len(hierarchy.get("unassigned_work_items", []))

    # Обновляем stats в иерархии
    hierarchy["stats"] = {
        "total_phases": total_phases,
        "total_subsections": total_subsections,
        "total_work_items": total_works,
        "unassigned_count": unassigned_count,
    }
    hierarchy["hierarchy_version"] = "5.0"

    print(f"\n  Результат финальной иерархии:")
    print(f"  - Фаз/разделов: {total_phases}")
    print(f"  - Подразделов:  {total_subsections}")
    print(f"  - Работ:        {total_works}")
    print(f"  - Unassigned:   {unassigned_count}")

    save_json(hierarchy, HIERARCHY_FILE)

    # Строим summary — короткая версия для человека
    summary = build_summary(hierarchy)
    save_json(summary, SUMMARY_FILE)

    print(f"\n  ✅ Этап C завершён!")
    return hierarchy


# ═══════════════════════════════════════════════════════════════
# SUMMARY ДЛЯ ЧЕЛОВЕКА
# ═══════════════════════════════════════════════════════════════

def build_summary(hierarchy: Dict) -> Dict:
    """Строит короткую версию иерархии для чтения человеком."""
    stats = hierarchy.get("stats", {})

    phases_summary = []
    for phase in hierarchy.get("phases", []):
        subsections = phase.get("subsections", [])
        work_count = sum(len(s.get("work_items", [])) for s in subsections)
        phases_summary.append({
            "phase": phase.get("phase", ""),
            "norm": phase.get("norm", ""),
            "subsections_count": len(subsections),
            "work_items_count": work_count,
            "subsections": [
                {
                    "name": s.get("name", ""),
                    "work_items_count": len(s.get("work_items", []))
                }
                for s in subsections
            ]
        })

    return {
        "project": hierarchy.get("project", ""),
        "hierarchy_version": "5.0",
        "top_sections": [p.get("phase", "") for p in hierarchy.get("phases", [])],
        "total_phases": stats.get("total_phases", 0),
        "total_subsections": stats.get("total_subsections", 0),
        "total_work_items": stats.get("total_work_items", 0),
        "unassigned_work_items": stats.get("unassigned_count", 0),
        "phases_detail": phases_summary,
        "note": "Читаемая версия section_hierarchy.json для инженера"
    }


# ═══════════════════════════════════════════════════════════════
# ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="AINTELLECTUM Hierarchy Builder v5.0"
    )
    parser.add_argument(
        "--step",
        choices=["A", "B", "C", "all"],
        default="all",
        help="Какой этап запустить (A=анализ чанков, B=merge, C=иерархия, all=всё)"
    )
    parser.add_argument(
        "--chunk",
        type=int,
        default=None,
        help="Тест: обработать только один чанк (номер)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("HIERARCHY BUILDER v5.0 - AINTELLECTUM")
    print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("=" * 60)
    print()

    # Загружаем манифест
    manifest = load_json(MANIFEST_FILE)
    if not manifest:
        print(f"❌ Не найден {MANIFEST_FILE}")
        print("   Сначала запусти препроцессор v4.7_final!")
        return

    project = manifest.get("project", "unknown")
    total_chunks = manifest.get("summary", {}).get("total_chunks", 0)
    print(f"Проект: {project}")
    print(f"Чанков: {total_chunks}")
    print(f"Работ:  {manifest.get('composition', {}).get('work_items', 0)}")
    print()

    # Инициализируем клиент
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Пробуем загрузить из .env
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        except ImportError:
            pass

    if not api_key:
        print("❌ ANTHROPIC_API_KEY не найден!")
        print("   Добавь в .env: ANTHROPIC_API_KEY=sk-ant-...")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Находим чанки
    chunk_files = find_chunks()
    if not chunk_files:
        print("❌ Чанки не найдены! Паттерн:", CHUNKS_PATTERN)
        return

    print(f"Найдено чанков: {len(chunk_files)}")
    print()

    result_files = []
    merged = None
    hierarchy = None

    # ── ЭТАП A ──
    if args.step in ("A", "all"):
        result_files = step_a_analyze_chunks(client, chunk_files, args.chunk)

    # ── ЭТАП B ──
    if args.step in ("B", "all") and args.chunk is None:
        import glob
        if not result_files:
            result_files = sorted(glob.glob("chunk_analysis_*.json"))
        merged = step_b_merge_results(result_files, manifest)

    # ── ЭТАП C ──
    if args.step in ("C", "all") and args.chunk is None:
        if merged is None:
            merged = load_json(MERGED_FILE)
        if merged:
            hierarchy = step_c_build_final_hierarchy(client, merged)
        else:
            print("❌ Нет merged данных для этапа C")
            print(f"   Сначала запусти этап B или убедись что есть {MERGED_FILE}")

    # ── ИТОГ ──
    print()
    print("=" * 60)
    if args.chunk:
        print(f"🧪 ТЕСТ чанка {args.chunk} завершён")
    else:
        print("🏆 HIERARCHY BUILDER v5.0 ЗАВЕРШЁН!")
    print("=" * 60)
    print()

    files_created = []
    if args.step in ("A", "all"):
        files_created.append("chunk_analysis_*.json  (ответы ИИ по каждому чанку)")
    if args.step in ("B", "all") and not args.chunk:
        files_created.append(f"{MERGED_FILE}  (объединённые результаты)")
    if args.step in ("C", "all") and not args.chunk:
        files_created.append(f"{HIERARCHY_FILE}  (финальная иерархия)")
        files_created.append(f"{SUMMARY_FILE}  (краткая версия для инженера)")

    if files_created:
        print("📁 Создано файлов:")
        for f in files_created:
            print(f"  - {f}")

    if hierarchy:
        stats = hierarchy.get("stats", {})
        print()
        print("📊 Итог иерархии:")
        print(f"  Фаз/разделов: {stats.get('total_phases', '?')}")
        print(f"  Подразделов:  {stats.get('total_subsections', '?')}")
        print(f"  Работ:        {stats.get('total_work_items', '?')}")
        if stats.get('unassigned_count', 0) > 0:
            print(f"  ⚠️ Unassigned: {stats.get('unassigned_count')}")

    print()
    print("🚀 Следующий шаг: укрупнение → длительности → ГПР")


if __name__ == "__main__":
    main()