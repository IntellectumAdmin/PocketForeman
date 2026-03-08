# -*- coding: utf-8 -*-
"""
Пример использования модуля Analytics
Тестовый скрипт для проверки работы всех компонентов
"""

from parsers.smeta_parser import parse_pdf_smeta
from parsers.enir_database import get_norm, calculate_duration
from schedule.builder import build_schedule
from visualization.charts import create_plan_fact_chart, save_chart_html


def main():
    print("=" * 50)
    print("📊 INTELLECTUM Analytics - Тест")
    print("=" * 50)
    
    # 1. Парсим смету (пока тестовые данные)
    print("\n1️⃣ Парсинг сметы...")
    works = parse_pdf_smeta("test.pdf")
    print(f"   Найдено работ: {len(works)}")
    for w in works:
        print(f"   - {w['code']}: {w['name']} ({w['volume']} {w['unit']})")
    
    # 2. Проверяем нормы ЕНиР
    print("\n2️⃣ Нормы ЕНиР...")
    norm = get_norm("concrete_foundation")
    if norm:
        print(f"   {norm['name']}: {norm['hours_per_unit']} ч/ед")
    
    days = calculate_duration("concrete_foundation", 1000)
    print(f"   Бетонирование 1000 м³: {days} дней")
    
    # 3. Строим график
    print("\n3️⃣ Построение графика...")
    schedule = build_schedule(works, "2025-12-01")
    print(f"   График построен: {len(schedule)} работ")
    for item in schedule[:3]:  # первые 3
        print(f"   - {item['name']}: {item['start_date']} → {item['end_date']}")
    
    # 4. Создаём график (пока HTML-заглушка)
    print("\n4️⃣ Создание графика План vs Факт...")
    html = create_plan_fact_chart(schedule, [])
    save_chart_html(html, "график_план_факт.html")
    
    print("\n" + "=" * 50)
    print("✅ Тест завершён успешно!")
    print("=" * 50)


if __name__ == "__main__":
    main()