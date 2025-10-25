# -*- coding: utf-8 -*-
"""
Добавляет запись в Notion: Раздел (Select) + Файл/Фото (название) + Ссылка OneDrive + Дата + Комментарий.
Использует переменные:
  NOTION_TOKEN_SCHOOL65
  NOTION_DATABASE_ID_SCHOOL65
"""

import os, json, argparse, datetime, requests
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

def add_entry(section_path: str, name: str, onedrive_url: str = None,
              comment: str = None, date_str: str = None) -> str:
    """Создаёт строку в базе Notion. Возвращает page_id."""
    if not date_str:
        date_str = datetime.date.today().isoformat()

    props = {
        "Раздел": {"select": {"name": section_path}},          # создаст опцию, если её нет
        "Файл / Фото": {"rich_text": [{"text": {"content": name}}]},
        "Дата": {"date": {"start": date_str}},
    }
    if onedrive_url:
        props["Ссылка OneDrive"] = {"url": onedrive_url}
    if comment:
        props["Комментарий"] = {"rich_text": [{"text": {"content": comment}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}

    r = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, data=json.dumps(payload))
    print("DEBUG Notion:", r.status_code, r.text[:400])  # <-- добавь ЭТУ строку
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Notion error {r.status_code}: {r.text}")
    return r.json().get("id")

def main():
    ap = argparse.ArgumentParser(description="INTELLECTUM: добавить запись в «Журнал вложений» Notion")
    ap.add_argument("--section", required=True, help="Путь раздела из ГПР (напр. 'Здание школы / Архитектурная часть / Фасады')")
    ap.add_argument("--name",    required=True, help="Имя/описание файла (напр. 'Фото фасада 14.10')")
    ap.add_argument("--url",     required=True, help="Шаринг-ссылка OneDrive на файл или папку")
    ap.add_argument("--comment", default=None,  help="Комментарий (опционально)")
    ap.add_argument("--date",    default=None,  help="Дата ISO YYYY-MM-DD (опционально, по умолчанию сегодня)")
    args = ap.parse_args()

    page_id = add_entry(args.section, args.name, args.url, args.comment, args.date)
    print("OK: создана запись в Notion, page_id:", page_id)

if __name__ == "__main__":
    main()



