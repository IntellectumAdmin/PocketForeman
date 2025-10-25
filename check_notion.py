import os
import requests

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_TASKS_DB")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"

response = requests.post(url, headers=HEADERS, json={})

print("Status:", response.status_code)

data = response.json()

print("Всего задач:", len(data["results"]))
for page in data["results"]:
    props = page["properties"]

    # --- Title (главное поле). У тебя оно называется "ID (текст)" ---
    if "ID (текст)" in props and props["ID (текст)"].get("type") == "title":
        title_items = props["ID (текст)"]["title"]
    else:
        # На всякий случай: авто-поиск первого поля типа title
        title_key = next((k for k, v in props.items() if v.get("type") == "title"), None)
        title_items = props[title_key]["title"] if title_key else []

    title = title_items[0]["plain_text"] if title_items else "(без названия)"

    # --- Статус (поддержим и Status, и Select) ---
    status_val = "-"
    if "Статус" in props:
        t = props["Статус"].get("type")
        if t == "status" and props["Статус"]["status"]:
            status_val = props["Статус"]["status"]["name"]
        elif t == "select" and props["Статус"]["select"]:
            status_val = props["Статус"]["select"]["name"]

    # --- Дедлайн (если есть колонка Date) ---
    deadline_val = "-"
    for k, v in props.items():
        if v.get("type") == "date":
            if v["date"] and v["date"].get("start"):
                deadline_val = v["date"]["start"]
            break

    print(f"- {title} | Статус: {status_val} | Дедлайн: {deadline_val}")

with open("tasks_output.txt", "w", encoding="utf-8") as f:
    f.write(f"Всего задач: {len(data['results'])}\n")
    for page in data["results"]:
        props = page["properties"]

        # Title
        if "ID (текст)" in props and props["ID (текст)"].get("type") == "title":
            title_items = props["ID (текст)"]["title"]
        else:
            title_key = next((k for k, v in props.items() if v.get("type") == "title"), None)
            title_items = props[title_key]["title"] if title_key else []

        title = title_items[0]["plain_text"] if title_items else "(без названия)"

        # Status
        status_val = "-"
        if "Статус" in props:
            t = props["Статус"].get("type")
            if t == "status" and props["Статус"]["status"]:
                status_val = props["Статус"]["status"]["name"]
            elif t == "select" and props["Статус"]["select"]:
                status_val = props["Статус"]["select"]["name"]

        # Deadline
        deadline_val = "-"
        for k, v in props.items():
            if v.get("type") == "date":
                if v["date"] and v["date"].get("start"):
                    deadline_val = v["date"]["start"]
                break

        f.write(f"- {title} | Статус: {status_val} | Дедлайн: {deadline_val}\n")


