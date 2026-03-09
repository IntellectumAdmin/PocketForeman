# -*- coding: utf-8 -*-
import os, json, requests, argparse, sys
from datetime import datetime
from typing import Optional, Dict, List

# ===== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ =====
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID  = os.getenv("NOTION_TASKS_DB")

API = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ===== ИМЕНА СВОЙСТВ В ТВОЕЙ БАЗЕ =====
TITLE_PROP      = "ID (текст)"          # Title
NAME_TEXT_PROP  = "Название задачи"     # Text
STATUS_PROP     = "Статус"              # Status
DEADLINE_PROP   = "Срок ( Deadline)"    # Date  (с пробелом внутри)
SOURCE_PROP     = "Источник (Source)"   # Select
PRIORITY_PROP   = "Приоритет"           # Select (если есть)
SIZE_PROP       = "Сложность (Size)"    # Select (если есть)

# ===== АЛИАСЫ =====
STATUS_ALIASES = {
    "не начато":"Not started","не начата":"Not started",
    "в работе":"In progress","в процессе":"In progress","делается":"In progress",
    "готово":"Done","сделано":"Done",
    "блок":"Blocked","заблокировано":"Blocked",
}
PRIORITY_ALIASES = {
    "высокий":"High","средний":"Medium","низкий":"Low",
    "high":"High","medium":"Medium","low":"Low",
}
SIZE_ALIASES = {
    "s":"S","small":"S","мал":"S","мал.":"S","небольшая":"S",
    "m":"M","medium":"M","ср":"M","ср.":"M","средняя":"M",
    "l":"L","large":"L","крупн":"L","крупн.":"L","большая":"L",
}

def normalize(val: Optional[str], aliases: Dict[str,str]) -> Optional[str]:
    if not val: return None
    v = val.strip()
    return aliases.get(v.lower(), v)

def parse_deadline(s: Optional[str]) -> Optional[str]:
    if not s: return None
    s = s.strip()
    if not s: return None
    if len(s)==10 and s[4]=="-" and s[7]=="-":   # YYYY-MM-DD
        return s
    if len(s)==10 and s[2]=="." and s[5]==".":   # DD.MM.YYYY
        d,m,y = s.split(".")
        return f"{y}-{m}-{d}"
    return s

def db_properties() -> Dict:
    r = requests.get(f"{API}/databases/{DATABASE_ID}", headers=HEADERS)
    return r.json() if r.status_code==200 else {}

def allowed_statuses() -> List[str]:
    try:
        props = db_properties()["properties"][STATUS_PROP]["status"]["options"]
        return [o["name"] for o in props]
    except Exception:
        return []

def allowed_select(prop: str) -> List[str]:
    try:
        props = db_properties()["properties"][prop]["select"]["options"]
        return [o["name"] for o in props]
    except Exception:
        return []

# ---------- Поиск страницы ----------
def query(payload: Dict) -> Dict:
    r = requests.post(f"{API}/databases/{DATABASE_ID}/query",
                      headers=HEADERS, data=json.dumps(payload))
    return r.json()

def find_by_intel_id(intel_id: str) -> Optional[Dict]:
    # Ищем по Title equals
    payload = {
        "filter": {"property": TITLE_PROP, "title": {"equals": intel_id}},
        "page_size": 1
    }
    data = query(payload)
    res = data.get("results", [])
    return res[0] if res else None

def find_by_name_contains(substr: str) -> List[Dict]:
    payload = {
        "filter": {"property": NAME_TEXT_PROP, "rich_text": {"contains": substr}},
        "page_size": 50
    }
    data = query(payload)
    return data.get("results", [])

# ---------- Обновление ----------
def patch_page(page_id: str, props: Dict) -> bool:
    r = requests.patch(f"{API}/pages/{page_id}",
                       headers=HEADERS,
                       data=json.dumps({"properties": props}))
    return r.status_code==200

def build_props(status=None, deadline=None, source=None, priority=None, size=None, new_name=None) -> Dict:
    props = {}
    if status:
        props[STATUS_PROP] = {"status": {"name": status}}
    if deadline:
        props[DEADLINE_PROP] = {"date": {"start": deadline}}
    if source:
        props[SOURCE_PROP] = {"select": {"name": source}}
    if priority:
        props[PRIORITY_PROP] = {"select": {"name": priority}}
    if size:
        props[SIZE_PROP] = {"select": {"name": size}}
    if new_name is not None:
        props[NAME_TEXT_PROP] = {"rich_text": [{"text": {"content": new_name}}]}
    return props

def main():
    if not NOTION_TOKEN or not DATABASE_ID:
        print("❗ NOTION_TOKEN/NOTION_TASKS_DB не заданы.")
        sys.exit(1)

    p = argparse.ArgumentParser(description="Обновление задач в Notion")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id",    help="Точный INTEL-ID, напр. INTEL-023")
    g.add_argument("--name",  help="Подстрока в «Название задачи»")

    p.add_argument("--status",   help="Новый статус (ru/en)")
    p.add_argument("--deadline", help="Новый срок: 2025-09-27 или 27.09.2025")
    p.add_argument("--source",   help="Источник (Select)")
    p.add_argument("--priority", help="Приоритет (High/Medium/Low или рус.)")
    p.add_argument("--size",     help="Сложность (S/M/L или рус.)")
    p.add_argument("--rename",   help="Переименовать «Название задачи»")
    args = p.parse_args()

    # нормализуем ввод
    new_status   = normalize(args.status,   STATUS_ALIASES)
    new_deadline = parse_deadline(args.deadline)
    new_source   = args.source.strip() if args.source else None
    new_priority = normalize(args.priority, PRIORITY_ALIASES)
    new_size     = normalize(args.size,     SIZE_ALIASES)
    new_name     = args.rename

    # подсказки по разрешённым значениям
    allowed_stat = allowed_statuses()
    if new_status and allowed_stat and new_status not in allowed_stat:
        print("⚠ Статус не найден. Разрешено:", ", ".join(allowed_stat))
        sys.exit(1)
    for prop, val, allowed in [
        (PRIORITY_PROP, new_priority, allowed_select(PRIORITY_PROP)),
        (SIZE_PROP,     new_size,     allowed_select(SIZE_PROP)),
    ]:
        if val and allowed and val not in allowed:
            print(f"⚠ Значение «{val}» не найдено для {prop}. Разрешено:", ", ".join(allowed))
            sys.exit(1)

    # находим страницы
    pages: List[Dict]
    if args.id:
        page = find_by_intel_id(args.id.strip())
        if not page:
            print("Не нашёл страницу с ID:", args.id)
            sys.exit(1)
        pages = [page]
    else:
        pages = find_by_name_contains(args.name.strip())
        if not pages:
            print("По подстроке ничего не найдено.")
            sys.exit(1)
        print(f"Найдено страниц: {len(pages)}")

    props = build_props(
        status=new_status,
        deadline=new_deadline,
        source=new_source,
        priority=new_priority,
        size=new_size,
        new_name=new_name
    )

    ok, fail = 0, 0
    for pg in pages:
        pid = pg["id"]
        title_txt = ""
        try:
            title_txt = pg["properties"][TITLE_PROP]["title"][0]["plain_text"]
        except Exception:
            pass
        name_txt = ""
        try:
            name_txt = pg["properties"][NAME_TEXT_PROP]["rich_text"][0]["plain_text"]
        except Exception:
            pass

        if patch_page(pid, props):
            ok += 1
            print(f"  ✓ Обновлено: {title_txt} — «{name_txt}» (page_id={pid})")
        else:
            fail += 1
            print(f"  ✗ Ошибка обновления: {title_txt} — «{name_txt}» (page_id={pid})")

    print(f"— Готово. Успешно: {ok}, с ошибками: {fail}")

if __name__ == "__main__":
    main()
