# -*- coding: utf-8 -*-
import os, json, re, requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID_SCHOOL65")
assert NOTION_TOKEN and DATABASE_ID, "Проверь .env: NOTION_TOKEN_SCHOOL65 и NOTION_DATABASE_ID_SCHOOL65"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

STRUCTURE_FILE = "structure.txt"

def sanitize_option_name(s: str) -> str:
    """
    Нормализуем имя опции Select для Notion:
    - запятые запрещены API → меняем на точку
    - приводим пробелы, обрезаем длину
    """
    s = s.replace(",", ".")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:90]  # ограничим до 90 символов на всякий случай

def iter_paths(filename):
    """Генерирует пути вида 'A / B / C' из structure.txt (2 пробела = уровень)."""
    with open(filename, "r", encoding="utf-8") as f:
        stack = []
        prev_level = 0
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or not line.endswith("/"):
                continue
            leading = len(line) - len(line.lstrip(" "))
            level = leading // 2
            name = line.strip().rstrip("/")

            if level > prev_level:
                stack.append(name)
            elif level == prev_level:
                if stack:
                    stack[-1] = name
                else:
                    stack.append(name)
            else:
                for _ in range(prev_level - level):
                    if stack:
                        stack.pop()
                if stack:
                    stack[-1] = name
                else:
                    stack.append(name)

            prev_level = level
            yield " / ".join(stack)

def get_database():
    r = requests.get(f"https://api.notion.com/v1/databases/{DATABASE_ID}", headers=HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch database: {r.status_code} {r.text}")
    return r.json()

def patch_select_options(options):
    body = {
        "properties": {
            "Раздел": {
                "select": {
                    "options": [{"name": o} for o in options]
                }
            }
        }
    }
    r = requests.patch(f"https://api.notion.com/v1/databases/{DATABASE_ID}", headers=HEADERS, data=json.dumps(body))
    if r.status_code != 200:
        raise RuntimeError(f"Failed to update select options: {r.status_code} {r.text}")

if __name__ == "__main__":
    # 1) Пути из structure.txt
    raw_paths = list(dict.fromkeys(iter_paths(STRUCTURE_FILE)))

    # 2) Санитизируем каждую часть пути и заново собираем строки
    sanitized_paths = []
    for p in raw_paths:
        parts = [sanitize_option_name(x) for x in p.split(" / ")]
        sanitized_paths.append(" / ".join(parts))
    # Уберём возможные дубликаты после нормализации, сохраним порядок
    all_paths = list(dict.fromkeys(sanitized_paths))

    # 3) Проверим свойство "Раздел"
    db = get_database()
    prop = db["properties"].get("Раздел")
    if not prop or prop.get("type") != "select":
        raise RuntimeError('В базе Notion нет поля "Раздел" типа Select. Создай его вручную в таблице.')

    # 4) Сольём существующие + новые
    current = [opt["name"] for opt in prop["select"].get("options", [])]
    merged = current + [p for p in all_paths if p not in current]

    # 5) Обновим опции
    patch_select_options(merged)
    print(f"OK, обновлено опций в поле 'Раздел': {len(merged)}")
