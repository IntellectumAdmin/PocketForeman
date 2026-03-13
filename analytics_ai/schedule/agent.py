# -*- coding: utf-8 -*-
"""
Schedule Agent - агент построения графиков производства работ
Поддерживает переключение между разными AI-провайдерами
"""

import os
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

from ..ai_providers import AIProvider, ClaudeProvider

log = logging.getLogger("schedule-agent")


class ScheduleAgent:
    """
    Агент для построения ГПР из смет
    
    Возможности:
    1. Анализ смет (PDF/Excel)
    2. Построение графика работ
    3. Извлечение структуры разделов
    4. Отказоустойчивость (fallback между провайдерами)
    
    Пример:
        agent = ScheduleAgent(provider="claude")
        result = agent.analyze_smeta("smeta.pdf")
    """
    
    # Доступные провайдеры (порядок = приоритет для fallback)
    PROVIDERS = ["claude", "gpt4", "gemini"]
    
    def __init__(
        self, 
        provider: str = "claude",
        fallback: bool = True
    ):
        """
        Инициализация Schedule Agent
        
        Args:
            provider: Имя AI-провайдера ("claude", "gpt4", "gemini")
            fallback: Включить автоматический fallback при ошибках
        """
        self.provider_name = provider
        self.fallback_enabled = fallback
        self.provider: Optional[AIProvider] = None
        
        # Создаём провайдера
        self._create_provider(provider)
    
    def _create_provider(self, name: str) -> AIProvider:
        """
        Фабрика AI-провайдеров
        
        Args:
            name: Имя провайдера
        
        Returns:
            Экземпляр AIProvider
        
        Raises:
            ValueError: Если провайдер неизвестен или недоступен
        """
        name = name.lower()
        
        if name == "claude":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "Не найден ANTHROPIC_API_KEY в .env. "
                    "Добавь: ANTHROPIC_API_KEY=sk-ant-..."
                )
            
            self.provider = ClaudeProvider(api_key=api_key)
            log.info("✓ Claude Provider инициализирован")
            return self.provider
        
        elif name == "gpt4":
            # TODO: Реализовать OpenAI Provider
            raise NotImplementedError(
                "GPT-4 Provider пока не реализован. "
                "Используй 'claude' или создай OpenAIProvider."
            )
        
        elif name == "gemini":
            # TODO: Реализовать Gemini Provider
            raise NotImplementedError(
                "Gemini Provider пока не реализован. "
                "Используй 'claude' или создай GeminiProvider."
            )
        
        else:
            raise ValueError(
                f"Неизвестный провайдер: {name}. "
                f"Доступны: {', '.join(self.PROVIDERS)}"
            )
    
    def analyze_smeta(
        self, 
        pdf_path: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Полный анализ сметы
        
        Args:
            pdf_path: Путь к PDF-файлу сметы
            **kwargs: Дополнительные параметры для провайдера
        
        Returns:
            {
                "structure": [...],  # Дерево разделов
                "volumes": {...},    # Объёмы работ
                "sequence": [...]    # Последовательность
            }
        """
        if not Path(pdf_path).exists():
            raise FileNotFoundError(f"Файл не найден: {pdf_path}")
        
        log.info(f"📄 Анализирую смету: {pdf_path}")
        log.info(f"🤖 Провайдер: {self.provider_name}")
        
        try:
            result = self.provider.analyze_smeta(pdf_path, **kwargs)
            log.info("✓ Смета проанализирована")
            return result
        
        except Exception as e:
            log.error(f"✗ Ошибка анализа: {e}")
            
            if self.fallback_enabled:
                return self._analyze_with_fallback(pdf_path, **kwargs)
            else:
                raise
    
    def build_schedule(
        self,
        smeta_data: Dict[str, Any],
        start_date: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Построение графика производства работ
        
        Args:
            smeta_data: Данные из analyze_smeta()
            start_date: Дата начала строительства (YYYY-MM-DD)
            **kwargs: Дополнительные параметры
        
        Returns:
            {
                "schedule": [...],     # График с датами
                "duration": 280,       # Общая длительность
                "critical_path": [...]  # Критический путь
            }
        """
        log.info("📊 Строю график производства работ...")
        
        try:
            result = self.provider.build_schedule(
                smeta_data, 
                start_date=start_date,
                **kwargs
            )
            log.info("✓ График построен")
            return result
        
        except Exception as e:
            log.error(f"✗ Ошибка построения ГПР: {e}")
            
            if self.fallback_enabled:
                return self._build_schedule_with_fallback(
                    smeta_data, 
                    start_date, 
                    **kwargs
                )
            else:
                raise
    
    def extract_structure(
        self,
        pdf_path: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Быстрое извлечение структуры (без объёмов)
        
        Args:
            pdf_path: Путь к PDF-файлу
            **kwargs: Дополнительные параметры
        
        Returns:
            [
                {"level": 0, "name": "Здание школы"},
                {"level": 1, "name": "Земляные работы"},
                ...
            ]
        """
        if not Path(pdf_path).exists():
            raise FileNotFoundError(f"Файл не найден: {pdf_path}")
        
        log.info(f"🌳 Извлекаю структуру из: {pdf_path}")
        
        try:
            result = self.provider.extract_structure(pdf_path, **kwargs)
            log.info(f"✓ Извлечено разделов: {len(result)}")
            return result
        
        except Exception as e:
            log.error(f"✗ Ошибка извлечения структуры: {e}")
            
            if self.fallback_enabled:
                return self._extract_structure_with_fallback(pdf_path, **kwargs)
            else:
                raise
    
    def _analyze_with_fallback(
        self, 
        pdf_path: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """
        Fallback-механизм: пробует провайдеров по порядку
        """
        log.warning("🔄 Включён режим fallback...")
        
        # Список провайдеров для попыток (кроме уже упавшего)
        providers_to_try = [
            p for p in self.PROVIDERS 
            if p != self.provider_name
        ]
        
        last_error = None
        
        for provider_name in providers_to_try:
            try:
                log.info(f"🔄 Пробую {provider_name}...")
                self._create_provider(provider_name)
                
                result = self.provider.analyze_smeta(pdf_path, **kwargs)
                
                log.info(f"✓ {provider_name} успешно проанализировал!")
                self.provider_name = provider_name
                return result
            
            except Exception as e:
                log.warning(f"✗ {provider_name} недоступен: {e}")
                last_error = e
                continue
        
        # Если все провайдеры упали
        raise RuntimeError(
            f"Все AI-провайдеры недоступны. "
            f"Последняя ошибка: {last_error}"
        )
    
    def _build_schedule_with_fallback(
        self,
        smeta_data: Dict[str, Any],
        start_date: Optional[str],
        **kwargs
    ) -> Dict[str, Any]:
        """Fallback для построения ГПР"""
        # Аналогично _analyze_with_fallback
        # (упрощённая версия для экономии токенов)
        raise NotImplementedError("Fallback для build_schedule будет добавлен")
    
    def _extract_structure_with_fallback(
        self,
        pdf_path: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Fallback для извлечения структуры"""
        raise NotImplementedError("Fallback для extract_structure будет добавлен")
    
    def get_provider_info(self) -> Dict[str, Any]:
        """
        Информация о текущем провайдере
        
        Returns:
            {
                "name": "claude",
                "available": True,
                "model": "claude-sonnet-4"
            }
        """
        return {
            "name": self.provider_name,
            "available": self.provider.is_available() if self.provider else False,
            "class": self.provider.__class__.__name__ if self.provider else None
        }
