# -*- coding: utf-8 -*-
"""
Диагностика: проверяем что реально возвращает API
"""
import os
import json
import re
from dotenv import load_dotenv
import anthropic

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Простой тест — просим вернуть JSON
prompt = """Верни ТОЛЬКО этот JSON без пояснений и без markdown:
{"test": "ok", "number": 42}"""

print("Отправляю тест в API...")
message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=200,
    messages=[{"role": "user", "content": prompt}]
)

text = message.content[0].text
print(f"\nТип ответа: {type(text)}")
print(f"Длина: {len(text)}")
print(f"Первые 200 символов:")
print(repr(text[:200]))
print()
print("Содержимое:")
print(text[:200])
print()

# Пробуем распарсить
try:
    result = json.loads(text)
    print(f"✅ JSON распарсился напрямую: {result}")
except Exception as e:
    print(f"❌ Прямой парсинг не сработал: {e}")
    
    # Чистим markdown
    cleaned = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'```\s*', '', cleaned).strip()
    print(f"После очистки: {repr(cleaned[:200])}")
    
    try:
        result = json.loads(cleaned)
        print(f"✅ После очистки распарсился: {result}")
    except Exception as e2:
        print(f"❌ После очистки тоже не сработало: {e2}")
        
        # Ищем от { до }
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1:
            fragment = cleaned[start:end+1]
            print(f"Фрагмент JSON: {repr(fragment[:200])}")
            try:
                result = json.loads(fragment)
                print(f"✅ Фрагмент распарсился: {result}")
            except Exception as e3:
                print(f"❌ Фрагмент тоже не работает: {e3}")

print("\nГотово!")