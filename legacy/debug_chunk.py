# -*- coding: utf-8 -*-
"""
Дебаг: смотрим точно что возвращает API для чанка 1
"""
import os
import json
import re
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Загружаем чанк 1
with open("smeta_chunk_001.json", "r", encoding="utf-8") as f:
    chunk = json.load(f)

# Берём первые 20 записей для теста (не все 325)
records = chunk.get("records", [])[:20]
lines = []
for r in records:
    t = r.get("t")
    if t == "s":
        lines.append(f'[РАЗДЕЛ] raw="{r.get("raw","")}" norm="{r.get("norm","")}"')
    elif t == "cs":
        lines.append(f'[КОНТЕКСТ] raw="{r.get("raw","")}"')
    elif t == "w":
        lines.append(f'[РАБОТА] name="{r.get("n","")}" unit={r.get("u","")} v={r.get("v","")}')

compact = "\n".join(lines)

prompt = f"""Верни ТОЛЬКО JSON без markdown блоков, без пояснений.

Данные фрагмента строительной сметы:
{compact}

Верни JSON в точно таком формате:
{{
  "chunk_id": 1,
  "sections": [
    {{
      "title_raw": "название раздела",
      "title_norm": "норм название",
      "level": 1,
      "children": []
    }}
  ],
  "unassigned_work_items": []
}}"""

print("Отправляю в API (20 записей из чанка 1)...")
msg = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=2000,
    messages=[{"role": "user", "content": prompt}]
)

text = msg.content[0].text
print(f"\nДлина ответа: {len(text)}")
print(f"Первые 300 символов (repr):")
print(repr(text[:300]))
print()
print("Первые 300 символов (текст):")
print(text[:300])

# Сохраняем полный ответ
with open("debug_response.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("\nПолный ответ сохранён в debug_response.txt")

# Пробуем парсить
text2 = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
text2 = re.sub(r'```\s*', '', text2).strip()

try:
    result = json.loads(text2)
    print(f"\n✅ Парсинг успешен! chunk_id={result.get('chunk_id')}, sections={len(result.get('sections',[]))}")
except Exception as e:
    print(f"\n❌ Парсинг не удался: {e}")
    start = text2.find('{')
    end = text2.rfind('}')
    if start != -1 and end != -1:
        fragment = text2[start:end+1]
        try:
            result = json.loads(fragment)
            print(f"✅ Фрагмент распарсился! sections={len(result.get('sections',[]))}")
        except Exception as e2:
            print(f"❌ Фрагмент тоже не работает: {e2}")
            print(f"Фрагмент (первые 200): {repr(fragment[:200])}")