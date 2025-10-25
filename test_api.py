import os, time, requests
from pathlib import Path
from dotenv import load_dotenv

# ── грузим .env явно из папки со скриптом ──────────────────────────────────────
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID")
assert NOTION_TOKEN, "Нет NOTION_TOKEN в .env!"
assert DATABASE_ID,  "Нет NOTION_DATABASE_ID в .env!"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ── узнаём имя титульной колонки (type == 'title') ────────────────────────────
def get_title_prop_name():
    r = requests.get(f"https://api.notion.com/v1/databases/{DATABASE_ID}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"Не смог прочитать базу: {r.status_code} {r.text}")
    props = r.json()["properties"]
    for name, meta in props.items():
        if meta.get("type") == "title":
            return name
    raise RuntimeError("В базе не нашли колонку типа 'title'")

title_prop = get_title_prop_name()

# ── создаём тестовую запись ───────────────────────────────────────────────────
payload = {
    "parent": {"database_id": DATABASE_ID},
    "properties": {
        title_prop: {
            "title": [
                {"text": {"content": f"Проверка связи API — {int(time.time())}"}}
            ]
        }
    }
}

resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
print("STATUS:", resp.status_code)
try:
    print(resp.json())
except Exception:
    print(resp.text)
