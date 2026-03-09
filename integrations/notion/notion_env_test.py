# notion_env_smoke.py
import os, requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

token = os.getenv("NOTION_TOKEN")
dbid  = os.getenv("NOTION_DATABASE_ID")

r = requests.post(
    "https://api.notion.com/v1/pages",
    headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    },
    json={
        "parent": {"database_id": dbid},
        "properties": {
            "ID (текст)": {"title": [{"text": {"content": "Проверка API — ок ✅"}}]},
        },
    },
)
print(r.status_code, r.text[:400])
