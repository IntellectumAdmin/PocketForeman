# notion_add_min.py
from notion_client import add_page, TITLE_PROP, PROP_STATUS

props = {
    # титульная колонка — это "ID (текст)" из .env → записываем туда текст
    TITLE_PROP: {"title": [{"text": {"content": "Тест через .env ✅"}}]}
}

# если есть колонка Статус — зададим "Not started"
if PROP_STATUS:
    # правильно для колонки типа Status:
    props[PROP_STATUS] = {"status": {"name": "Not started"}}


resp = add_page(props)
print("OK:", resp["id"])
