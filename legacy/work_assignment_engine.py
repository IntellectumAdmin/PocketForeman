# -*- coding: utf-8 -*-
"""
WORK ASSIGNMENT ENGINE v1.0
Архитектура: Аян (ChatGPT) | Разработка: Claude (Anthropic)
Проект: AINTELLECTUM | Капитан: Ереке

НАЗНАЧЕНИЕ:
  Привязывает 8,277 работ к 273 подразделам иерархии сметы.

PIPELINE:
  smeta_ai.json + section_hierarchy.json
         ↓
  [A] Батчевая привязка через LLM
         ↓
  [B] Агрегация объёмов
         ↓
  [C] Сводка по фазам
         ↓
  work_assignment.json + volume_summary.json

ФИЛОСОФИЯ:
  Код  = загрузить + батчи + сохранить + агрегировать
  ИИ   = понять смысл работы + найти подраздел

ИСПОЛЬЗОВАНИЕ:
  python work_assignment_engine.py              # полный прогон
  python work_assignment_engine.py --test 20   # тест на 20 работах
  python work_assignment_engine.py --step A    # только привязка
  python work_assignment_engine.py --step B    # только агрегация
"""

import os
import re
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════
MODEL       = "claude-haiku-4-5-20251001"
MAX_TOKENS  = 8192
BATCH_SIZE  = 100    # работ за один запрос к ИИ
DELAY       = 1.5   # секунды между запросами
MAX_RETRIES = 3

# Файлы ввода
HIERARCHY_FILE = "section_hierarchy.json"
SMETA_AI_FILE  = "smeta_ai.json"

# Файлы вывода
BATCHES_FILE        = "work_batches_result.json"
ASSIGNMENT_FILE     = "work_assignment.json"
VOLUME_SUMMARY_FILE = "volume_summary.json"


# ═══════════════════════════════════════════════════════════════
# ПРОМПТ ДЛЯ ПРИВЯЗКИ РАБОТ
# ═══════════════════════════════════════════════════════════════
ASSIGNMENT_PROMPT = """Ты привязываешь строительные работы к разделам сметы.

ДОСТУПНЫЕ РАЗДЕЛЫ И ПОДРАЗДЕЛЫ:
{hierarchy_compact}

РАБОТЫ ДЛЯ ПРИВЯЗКИ (batch {batch_num}):
{works_list}

ПРАВИЛА:
1. Каждую работу привяжи к самому подходящему подразделу
2. Используй смысл названия работы, а не только ключевые слова
3. Если работа не подходит ни к одному подразделу — используй "unassigned"
4. Отвечай ТОЛЬКО JSON без markdown и пояснений

ФОРМАТ ОТВЕТА:
{{"assignments": [{{"work_id": 0, "phase": "название фазы", "subsection": "название подраздела"}}]}}"""


# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════
def load_json(path: str) -> Optional[Dict]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  ⚠️ Не найден: {path}")
        return None
    except json.JSONDecodeError as e:
        print(f"  ⚠️ Ошибка JSON в {path}: {e}")
        return None


def save_json(data: Any, path: str):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(path)
    print(f"  ✓ {Path(path).name}: {size / 1024:.1f} КБ")


def extract_json(text: str) -> Optional[Dict]:
    text = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```\s*', '', text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    return None


def call_llm(client: anthropic.Anthropic, prompt: str) -> Optional[str]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}]
            )
            return msg.content[0].text
        except anthropic.RateLimitError:
            wait = 30 * attempt
            print(f"    ⏳ Rate limit, жду {wait}с...")
            time.sleep(wait)
        except Exception as e:
            print(f"    ⚠️ Ошибка (попытка {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(10)
    return None


def build_hierarchy_compact(hierarchy: Dict) -> str:
    """
    Строит компактный список разделов/подразделов для промпта.
    Формат: "Фаза → Подраздел"
    """
    lines = []
    for phase in hierarchy.get("phases", []):
        phase_name = phase.get("phase", "")
        for sub in phase.get("subsections", []):
            sub_name = sub.get("name", "")
            lines.append(f'"{phase_name}" → "{sub_name}"')
    return "\n".join(lines)


def extract_works_from_smeta(smeta: Dict) -> List[Dict]:
    """Извлекает все work_item из smeta_ai.json."""
    works = []
    records = smeta.get("records", [])
    work_id = 0
    for record in records:
        if record.get("t") == "w":
            works.append({
                "id": work_id,
                "name": record.get("n", ""),
                "norm": record.get("norm", ""),
                "unit": record.get("u", ""),
                "volume": record.get("v")
            })
            work_id += 1
    return works


# ═══════════════════════════════════════════════════════════════
# ЭТАП A: ПРИВЯЗКА РАБОТ К ПОДРАЗДЕЛАМ
# ═══════════════════════════════════════════════════════════════
def step_a_assign_works(
    client: anthropic.Anthropic,
    works: List[Dict],
    hierarchy: Dict,
    test_limit: Optional[int] = None
) -> List[Dict]:
    """
    Батчами отправляет работы в ИИ для привязки к подразделам.
    """
    print("\n" + "="*60)
    print("ЭТАП A: ПРИВЯЗКА РАБОТ К ПОДРАЗДЕЛАМ")
    print("="*60)

    if test_limit:
        works = works[:test_limit]
        print(f"  🧪 Тест режим: {test_limit} работ из {len(works)}")

    hierarchy_compact = build_hierarchy_compact(hierarchy)
    total = len(works)
    batches = [works[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

    print(f"  Работ: {total}")
    print(f"  Батчей: {len(batches)} по {BATCH_SIZE}")
    print()

    all_assignments = []
    failed_batches = []

    # Загружаем уже обработанные батчи если есть
    existing = load_json(BATCHES_FILE)
    processed_batches = set()
    if existing:
        for a in existing.get("assignments", []):
            batch_num = a.get("batch_num")
            if batch_num is not None:
                processed_batches.add(batch_num)
        all_assignments = existing.get("assignments", [])
        print(f"  ↩️ Найдено уже обработанных батчей: {len(processed_batches)}")

    for batch_idx, batch in enumerate(batches, 1):
        if batch_idx in processed_batches:
            print(f"  [{batch_idx:3d}/{len(batches)}] ⏭️ Пропускаю (уже есть)")
            continue

        # Строим список работ для промпта
        works_lines = []
        for w in batch:
            vol_str = f", объём={w['volume']}" if w.get('volume') else ""
            works_lines.append(
                f'{{"work_id":{w["id"]}, "name":"{w["name"]}", "norm":"{w["norm"]}", "unit":"{w["unit"]}"{vol_str}}}'
            )
        works_str = "\n".join(works_lines)

        prompt = ASSIGNMENT_PROMPT.format(
            hierarchy_compact=hierarchy_compact,
            batch_num=batch_idx,
            works_list=works_str
        )

        print(f"  [{batch_idx:3d}/{len(batches)}] Обрабатываю {len(batch)} работ...")

        response = call_llm(client, prompt)
        if not response:
            print(f"    ❌ Нет ответа — сохраняю как unassigned")
            for w in batch:
                all_assignments.append({
                    "batch_num": batch_idx,
                    "work_id": w["id"],
                    "name": w["name"],
                    "norm": w["norm"],
                    "unit": w["unit"],
                    "volume": w.get("volume"),
                    "phase": "unassigned",
                    "subsection": "unassigned",
                    "error": "no_response"
                })
            failed_batches.append(batch_idx)
            continue

        result = extract_json(response)
        if not result or "assignments" not in result:
            print(f"    ⚠️ Не удалось распарсить — сохраняю как unassigned")
            for w in batch:
                all_assignments.append({
                    "batch_num": batch_idx,
                    "work_id": w["id"],
                    "name": w["name"],
                    "norm": w["norm"],
                    "unit": w["unit"],
                    "volume": w.get("volume"),
                    "phase": "unassigned",
                    "subsection": "unassigned",
                    "error": "parse_failed"
                })
            failed_batches.append(batch_idx)
            continue

        # Объединяем результат с данными работ
        assignments_map = {
            a["work_id"]: a
            for a in result["assignments"]
        }

        batch_assigned = 0
        batch_unassigned = 0
        for w in batch:
            assignment = assignments_map.get(w["id"], {})
            phase = assignment.get("phase", "unassigned")
            subsection = assignment.get("subsection", "unassigned")

            if phase and phase != "unassigned":
                batch_assigned += 1
            else:
                batch_unassigned += 1

            all_assignments.append({
                "batch_num": batch_idx,
                "work_id": w["id"],
                "name": w["name"],
                "norm": w["norm"],
                "unit": w["unit"],
                "volume": w.get("volume"),
                "phase": phase,
                "subsection": subsection
            })

        print(f"    ✓ Привязано: {batch_assigned}, unassigned: {batch_unassigned}")

        # Сохраняем промежуточный результат после каждого батча
        save_json(
            {"assignments": all_assignments, "total": len(all_assignments)},
            BATCHES_FILE
        )

        if batch_idx < len(batches):
            time.sleep(DELAY)

    assigned_count = sum(
        1 for a in all_assignments
        if a.get("phase", "unassigned") != "unassigned"
    )
    unassigned_count = len(all_assignments) - assigned_count

    print(f"\n  ✅ Этап A завершён!")
    print(f"  Привязано:    {assigned_count}")
    print(f"  Unassigned:   {unassigned_count}")
    if failed_batches:
        print(f"  ⚠️ Ошибочных батчей: {len(failed_batches)}")

    return all_assignments


# ═══════════════════════════════════════════════════════════════
# ЭТАП B: АГРЕГАЦИЯ — СТРОИМ ИЕРАРХИЮ С РАБОТАМИ
# ═══════════════════════════════════════════════════════════════
def step_b_aggregate(
    assignments: List[Dict],
    hierarchy: Dict
) -> Dict:
    """
    Агрегирует привязки и строит финальный work_assignment.json.

    Структура:
    phase → subsection → work_items → volumes
    """
    print("\n" + "="*60)
    print("ЭТАП B: АГРЕГАЦИЯ ОБЪЁМОВ")
    print("="*60)

    # Строим словарь фаз и подразделов из иерархии
    hierarchy_map = {}
    for phase in hierarchy.get("phases", []):
        phase_name = phase.get("phase", "")
        hierarchy_map[phase_name] = {
            "norm": phase.get("norm", ""),
            "subsections": {}
        }
        for sub in phase.get("subsections", []):
            sub_name = sub.get("name", "")
            hierarchy_map[phase_name]["subsections"][sub_name] = []

    # Добавляем unassigned
    hierarchy_map["unassigned"] = {
        "norm": "unassigned",
        "subsections": {"unassigned": []}
    }

    # Распределяем работы
    for a in assignments:
        phase = a.get("phase", "unassigned")
        subsection = a.get("subsection", "unassigned")

        # Если фаза не найдена — unassigned
        if phase not in hierarchy_map:
            phase = "unassigned"
            subsection = "unassigned"

        # Если подраздел не найден в фазе — добавляем
        if subsection not in hierarchy_map[phase]["subsections"]:
            hierarchy_map[phase]["subsections"][subsection] = []

        hierarchy_map[phase]["subsections"][subsection].append({
            "name": a.get("name", ""),
            "norm": a.get("norm", ""),
            "unit": a.get("unit", ""),
            "volume": a.get("volume")
        })

    # Строим финальный результат с агрегацией
    phases_result = []
    total_works = 0
    total_unassigned = 0

    for phase_name, phase_data in hierarchy_map.items():
        if phase_name == "unassigned":
            continue

        subsections_result = []
        phase_work_count = 0
        phase_volume_by_unit = defaultdict(float)

        for sub_name, works in phase_data["subsections"].items():
            sub_volume_by_unit = defaultdict(float)
            for w in works:
                vol = w.get("volume")
                unit = w.get("unit", "")
                if vol and unit:
                    sub_volume_by_unit[unit] += vol

            subsections_result.append({
                "name": sub_name,
                "work_items_count": len(works),
                "volumes": dict(sub_volume_by_unit),
                "work_items": works
            })
            phase_work_count += len(works)
            for unit, vol in sub_volume_by_unit.items():
                phase_volume_by_unit[unit] += vol

        phases_result.append({
            "phase": phase_name,
            "norm": phase_data["norm"],
            "subsections_count": len(subsections_result),
            "work_items_count": phase_work_count,
            "volumes": dict(phase_volume_by_unit),
            "subsections": subsections_result
        })
        total_works += phase_work_count

    # Unassigned
    unassigned_works = hierarchy_map.get("unassigned", {}).get("subsections", {}).get("unassigned", [])
    total_unassigned = len(unassigned_works)

    result = {
        "project": hierarchy.get("project", "unknown"),
        "version": "1.0",
        "stats": {
            "total_phases": len(phases_result),
            "total_subsections": sum(p["subsections_count"] for p in phases_result),
            "total_work_items": total_works,
            "unassigned_count": total_unassigned,
            "assignment_rate": f"{total_works / (total_works + total_unassigned) * 100:.1f}%" if (total_works + total_unassigned) > 0 else "0%"
        },
        "phases": phases_result,
        "unassigned_work_items": unassigned_works
    }

    print(f"  Фаз:          {result['stats']['total_phases']}")
    print(f"  Подразделов:  {result['stats']['total_subsections']}")
    print(f"  Привязано:    {total_works}")
    print(f"  Unassigned:   {total_unassigned}")
    print(f"  Привязка:     {result['stats']['assignment_rate']}")

    save_json(result, ASSIGNMENT_FILE)
    print(f"\n  ✅ Этап B завершён!")
    return result


# ═══════════════════════════════════════════════════════════════
# ЭТАП C: СВОДКА ПО ФАЗАМ
# ═══════════════════════════════════════════════════════════════
def step_c_volume_summary(assignment: Dict) -> Dict:
    """
    Строит читаемую сводку объёмов по фазам.
    Основа для расчёта длительностей и ГПР.
    """
    print("\n" + "="*60)
    print("ЭТАП C: СВОДКА ОБЪЁМОВ")
    print("="*60)

    phases_summary = []
    for phase in assignment.get("phases", []):
        phase_name = phase.get("phase", "")
        work_count = phase.get("work_items_count", 0)
        volumes = phase.get("volumes", {})

        # Основная единица объёма (самый большой объём)
        main_volume = None
        main_unit = None
        if volumes:
            main_unit = max(volumes, key=volumes.get)
            main_volume = volumes[main_unit]

        phases_summary.append({
            "phase": phase_name,
            "work_items_count": work_count,
            "main_volume": main_volume,
            "main_unit": main_unit,
            "all_volumes": volumes,
            "subsections": [
                {
                    "name": s["name"],
                    "work_items_count": s["work_items_count"],
                    "volumes": s["volumes"]
                }
                for s in phase.get("subsections", [])
                if s["work_items_count"] > 0
            ]
        })

        if work_count > 0:
            vol_str = f"{main_volume:.1f} {main_unit}" if main_volume else "—"
            print(f"  {phase_name}: {work_count} работ, {vol_str}")

    summary = {
        "project": assignment.get("project", ""),
        "version": "1.0",
        "stats": assignment.get("stats", {}),
        "phases_summary": phases_summary,
        "note": "Основа для расчёта длительностей и построения ГПР"
    }

    save_json(summary, VOLUME_SUMMARY_FILE)
    print(f"\n  ✅ Этап C завершён!")
    return summary


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="AINTELLECTUM Work Assignment Engine v1.0")
    parser.add_argument("--step", choices=["A", "B", "C", "all"], default="all")
    parser.add_argument("--test", type=int, default=None, help="Тест: N работ")
    args = parser.parse_args()

    print("=" * 60)
    print("WORK ASSIGNMENT ENGINE v1.0 - AINTELLECTUM")
    print("Архитектура: Аян | Разработка: Claude | Капитан: Ереке")
    print("=" * 60)
    print()

    # Загружаем данные
    hierarchy = load_json(HIERARCHY_FILE)
    smeta = load_json(SMETA_AI_FILE)

    if not hierarchy:
        print(f"❌ Не найден {HIERARCHY_FILE}")
        print("   Сначала запусти hierarchy_builder.py!")
        return

    if not smeta:
        print(f"❌ Не найден {SMETA_AI_FILE}")
        return

    # Извлекаем работы
    works = extract_works_from_smeta(smeta)
    phases_count = len(hierarchy.get("phases", []))
    subsections_count = sum(
        len(p.get("subsections", []))
        for p in hierarchy.get("phases", [])
    )

    print(f"Проект:      {hierarchy.get('project', 'unknown')}")
    print(f"Работ:       {len(works)}")
    print(f"Фаз:         {phases_count}")
    print(f"Подразделов: {subsections_count}")
    if args.test:
        print(f"Тест режим:  {args.test} работ")
    print()

    # Инициализируем клиент
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY не найден в .env!")
        return

    client = anthropic.Anthropic(api_key=api_key)
    assignments = []
    assignment = None

    # ── ЭТАП A ──
    if args.step in ("A", "all"):
        assignments = step_a_assign_works(client, works, hierarchy, args.test)

    # ── ЭТАП B ──
    if args.step in ("B", "all"):
        if not assignments:
            existing = load_json(BATCHES_FILE)
            if existing:
                assignments = existing.get("assignments", [])
            else:
                print(f"❌ Нет данных для этапа B. Запусти --step A сначала.")
                return
        assignment = step_b_aggregate(assignments, hierarchy)

    # ── ЭТАП C ──
    if args.step in ("C", "all"):
        if not assignment:
            assignment = load_json(ASSIGNMENT_FILE)
        if assignment:
            step_c_volume_summary(assignment)
        else:
            print(f"❌ Нет данных для этапа C. Запусти --step B сначала.")
            return

    # ── ИТОГ ──
    print()
    print("=" * 60)
    print("🏆 WORK ASSIGNMENT ENGINE v1.0 ЗАВЕРШЁН!")
    print("=" * 60)
    print()
    print("📁 Файлы:")
    print(f"  - {BATCHES_FILE:<35} (сырые результаты батчей)")
    print(f"  - {ASSIGNMENT_FILE:<35} (полная иерархия с работами)")
    print(f"  - {VOLUME_SUMMARY_FILE:<35} (сводка объёмов → основа ГПР)")
    print()
    print("🚀 Следующий шаг: Duration Engine → ГПР!")


if __name__ == "__main__":
    main()