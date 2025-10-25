import os, sys, json, requests, time
from datetime import datetime

# ==== НАСТРОЙКА ИМЁН СВОЙСТВ В ТВОЕЙ БАЗЕ ====
TITLE_PROP      = "ID (текст)"          # Это Title-колонка (левая первая)
NAME_TEXT_PROP  = "Название задачи"     # Обычный Text
STATUS_PROP     = "Статус"              # Status
DEADLINE_PROP   = "Срок ( Deadline)"    # Date (обрати внимание на пробел)
SOURCE_PROP     = "Источник (Source)"   # Select (не используется здесь)

# ==== Русско-английские алиасы статусов ====
STATUS_ALIASES = {
    "не начато": "Not started",
    "не начата": "Not started",
    "not started": "Not started",
    "в работе": "In progress",
    "в процессе": "In progress",
    "in progress": "In progress",
    "сделано": "Done",
    "готово": "Done",
    "done": "Done",
}
def norm_status(s: str) -> str:
    if not s:
        return "Not started"
    return STATUS_ALIASES.get(s.strip().lower(), s)

# ==== БАЗОВОЕ ====
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_TASKS_DB")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def get_database_schema():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def get_allowed_statuses():
    try:
        db = get_database_schema()
        prop = db["properties"][STATUS_PROP]
        options = prop["status"]["options"]
        return [o["name"] for o in options]
    except Exception:
        return None  # если не получилось — не будем валиться

def find_pages_by_name_contains(substr):
    """Ищем по подстроке в 'Название задачи' (Text). Возвращаем список страниц."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": NAME_TEXT_PROP,
            "rich_text": {"contains": substr}
        },
        "page_size": 10,
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]
    }
    r = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])

def update_status(page_id, new_status):
    payload = {
        "properties": {
            STATUS_PROP: {"status": {"name": new_status}}
        }
    }
    url = f"https://api.notion.com/v1/pages/{page_id}"
    r = requests.patch(url, headers=HEADERS, data=json.dumps(payload), timeout=30)
    if r.status_code in (200, 204):
        return True, {}
    return False, {"code": r.status_code, "body": r.text[:400]}

def main():
    if len(sys.argv) < 3:
        print("Использование:\n  python notion_update_status.py \"Подстрока в названии\" \"Новый статус\"")
        allowed = get_allowed_statuses()
        if allowed:
            print("Разрешённые статусы:", ", ".join(allowed))
        return

    name_substr = sys.argv[1]
    new_status  = norm_status(sys.argv[2])

    allowed = get_allowed_statuses()
    if allowed and new_status not in allowed:
        print(f"Статус «{new_status}» не найден. Разрешено: {', '.join(allowed)}")
        return

    pages = find_pages_by_name_contains(name_substr)
    if not pages:
        print("Не нашли задач по подстроке:", name_substr)
        return

    page = pages[0]
    ok, info = update_status(page["id"], new_status)
    title_show = None
    try:
        title_show = page["properties"][NAME_TEXT_PROP]["rich_text"][0]["plain_text"]
    except Exception:
        title_show = "(без названия)"

    if ok:
        print(f"✅ Статус обновлён: «{title_show}» → {new_status} (page_id={page['id']})")
    else:
        print("❌ Не удалось обновить статус:", info)

if __name__ == "__main__":
    main()
