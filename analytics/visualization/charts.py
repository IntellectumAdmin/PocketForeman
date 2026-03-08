# -*- coding: utf-8 -*-
"""
Создание интерактивных графиков План vs Факт
"""

from typing import List, Dict, Any


def create_plan_fact_chart(schedule: List[Dict], fact_data: List[Dict]) -> str:
    """
    Создаёт график план vs факт
    
    Args:
        schedule: плановый график работ
        fact_data: фактические данные из ЖПР
        
    Returns:
        HTML-код графика (Plotly)
    """
    
    # TODO: Реализовать через Plotly
    # Пока возвращаем заглушку
    
    html = """
    <html>
    <head>
        <title>График План vs Факт</title>
    </head>
    <body>
        <h1>📊 График производства работ</h1>
        <p>План vs Факт (TODO: интеграция Plotly)</p>
    </body>
    </html>
    """
    
    return html


def save_chart_html(html: str, filename: str = "chart.html"):
    """
    Сохраняет график в HTML-файл
    
    Args:
        html: HTML-код графика
        filename: имя файла для сохранения
    """
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"График сохранён: {filename}")


if __name__ == "__main__":
    # Тест
    schedule = [{"name": "Работа 1", "days": 10}]
    fact = [{"name": "Работа 1", "days": 8}]
    
    html = create_plan_fact_chart(schedule, fact)
    save_chart_html(html, "test_chart.html")