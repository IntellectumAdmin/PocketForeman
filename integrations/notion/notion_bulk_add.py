# notion_bulk_add.py  (v2: анти-дубли по (Название + Объект))
# Требует: .env (NOTION_TOKEN, NOTION_DATABASE_ID, имена свойств в P*)
# Вход: tasks_to_add.txt — по одной задаче в строке. Формат:
#  "Название задачи"   или   "Название задачи @Объект"

import os, re, json, sys
from dotenv import load_dotenv
import requests

load_dotenv()

NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
DATABASE_ID    = os.getenv("NOTION_DATABASE_ID")

# Имена свойств (точно как в Notion)
P_TITLE_ID = os.getenv("PROP_TITLE_ID", "ID (текст)")
P_NAME     = os.getenv("PROP_NAME", "Название задачи")
P_STATUS   = os.getenv("PROP_STATUS", "Статус")
P_OBJECT   = os.getenv("PROP_OBJECT", "Объект")  # Select

HEAD = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

INPUT_FILE = "tasks_to_add.txt"
DEFAULT_STATUS = "Not started"

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()

def parse_line(line: str):
    """Возвращает (name, object|None). Формат: 'Название @Объект'."""
    raw = line.strip()
    if not raw:
        return None, None
    # делим только по последнему ' @'
    if "@" in raw:
        left, right = raw.split("@", 1)
        name = left.strip()
        obj  = right.strip()
        if obj == "":
            obj = None
        return name, obj
    return raw, None

def notion_paginate(url: str, payload: dict):
    """Итератор по всем страницам результатов /query."""
    start_cursor = None
    while True:
        body = dict(payload)
        if start_cursor:
            body["start_cursor"] = start_cursor
        r = requests.post(url, headers=HEAD, data=json.dumps(body))
        r.raise_for_status()
        data = r.json()
        for item in data.get("results", []):
            yield item
        if not data.get("has_more"):
            break
        start_cursor = data.get("next_cursor")

def fetch_existing_pairs_and_max():
    """Возвращает (set((name_norm, object_norm)), max_intel_number)."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {
        "page_size": 100,
        "filter": {"property": P_STATUS, "status": {"does_not_equal": ""}},  # просто любой запрос
        "sorts": [{"property": P_TITLE_ID, "direction": "ascending"}],
    }
    pairs = set()
    max_no = 0

    # Если базы многостраничные — заберём все
    for page in notion_paginate(url, payload):
        props = page.get("properties", {})
        # ID (текст)
        tval = ""
        tarr = props.get(P_TITLE_ID, {}).get("title", [])
        if tarr:
            tval = tarr[0].get("plain_text") or tarr[0].get("text", {}).get("content", "")

        m = re.search(r"INTEL-(\d+)", tval or "")
        if m:
            try:
                n = int(m.group(1))
                if n > max_no:
                    max_no = n
            except:
                pass

        # Название
        name = ""
        narr = props.get(P_NAME, {}).get("rich_text", [])
        if narr:
            name = narr[0].get("plain_text") or narr[0].get("text", {}).get("content", "")

        # Объект (select)
        obj_name = ""
        sel = props.get(P_OBJECT, {}).get("select")
        if isinstance(sel, dict):
            obj_name = sel.get("name") or ""

        pairs.add((norm(name), norm(obj_name)))

    return pairs, max_no

def create_page(next_no: int, name: str, obj: str|None):
    intel_id = f"INTEL-{next_no:03d}"
    properties = {
        P_TITLE_ID: {"title": [{"text": {"content": intel_id}}]},
        P_NAME:     {"rich_text": [{"text": {"content": name}}]},
        P_STATUS:   {"status": {"name": DEFAULT_STATUS}},
    }
    if obj:
        properties[P_OBJECT] = {"select": {"name": obj}}

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": properties,
    }
    r = requests.post("https://api.notion.com/v1/pages", headers=HEAD, data=json.dumps(payload))
    return r

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Не найден файл ввода: {INPUT_FILE}")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]

    # Парсим
    items = []
    for ln in lines:
        name, obj = parse_line(ln)
        if name:
            items.append((name, obj))

    existing_pairs, max_intel = fetch_existing_pairs_and_max()

    print(f"Разрешённый статус по умолчанию: {DEFAULT_STATUS}")
    print(f"Файл ввода: {INPUT_FILE}")
    print(f"В базе найдено: max INTEL = {max_intel:03d}, уникальных по (Название+Объект) = {len(existing_pairs)}")

    to_add = []
    skipped = 0
    for name, obj in items:
        key = (norm(name), norm(obj or ""))
        if key in existing_pairs:
            skipped += 1
            continue
        to_add.append((name, obj))

    print(f"Буду добавлять {len(to_add)} строк(и); пропущено дублей: {skipped}\n")

    ok = 0
    err = 0
    next_no = max_intel
    for name, obj in to_add:
        next_no += 1
        r = create_page(next_no, name, obj)
        if r.status_code in (200, 201):
            intel_id = f"INTEL-{next_no:03d}"
            suffix = f" @{obj}" if obj else ""
            print(f"  √ Добавлено: {intel_id} — «{name}{suffix}»")
            existing_pairs.add((norm(name), norm(obj or "")))
            ok += 1
        else:
            print(f"  × Ошибка: {r.status_code} {r.text}")
            err += 1

    print(f"\n— Готово. Успешно: {ok}, с ошибками: {err}")
    print("Напоминание: очисти tasks_to_add.txt, чтобы не отправить повторно.")
    input("Для продолжения нажмите любую клавишу . . . ")

if __name__ == "__main__":
    main()
