import os, json, requests
from datetime import date

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_TASKS_DB")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def get_title_key(db_props):
    """Находит ключ колонки с типом title (на случай, если она не 'Название задачи')."""
    for k, v in db_props.items():
        if v.get("type") == "title":
            return k
    return None

def fetch_db_properties():
    r = requests.get(f"https://api.notion.com/v1/databases/{DATABASE_ID}", headers=HEADERS)
    r.raise_for_status()
    return r.json()["properties"]

DB_PROPS = fetch_db_properties()
TITLE_KEY = get_title_key(DB_PROPS) or "Name"

# Подстрой названия полей под свою таблицу (смотри шапку в Notion):
FIELD_STATUS   = "Статус"
FIELD_DEADLINE = "Срок ( Deadline)"
FIELD_PRIORITY = "Приоритет"
FIELD_OWNER    = "Владелец (Owner)"
FIELD_SOURCE   = "Источник (Source)"
FIELD_SIZE     = "Сложность (Size)"
FIELD_IDTXT    = "ID (текст)"   # если хочешь хранить код задачи (B1, INTEL-001)

def create_task(
    title: str,
    status: str = "Planned",
    deadline_iso: str | None = None,     # "2025-09-30"
    priority: str | None = None,         # "P1"/"P2"/"P3"
    owner_name: str | None = None,       # у People-колонки нужен user_id; для простоты можно завести Text-колонку OwnerName
    source: str | None = None,
    size: str | None = None,
    id_text: str | None = None,
):
    props = {
        TITLE_KEY: {"title": [{"text": {"content": title}}]}
    }

    if FIELD_STATUS in DB_PROPS and status:
        props[FIELD_STATUS] = {"select": {"name": status}}

    if FIELD_DEADLINE in DB_PROPS and deadline_iso:
        props[FIELD_DEADLINE] = {"date": {"start": deadline_iso}}

    if FIELD_PRIORITY in DB_PROPS and priority:
        props[FIELD_PRIORITY] = {"select": {"name": priority}}

    # В твоей базе поле Owner — People. Для установки People через API нужен user_id из Notion.
    # Пока пропустим, либо заведи доп. колонку "OwnerName (Text)" и используй её.
    # if FIELD_OWNER in DB_PROPS and some_user_id:
    #     props[FIELD_OWNER] = {"people": [{"id": some_user_id}]}

    if FIELD_SOURCE in DB_PROPS and source:
        props[FIELD_SOURCE] = {"rich_text": [{"text": {"content": source}}]}

    if FIELD_SIZE in DB_PROPS and size:
        props[FIELD_SIZE] = {"select": {"name": size}}

    if FIELD_IDTXT in DB_PROPS and id_text:
        props[FIELD_IDTXT] = {"rich_text": [{"text": {"content": id_text}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, data=json.dumps(payload))
    if r.status_code in (200, 201):
        page = r.json()
        print("✅ Создано:", title, "| page_id:", page["id"])
        return page["id"]
    print("❌ Ошибка:", r.status_code, r.text[:300])
    return None

# Пример вызова:
if __name__ == "__main__":
    create_task(
        title="Проверить связку Notion ↔ Python",
        status="Planned",
        deadline_iso=str(date.today()),
        priority="P2",
        source="скрипт теста",
        size="S",
        id_text="DEV-TEST-001",
    )
