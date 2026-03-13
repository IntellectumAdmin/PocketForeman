# -*- coding: utf-8 -*-
"""
Базовый класс для AI-провайдеров
Обеспечивает единый интерфейс для разных AI-моделей
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class AIProvider(ABC):
    """
    Абстрактный базовый класс для всех AI-провайдеров.
    
    Каждый провайдер (Claude, GPT-4, Gemini) должен реализовать:
    1. analyze_smeta() - анализ сметы
    2. build_schedule() - построение ГПР
    3. extract_structure() - извлечение структуры разделов
    """
    
    def __init__(self, api_key: str, **kwargs):
        """
        Инициализация провайдера
        
        Args:
            api_key: API-ключ для доступа к AI
            **kwargs: Дополнительные параметры (model_name, timeout и т.д.)
        """
        self.api_key = api_key
        self.config = kwargs
    
    @abstractmethod
    def analyze_smeta(self, pdf_path: str, **kwargs) -> Dict[str, Any]:
        """
        Анализирует смету и извлекает:
        - Структуру разделов
        - Объёмы работ
        - Виды работ
        - Единицы измерения
        
        Args:
            pdf_path: Путь к PDF-файлу сметы
            **kwargs: Дополнительные параметры
        
        Returns:
            {
                "structure": [...],  # Дерево разделов
                "volumes": {...},    # Объёмы работ
                "works": [...]       # Виды работ
            }
        """
        pass
    
    @abstractmethod
    def build_schedule(
        self, 
        smeta_data: Dict[str, Any],
        start_date: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Строит график производства работ (ГПР)
        
        Args:
            smeta_data: Данные из analyze_smeta()
            start_date: Дата начала строительства (формат: YYYY-MM-DD)
            **kwargs: Дополнительные параметры
        
        Returns:
            {
                "schedule": [...],   # График работ с датами
                "duration": 280,     # Общая длительность (дней)
                "critical_path": [...] # Критический путь
            }
        """
        pass
    
    @abstractmethod
    def extract_structure(self, pdf_path: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Извлекает только структуру разделов (без объёмов)
        
        Args:
            pdf_path: Путь к PDF-файлу сметы
            **kwargs: Дополнительные параметры
        
        Returns:
            [
                {"level": 0, "name": "Здание школы"},
                {"level": 1, "name": "Земляные работы"},
                ...
            ]
        """
        pass
    
    def get_provider_name(self) -> str:
        """Возвращает название провайдера"""
        return self.__class__.__name__.replace("Provider", "")
    
    def is_available(self) -> bool:
        """
        Проверяет доступность провайдера
        
        Returns:
            True если провайдер доступен, иначе False
        """
        try:
            # Простая проверка - есть ли API-ключ
            return bool(self.api_key and len(self.api_key) > 10)
        except Exception:
            return False
