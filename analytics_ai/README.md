# 🤖 INTELLECTUM Schedule Agent

Модульная AI-система для анализа смет и построения графиков производства работ.

## ✨ Возможности

- ✅ **Анализ смет** (PDF/Excel)
- ✅ **Построение ГПР** с датами и зависимостями
- ✅ **Извлечение структуры** разделов
- ✅ **Мультипровайдерная архитектура** (Claude, GPT-4, Gemini)
- ✅ **Отказоустойчивость** (автоматический fallback)

---

## 📁 Структура проекта

```
analytics_ai/
├── ai_providers/              # AI-провайдеры
│   ├── __init__.py
│   ├── base.py               # Абстрактный базовый класс
│   └── claude_provider.py    # Реализация для Claude
│
├── schedule/                  # Schedule Agent
│   ├── __init__.py
│   └── agent.py              # Главный агент
│
├── example_usage.py           # Примеры использования
└── README.md                  # Документация
```

---

## 🚀 Установка

### 1. Установи зависимости

```bash
pip install anthropic --break-system-packages
```

### 2. Настрой API-ключи

Создай файл `.env` в корне проекта:

```env
# Claude (Anthropic) - основной провайдер
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI (резервный) - пока не используется
OPENAI_API_KEY=sk-...

# Google Gemini (резервный) - пока не используется
GOOGLE_API_KEY=...
```

---

## 💡 Использование

### Базовый пример

```python
from analytics_ai.schedule import ScheduleAgent

# Создаём агента
agent = ScheduleAgent(provider="claude")

# Анализируем смету
result = agent.analyze_smeta("smeta.pdf")

print(result)
# {
#   "structure": [...],  # Дерево разделов
#   "volumes": {...},    # Объёмы работ
#   "sequence": [...]    # Последовательность
# }
```

### Извлечение структуры

```python
# Быстрое извлечение только структуры (без объёмов)
structure = agent.extract_structure("smeta.pdf")

for item in structure:
    indent = "  " * item["level"]
    print(f"{indent}{item['name']}")
```

### Построение ГПР

```python
# Шаг 1: Анализ сметы
smeta_data = agent.analyze_smeta("smeta.pdf")

# Шаг 2: Построение графика
schedule = agent.build_schedule(
    smeta_data,
    start_date="2024-05-01"
)

print(f"Длительность: {schedule['duration']} дней")
print(f"Критический путь: {schedule['critical_path']}")
```

### Fallback (отказоустойчивость)

```python
# Создаём агента с fallback
agent = ScheduleAgent(
    provider="claude",
    fallback=True  # Если Claude упадёт → попробует другие
)

result = agent.analyze_smeta("smeta.pdf")
# Если Claude недоступен → автоматически попробует GPT-4 → Gemini
```

---

## 🔧 Архитектура

### Абстрактный AIProvider

Все AI-провайдеры наследуются от базового класса:

```python
class AIProvider(ABC):
    @abstractmethod
    def analyze_smeta(self, pdf_path: str) -> dict:
        """Анализ сметы"""
        pass
    
    @abstractmethod
    def build_schedule(self, smeta_data: dict) -> dict:
        """Построение ГПР"""
        pass
    
    @abstractmethod
    def extract_structure(self, pdf_path: str) -> list:
        """Извлечение структуры"""
        pass
```

### Реализации провайдеров

#### Claude (Anthropic) ✅ Реализовано

```python
from analytics_ai.ai_providers import ClaudeProvider

provider = ClaudeProvider(api_key="sk-ant-...")
result = provider.analyze_smeta("smeta.pdf")
```

**Преимущества:**
- ⭐⭐⭐⭐⭐ Лучшее качество анализа
- 📄 Поддержка больших PDF (до 100 страниц)
- 🧠 Понимание строительной логики

#### GPT-4 (OpenAI) ⏳ В разработке

```python
from analytics_ai.ai_providers import OpenAIProvider

provider = OpenAIProvider(api_key="sk-...")
result = provider.analyze_smeta("smeta.pdf")
```

#### Gemini (Google) ⏳ В разработке

```python
from analytics_ai.ai_providers import GeminiProvider

provider = GeminiProvider(api_key="...")
result = provider.analyze_smeta("smeta.pdf")
```

---

## 📊 Примеры

Запусти примеры:

```bash
python analytics_ai/example_usage.py
```

Доступные примеры:
1. **Базовый анализ** - полный анализ сметы
2. **Извлечение структуры** - быстрое получение дерева разделов
3. **Построение ГПР** - график с датами
4. **Fallback** - отказоустойчивость
5. **Информация о провайдере**

---

## 🎯 Следующие шаги

### Ближайшее (1-2 недели)

- [ ] Добавить объёмы работ в ГПР
- [ ] Реализовать OpenAI Provider
- [ ] Интеграция с ЖПР-ботом

### Среднесрочное (1-2 месяца)

- [ ] Реализовать Gemini Provider
- [ ] Локальный Llama Provider (офлайн)
- [ ] Визуализация ГПР (диаграмма Ганта)

### Долгосрочное (3+ месяца)

- [ ] Парсер Excel-смет
- [ ] Сравнение план vs факт (ЖПР)
- [ ] Risk Agent (предсказание задержек)
- [ ] Веб-интерфейс для прорабов

---

## 🤝 Философия

**"Не зависеть от одного поставщика"**

INTELLECTUM построен на принципе модульности:
- Если Claude недоступен → используй GPT-4
- Если OpenAI дорогой → используй Gemini
- Если нет интернета → используй локальный Llama

**Прораб всегда должен иметь доступ к системе!**

---

## 📞 Контакты

Разработчик: Ереке (начальник участка, Казахстан)  
AI-партнёр: Claude (Anthropic)

**INTELLECTUM - Карманный прораб. Работает рядом, думает вместе, помогает всегда.**
