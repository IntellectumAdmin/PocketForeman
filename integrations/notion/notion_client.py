# notion_client.py
import os, requests
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID")

# Имена свойств из .env (как у тебя сейчас)
TITLE_PROP   = os.getenv("PROP_TITLE_ID")     # "ID (текст)"
PROP_NAME    = os.getenv("PROP_NAME")
PROP_STATUS  = os.getenv("PROP_STATUS")
PROP_DEADLINE= os.getenv("PROP_DEADLINE")
PROP_SOURCE  = os.getenv("PROP_SOURCE")
PROP_OBJECT  = os.getenv("PROP_OBJECT")
PROP_ATTACH  = os.getenv("PROP_ATTACH")
PROP_XAI_LOG = os.getenv("PROP_XAI_LOG")

assert NOTION_TOKEN and DATABASE_ID, "Проверь NOTION_TOKEN / NOTION_DATABASE_ID в .env"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def _get_db_schema():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def get_title_prop_fallback():
    """
    Возвращает имя титульной колонки:
    - сначала пробуем из .env (TITLE_PROP)
    - иначе читаем схему и ищем property с type == 'title'
    """
    if TITLE_PROP:
        return TITLE_PROP
    schema = _get_db_schema().get("properties", {})
    for name, meta in schema.items():
        if meta.get("type") == "title":
            return name
    raise RuntimeError("Не нашли title-колонку в базе Notion")

def add_page(properties: dict):
    url = "https://api.notion.com/v1/pages"
    payload = {"parent": {"database_id": DATABASE_ID}, "properties": properties}
    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code >= 400:
        raise RuntimeError(f"Notion error {r.status_code}: {r.text}")
    return r.json()

# Утилита: безопасно проставить select/статус, если колонка есть в .env
def set_select(props: dict, prop_name: str | None, value: str):
    if not prop_name:
        return
    props[prop_name] = {"select": {"name": value}}
