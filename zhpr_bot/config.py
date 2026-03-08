# -*- coding: utf-8 -*-
"""
config.py — Конфигурация ЖПР-бота INTELLECTUM

Здесь храним:
- токены Telegram и Notion
- ID баз Notion
- имена колонок
- пути к структуре (structure.txt)
- настройки погоды
"""

import os
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

# ===== Telegram =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_ZHPR", "")

# ===== Notion: база ЖПР =====
NOTION_TOKEN = os.getenv("NOTION_TOKEN_ZHPR", "")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID_ZHPR", "")

# ===== Notion: база вложений (фото) =====
ATT_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65", "")
ATT_DB_ID = os.getenv("NOTION_DATABASE_ID_SCHOOL65", "")

# ===== OpenWeather =====
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

# ===== Пути =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STRUCTURE_FILE = os.path.join(BASE_DIR, "structure", "structure.txt")
WEATHER_STORE_FILE = os.path.join(BASE_DIR, "weather_store.json")

# ===== Имена свойств Notion =====
PROP_TITLE       = "1. Название записи"
PROP_DATE        = "2. Дата"
PROP_SECTION     = "3. Раздел (ГПР)"
PROP_SUBSECTION  = "4. Подраздел / Участок"
PROP_WORKTYPE    = "5. Вид работ"
PROP_PLAN        = "6. Объём по плану (на день)"
PROP_FACT        = "7. Объём факт (выполнено)"
PROP_UNIT        = "8. Единица измерения"
PROP_WORKERS     = "9. Количество рабочих"
PROP_EQUIP_TYPE  = "10. Машины и механизмы (тип)"
PROP_EQUIP_COUNT = "11. Машины и механизмы (количество)"
PROP_WEATHER     = "12. Погода"
PROP_RESPONSIBLE = "13. Ответственный"
PROP_PHOTO       = "14. Фото (URL)"
PROP_COMMENT     = "15. Комментарий"

# ===== Заголовки Notion =====
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

ATT_HEADERS = None
if ATT_TOKEN and ATT_DB_ID:
    ATT_HEADERS = {
        "Authorization": f"Bearer {ATT_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
