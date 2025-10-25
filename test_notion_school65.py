# -*- coding: utf-8 -*-
import os, json, datetime, requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID_SCHOOL65")

assert NOTION_TOKEN and DATABASE_ID, "Проверь .env: NOTION_TOKEN_SCHOOL65 и NOTION_DATABASE_ID_SCHOOL65"

NOTION_API = "https://api.notion.com/v1/pages"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def add_entry(section_path, name, url=None, comment=None, date=None):
    props = {
        "Раздел": {"select": {"name": section_path}},  # создаст опцию, если её нет
        "Файл / Фото": {"rich_text": [{"text": {"content": name}}]},
    }
    if url:
        props["Ссылка OneDrive"] = {"url": url}
    if comment:
        props["Комментарий"] = {"rich_text": [{"text": {"content": comment}}]}
    if date is None:
        date = datetime.date.today().isoformat()
    props["Дата"] = {"date": {"start": date}}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = requests.post(NOTION_API, headers=HEADERS, data=json.dumps(payload))
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Notion error {r.status_code}: {r.text}")
    return r.json().get("id")

if __name__ == "__main__":
    page_id = add_entry(
        section_path="Благоустройство / Плитка / Укладка",
        name="Тестовая синхронизация",
        url=None,  # при желании вставь ссылку OneDrive
        comment="Проверка связи (Ереке + Аян)"
    )
    print("OK, создана запись в Notion, page_id:", page_id)
