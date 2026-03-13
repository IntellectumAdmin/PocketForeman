# -*- coding: utf-8 -*-
"""
Пример использования Schedule Agent
INTELLECTUM - модульная AI-система
"""
# Загружаем переменные окружения
from dotenv import load_dotenv
from pathlib import Path

# Путь к .env (в корне Python_Start)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

import os
import json

# Импортируем Schedule Agent
from analytics_ai.schedule import ScheduleAgent


def example_1_basic_usage():
    """
    Пример 1: Базовое использование (Claude)
    """
    print("=" * 60)
    print("ПРИМЕР 1: Базовый анализ сметы через Claude")
    print("=" * 60)
    
    # Создаём агента (по умолчанию Claude)
    agent = ScheduleAgent(provider="claude")
    
    # Путь к смете
    smeta_path = "analytics_ai/data/8._локальные.pdf"
    
    if not Path(smeta_path).exists():
        print(f"⚠️ Файл не найден: {smeta_path}")
        return
    
    # Анализируем смету
    print(f"\n📄 Анализирую смету: {smeta_path}")
    result = agent.analyze_smeta(smeta_path)
    
    # Показываем результат
    print("\n✅ РЕЗУЛЬТАТ:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def example_2_extract_structure_only():
    """
    Пример 2: Быстрое извлечение только структуры
    """
    print("\n" + "=" * 60)
    print("ПРИМЕР 2: Извлечение структуры (быстрый режим)")
    print("=" * 60)
    
    agent = ScheduleAgent(provider="claude")
    smeta_path = "analytics_ai/data/8._локальные.pdf"
    
    if not Path(smeta_path).exists():
        print(f"⚠️ Файл не найден: {smeta_path}")
        return
    
    # Извлекаем только структуру
    print(f"\n🌳 Извлекаю структуру из: {smeta_path}")
    structure = agent.extract_structure(smeta_path)
    
    # Показываем дерево
    print(f"\n✅ Найдено разделов: {len(structure)}\n")
    for item in structure[:10]:  # Первые 10
        indent = "  " * item["level"]
        print(f"{indent}{item['name']}")
    
    if len(structure) > 10:
        print(f"... и ещё {len(structure) - 10} разделов")


def example_3_build_schedule():
    """
    Пример 3: Построение полного ГПР
    """
    print("\n" + "=" * 60)
    print("ПРИМЕР 3: Построение графика производства работ")
    print("=" * 60)
    
    agent = ScheduleAgent(provider="claude")
    smeta_path = "analytics_ai/data/8._локальные.pdf"
    
    if not Path(smeta_path).exists():
        print(f"⚠️ Файл не найден: {smeta_path}")
        return
    
    # Шаг 1: Анализ сметы
    print("\n📄 Шаг 1: Анализ сметы...")
    smeta_data = agent.analyze_smeta(smeta_path)
    
    # Шаг 2: Построение ГПР
    print("\n📊 Шаг 2: Строю график работ...")
    schedule = agent.build_schedule(
        smeta_data,
        start_date="2024-05-01"
    )
    
    # Показываем результат
    print("\n✅ ГРАФИК ПОСТРОЕН:")
    print(f"Общая длительность: {schedule.get('duration', '?')} дней")
    print(f"Критический путь: {schedule.get('critical_path', [])}")


def example_4_with_fallback():
    """
    Пример 4: Режим fallback (отказоустойчивость)
    """
    print("\n" + "=" * 60)
    print("ПРИМЕР 4: Fallback между провайдерами")
    print("=" * 60)
    
    # Создаём агента с включённым fallback
    agent = ScheduleAgent(
        provider="claude",
        fallback=True  # Если Claude упадёт → попробует GPT-4 → Gemini
    )
    
    smeta_path = "analytics_ai/data/8._локальные.pdf"
    
    if not Path(smeta_path).exists():
        print(f"⚠️ Файл не найден: {smeta_path}")
        return
    
    # Анализируем (с автоматическим fallback при ошибках)
    print("\n📄 Анализирую с fallback...")
    try:
        result = agent.analyze_smeta(smeta_path)
        print(f"\n✅ Успешно! Использован провайдер: {agent.provider_name}")
    except Exception as e:
        print(f"\n❌ Все провайдеры недоступны: {e}")


def example_5_provider_info():
    """
    Пример 5: Информация о провайдере
    """
    print("\n" + "=" * 60)
    print("ПРИМЕР 5: Информация о провайдере")
    print("=" * 60)
    
    agent = ScheduleAgent(provider="claude")
    
    info = agent.get_provider_info()
    print("\n📊 ИНФОРМАЦИЯ О ПРОВАЙДЕРЕ:")
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    """
    Запуск примеров
    
    Использование:
        python analytics/example_usage.py
    
    Перед запуском убедись:
    1. Установлен anthropic: pip install anthropic
    2. В .env есть: ANTHROPIC_API_KEY=sk-ant-...
    3. Есть файл сметы: analytics_ai/data/8._локальные.pdf
    """
    
    print("\n🚀 INTELLECTUM Schedule Agent - Примеры использования\n")
    
    # Проверяем API-ключ
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ ОШИБКА: Не найден ANTHROPIC_API_KEY в .env")
        print("\nДобавь в файл .env:")
        print("ANTHROPIC_API_KEY=sk-ant-...")
        exit(1)
    
    # Запускаем примеры
    try:
        # Выбери нужный пример:
        
        # example_1_basic_usage()              # Базовый анализ
        example_2_extract_structure_only()   # Быстрое извлечение структуры
        # example_3_build_schedule()           # Полный ГПР
        # example_4_with_fallback()            # Fallback
        # example_5_provider_info()            # Информация
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
