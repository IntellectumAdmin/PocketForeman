# notion_add_one_min.py
import os, json, requests
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("NOTION_TOKEN")
DB_ID  = os.getenv("NOTION_DATABASE_ID")

P_TITLE = os.getenv("PROP_TITLE_ID", "ID (текст)")
P_NAME  = os.getenv("PROP_NAME", "Название задачи")
P_STATUS= os.getenv("PROP_STATUS", "Статус")
P_OBJ   = os.getenv("PROP_OBJECT", "Объект")

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

props = {
    P_TITLE: {"title": [{"text": {"content": "INTEL-001"}}]},
    P_NAME:  {"rich_text": [{"text": {"content": "Сделать обмеры фасадов"}}]},
    P_STATUS:{"status": {"name": "Not started"}},
    P_OBJ:   {"select": {"name": "Блок 9"}},
}

payload = {"parent": {"database_id": DB_ID}, "properties": props}
r = requests.post("https://api.notion.com/v1/pages", headers=headers, data=json.dumps(payload))
print(r.status_code, r.text)
