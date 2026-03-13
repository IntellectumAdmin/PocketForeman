# -*- coding: utf-8 -*-
"""
Claude Provider (Anthropic)
Основной AI-провайдер для INTELLECTUM
Поддержка больших PDF через разбивку на части
"""

import base64
import io
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

from .base import AIProvider

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


class ClaudeProvider(AIProvider):
    """
    Провайдер для Claude (Anthropic API)
    
    Преимущества:
    - Лучшее качество анализа строительных документов
    - Поддержка больших PDF (до 100 страниц)
    - Понимание структуры и логики ГПР
    """
    
    def __init__(
        self, 
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 16000,
        **kwargs
    ):
        """
        Инициализация Claude Provider
        
        Args:
            api_key: Anthropic API key
            model: Модель Claude (sonnet-4 по умолчанию)
            max_tokens: Максимальная длина ответа
        """
        super().__init__(api_key, **kwargs)
        
        if not HAS_ANTHROPIC:
            raise ImportError(
                "Установи anthropic: pip install anthropic --break-system-packages"
            )
        
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
    
    def analyze_smeta(self, pdf_path: str, **kwargs) -> Dict[str, Any]:
        """
        Полный анализ сметы через Claude
        
        Извлекает:
        1. Структуру разделов (иерархия)
        2. Объёмы работ (укрупнённо)
        3. Последовательность работ
        """
        # Читаем PDF как base64
        pdf_data = self._read_pdf_as_base64(pdf_path)
        
        # Промпт для Claude
        prompt = """
Проанализируй строительную смету и верни структурированные данные.

ЗАДАЧА:
1. Извлеки дерево разделов (иерархия работ)
2. Для каждого раздела найди ОСНОВНОЙ объём работ (главная единица измерения)
3. Определи последовательность работ (что идёт за чем)

ФОРМАТ ОТВЕТА (JSON):
{
  "structure": [
    {"level": 0, "name": "Здание школы"},
    {"level": 1, "name": "Земляные работы"},
    {"level": 2, "name": "Разработка грунта"}
  ],
  "volumes": {
    "Земляные работы": {"value": 1500, "unit": "м³"},
    "Фундаменты": {"value": 1200, "unit": "м³"}
  },
  "sequence": [
    "Земляные работы",
    "Фундаменты",
    "Конструкции ж/б выше 0.000"
  ]
}

Анализируй смету:
"""
        
        # Запрос к Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        # Парсим ответ
        result = self._parse_response(response)
        return result
    
    def build_schedule(
        self, 
        smeta_data: Dict[str, Any],
        start_date: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Строит ГПР на основе данных сметы
        """
        prompt = f"""
Построй график производства работ (ГПР) на основе данных:

СТРУКТУРА РАБОТ:
{smeta_data.get('structure', [])}

ОБЪЁМЫ:
{smeta_data.get('volumes', {})}

ПОСЛЕДОВАТЕЛЬНОСТЬ:
{smeta_data.get('sequence', [])}

ДАТА НАЧАЛА: {start_date or "не указана"}

ЗАДАЧА:
1. Определи длительность каждого раздела (используй строительные нормы)
2. Построй последовательность с учётом зависимостей
3. Найди критический путь

ФОРМАТ ОТВЕТА (JSON):
{{
  "schedule": [
    {{
      "section": "Земляные работы",
      "start": "2024-05-01",
      "end": "2024-05-31",
      "duration_days": 30
    }}
  ],
  "duration": 280,
  "critical_path": ["Фундаменты", "Колонны", "Перекрытия"]
}}
"""
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        return self._parse_response(response)
    
    def extract_structure(self, pdf_path: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Извлекает только структуру разделов (без объёмов)
        
        ПОДДЕРЖКА БОЛЬШИХ PDF:
        - Если PDF < 20 страниц → обрабатывает целиком
        - Если PDF > 20 страниц → разбивает на части и объединяет результаты
        
        Args:
            pdf_path: Путь к PDF-файлу
            **kwargs: Дополнительные параметры
                chunk_size: Размер части в страницах (по умолчанию 20)
        
        Returns:
            [
                {"level": 0, "name": "Здание школы"},
                {"level": 1, "name": "Земляные работы"},
                ...
            ]
        """
        chunk_size = kwargs.get('chunk_size', 20)
        
        # Проверяем размер PDF
        try:
            page_count = self._get_pdf_page_count(pdf_path)
        except Exception as e:
            print(f"⚠️ Не удалось подсчитать страницы: {e}")
            print("📄 Обрабатываю как обычный PDF...")
            page_count = 0
        
        # Если PDF маленький (или не удалось подсчитать) → обычный способ
        if page_count == 0 or page_count <= 20:
            print(f"📄 PDF содержит {page_count} страниц (обрабатываю целиком)")
            return self._extract_structure_simple(pdf_path)
        
        # Если PDF большой → разбиваем на части
        print(f"📄 PDF содержит {page_count} страниц (требуется разбивка)")
        
        # Разбиваем на части
        chunks = self._split_pdf_to_chunks(pdf_path, chunk_size=chunk_size)
        
        # Анализируем каждую часть
        all_structures = []
        import time

        for i, chunk_bytes in enumerate(chunks, 1):
            try:
                structure = self._extract_structure_from_chunk(chunk_bytes, i)
                all_structures.append(structure)
        
                # Пауза между запросами (избегаем rate limit)
                if i < len(chunks):  # Не ждём после последней части
                    print(f"  ⏳ Пауза 90 сек (rate limit)...")
                    time.sleep(90)
            
            except Exception as e:
                print(f"  ✗ Ошибка в части {i}: {e}")
                continue
        
        # Объединяем результаты
        merged = self._merge_structures(all_structures)
        
        return merged
    
    def _extract_structure_simple(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Простое извлечение структуры (для PDF < 20 страниц)
        Старый метод extract_structure
        """
        pdf_data = self._read_pdf_as_base64(pdf_path)
        
        prompt = """
Извлеки ТОЛЬКО структуру разделов из сметы (дерево работ).

ФОРМАТ ОТВЕТА (JSON):
[
  {"level": 0, "name": "Здание школы"},
  {"level": 1, "name": "Земляные работы"},
  {"level": 2, "name": "Котлован"}
]

Уровень 0 - главные объекты
Уровень 1 - основные разделы
Уровень 2 - подразделы

Анализируй смету:
"""
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        result = self._parse_response(response)
        return result if isinstance(result, list) else result.get("structure", [])
    
    def _read_pdf_as_base64(self, pdf_path: str) -> str:
        """Читает PDF и конвертирует в base64"""
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        return base64.standard_b64encode(pdf_bytes).decode('utf-8')
    
    def _parse_response(self, response) -> Any:
        """
        Парсит ответ Claude и извлекает JSON
        """
        import json
        import re
        
        # Берём текст из ответа
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        
        # Убираем markdown-обёртки (```json ... ```)
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()
        
        # Парсим JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Если не удалось распарсить - возвращаем как текст
            return {"raw_text": text}
    
    def _get_pdf_page_count(self, pdf_path: str) -> int:
        """
        Подсчитывает количество страниц в PDF
        
        Returns:
            Количество страниц
        """
        if not HAS_PYPDF:
            raise ImportError(
                "Установи PyPDF2: pip install PyPDF2 --break-system-packages"
            )
        
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    
    def _split_pdf_to_chunks(
        self, 
        pdf_path: str, 
        chunk_size: int = 80
    ) -> List[bytes]:
        """
        Разбивает большой PDF на части (chunks)
        
        Args:
            pdf_path: Путь к PDF
            chunk_size: Размер части в страницах (макс 80 для API)
        
        Returns:
            Список PDF-файлов в виде bytes
        """
        if not HAS_PYPDF:
            raise ImportError(
                "Установи PyPDF2: pip install PyPDF2 --break-system-packages"
            )
        
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        chunks = []
        
        print(f"📄 PDF содержит {total_pages} страниц")
        print(f"📦 Разбиваю на части по {chunk_size} страниц...")
        
        # Разбиваем на части
        for start_page in range(0, total_pages, chunk_size):
            end_page = min(start_page + chunk_size, total_pages)
            
            # Создаём новый PDF с частью страниц
            writer = PdfWriter()
            for page_num in range(start_page, end_page):
                writer.add_page(reader.pages[page_num])
            
            # Сохраняем в bytes
            output = io.BytesIO()
            writer.write(output)
            output.seek(0)
            chunk_bytes = output.read()
            
            chunks.append(chunk_bytes)
            print(f"  ✓ Часть {len(chunks)}: страницы {start_page+1}-{end_page}")
        
        return chunks
    
    def _extract_structure_from_chunk(
        self, 
        chunk_bytes: bytes, 
        chunk_num: int
    ) -> List[Dict[str, Any]]:
        """
        Извлекает структуру из одной части PDF
        
        Args:
            chunk_bytes: PDF в виде bytes
            chunk_num: Номер части (для логирования)
        
        Returns:
            Список разделов
        """
        print(f"🤖 Анализирую часть {chunk_num}...")
        
        # Конвертируем в base64
        pdf_data = base64.standard_b64encode(chunk_bytes).decode('utf-8')
        
        prompt = """
Извлеки ТОЛЬКО структуру разделов из сметы (дерево работ).

ФОРМАТ ОТВЕТА (JSON):
[
  {"level": 0, "name": "Здание школы"},
  {"level": 1, "name": "Земляные работы"},
  {"level": 2, "name": "Котлован"}
]

Уровень 0 - главные объекты
Уровень 1 - основные разделы
Уровень 2 - подразделы

Анализируй смету:
"""
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        result = self._parse_response(response)
        structure = result if isinstance(result, list) else result.get("structure", [])
        
        print(f"  ✓ Извлечено разделов: {len(structure)}")
        return structure
    
    def _merge_structures(
        self, 
        structures: List[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Объединяет структуры из разных частей PDF
        Удаляет дубли
        
        Args:
            structures: Список структур из разных частей
        
        Returns:
            Объединённая структура без дублей
        """
        print("🔗 Объединяю результаты...")
        
        seen: Set[str] = set()
        merged = []
        
        for structure in structures:
            for item in structure:
                # Уникальный ключ: уровень + имя
                key = f"{item['level']}:{item['name']}"
                
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
        
        print(f"✅ Итого разделов: {len(merged)} (убрано дублей: {sum(len(s) for s in structures) - len(merged)})")
        return merged
    
    def is_available(self) -> bool:
        """Проверка доступности Claude API"""
        if not super().is_available():
            return False
        
        try:
            # Простой тестовый запрос
            self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "test"}]
            )
            return True
        except Exception:
            return False
