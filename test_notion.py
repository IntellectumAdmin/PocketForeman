import os, json, time, requests
from datetime import datetime

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_TASKS_DB")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def xai(event, notes=""):
    return f"[XAI] {event} @ {datetime.utcnow().isoformat()}Z | {notes}"

def create_task(name, status="Planned", deadline_iso=None):
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Name":   {"title": [{"text": {"content": name}}]},
            "Status": {"select": {"name": status}},
        },
    }
    if deadline_iso:
        payload["properties"]["Deadline"] = {"date": {"start": deadline_iso}}

    for attempt in range(3):
        r = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, data=json.dumps(payload))
        if r.status_code in (200, 201):
            print(xai("create_task:OK", f"name={name}, status={status}"))
            return True
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2 ** attempt)
            continue
        print(xai("create_task:FAIL", f"code={r.status_code}, body={r.text[:200]}"))
        return False
    print(xai("create_task:FAIL", "max_retries"))
    return False

# Пробный запуск
create_task("Test INTELLECTUM sync", "In Progress", "2025-09-30")
