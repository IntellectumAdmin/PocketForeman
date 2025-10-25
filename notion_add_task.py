import os, json, requests
from datetime import date

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_TASKS_DB")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def get_db_props():
    r = requests.get(f"https://api.notion.com/v1/databases/{DATABASE_ID}", headers=HEADERS)
    r.raise_for_status()
    return r.json()["properties"]

def find_prop_keys(props):
    keys = {"title": None, "status": None, "date": None, "source": None, "xai": None}
    for k, v in props.items():
        t = v.get("type")
        if t == "title": keys["title"] = k
        if t == "status" or (t == "select" and k.lower().startswith("статус")):
            keys["status"] = (k, t)      # имя поля и тип: status/select
        if t == "date" and ("срок" in k.lower() or "deadline" in k.lower() or "дед" in k.lower()):
            keys["date"] = k
        if t == "select" and ("source" in k.lower() or "источник" in k.lower()):
            keys["source"] = k
        if t in ("rich_text","title") and ("xai" in k.lower() or "лог" in k.lower()):
            keys["xai"] = k
    return keys

def create_task(
    title_text: str,
    status_name: str | None = "Planned",
    deadline_iso: str | None = None,      # "YYYY-MM-DD"
    source_name: str | None = None,       # например: "Чат Аян" / "Грок" / "API"
    xai_note: str | None = None,
):
    props = get_db_props()
    keys = find_prop_keys(props)

    if not keys["title"]:
        raise RuntimeError("Не найдено поле типа Title в базе Notion.")

    body_props = {
        keys["title"]: {"title": [{"text": {"content": title_text}}]}
    }

        # Статус (поддержим и Status, и Select) — подберём существующую опцию
    if keys["status"]:
        name, kind = keys["status"]
        if kind == "status":
            # список существующих опций статуса
            opts = [o["name"] for o in props[name]["status"]["options"]]
            chosen = status_name if (status_name and status_name in opts) else (opts[0] if opts else None)
            if chosen:
                body_props[name] = {"status": {"name": chosen}}
        else:
            # select: Notion сам создаст опцию, если её нет
            if status_name:
                body_props[name] = {"select": {"name": status_name}}


    # Дедлайн (Date)
    if keys["date"] and deadline_iso:
        body_props[keys["date"]] = {"date": {"start": deadline_iso}}

    # Источник (Select) — Notion сам создаст опцию, если её нет
    if keys["source"] and source_name:
        body_props[keys["source"]] = {"select": {"name": source_name}}

    # XAI Log (rich_text / title как текст)
    if keys["xai"] and xai_note:
        # если поле rich_text — кладём туда; если вдруг title — тоже положим (редко)
        body_props[keys["xai"]] = {"rich_text": [{"text": {"content": xai_note}}]} if props[keys["xai"]]["type"]=="rich_text" \
                                   else {"title": [{"text": {"content": xai_note}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": body_props}
    r = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, data=json.dumps(payload))
    if r.status_code in (200, 201):
        page = r.json()
        print("✅ Создано:", title_text, "| page_id:", page["id"])
    else:
        print("❌ Ошибка:", r.status_code, r.text[:500])

if __name__ == "__main__":
    # Пример: создаём тестовую задачу
    create_task(
        title_text="API-тест: связь работает",
        status_name="Not started",
                      # или "In Progress" / "Done" / "Blocked"
        deadline_iso=date.today().isoformat(),       # сегодняшняя дата
        source_name="API",                           # опционально
        xai_note="[XAI] создано из Python тестом"    # опционально
    )
