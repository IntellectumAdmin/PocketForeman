import requests

# 🔑 Подставь свои данные:
NOTION_TOKEN = "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"
DATABASE_ID  = "28075f2041118008abc5ec7b5a15a072"

# Заголовки
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# Данные для новой задачи
data = {
    "parent": {"database_id": DATABASE_ID},
    "properties": {
        "ID (текст)": {   # ⚡ именно так, как у тебя в базе
            "title": [{"text": {"content": "Проверка API — запись удалась ✅"}}]
        }
    }
}

# Отправляем запрос
resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=data)

print("STATUS:", resp.status_code)
print("RESPONSE:", resp.json())
