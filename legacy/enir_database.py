# -*- coding: utf-8 -*-
"""
База норм ЕНиР для расчёта длительности работ
(Единые нормы и расценки на строительные работы - Казахстан)
"""

from typing import Dict, Optional


# Нормы времени на выполнение работ (чел-часы на единицу объёма)
ENIR_NORMS: Dict[str, Dict] = {
    # Земляные работы
    "earth_excavation": {
        "name": "Разработка грунта экскаватором",
        "unit": "м³",
        "workers": 2,  # звено
        "hours_per_unit": 0.05,  # чел-часы на 1 м³
        "equipment": ["Экскаватор"],
    },
    "earth_backfill": {
        "name": "Обратная засыпка грунта",
        "unit": "м³",
        "workers": 4,
        "hours_per_unit": 0.08,
        "equipment": ["Бульдозер"],
    },
    
    # Бетонные работы
    "concrete_foundation": {
        "name": "Бетонирование фундаментов",
        "unit": "м³",
        "workers": 8,
        "hours_per_unit": 1.2,
        "equipment": ["Кран", "Бетононасос"],
    },
    "concrete_walls": {
        "name": "Бетонирование стен",
        "unit": "м³",
        "workers": 6,
        "hours_per_unit": 1.5,
        "equipment": ["Кран"],
    },
    
    # Кирпичная кладка
    "brickwork": {
        "name": "Кладка кирпича",
        "unit": "м³",
        "workers": 4,
        "hours_per_unit": 8.0,
        "equipment": [],
    },
    
    # Монтаж конструкций
    "steel_installation": {
        "name": "Монтаж металлоконструкций",
        "unit": "т",
        "workers": 6,
        "hours_per_unit": 12.0,
        "equipment": ["Автокран"],
    },
}


def get_norm(work_type: str) -> Optional[Dict]:
    """
    Получить норму ЕНиР по типу работы
    
    Args:
        work_type: тип работы (ключ из ENIR_NORMS)
        
    Returns:
        Словарь с нормой или None
    """
    return ENIR_NORMS.get(work_type)


def calculate_duration(work_type: str, volume: float) -> Optional[float]:
    """
    Рассчитать длительность работ в днях
    
    Args:
        work_type: тип работы
        volume: объём работ
        
    Returns:
        Длительность в днях (8-часовой рабочий день)
    """
    norm = get_norm(work_type)
    if not norm:
        return None
    
    total_hours = norm["hours_per_unit"] * volume
    workers = norm["workers"]
    
    # Делим на количество рабочих и на 8 часов в день
    days = total_hours / (workers * 8)
    
    return round(days, 1)


if __name__ == "__main__":
    # Тест
    print("Нормы ЕНиР загружены:")
    for key, norm in ENIR_NORMS.items():
        print(f"  {key}: {norm['name']}")
    
    # Пример расчёта
    volume = 1000  # м³
    days = calculate_duration("concrete_foundation", volume)
    print(f"\nБетонирование {volume} м³ фундамента: {days} дней")