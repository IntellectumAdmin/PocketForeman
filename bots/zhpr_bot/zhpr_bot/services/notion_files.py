# -*- coding: utf-8 -*-
"""
notion_files.py — работа с Notion-базой вложений (фото) для ЖПР-бота

Ищем фото по:
- дате (колонка "Дата")
- разделу (колонка "Раздел")

Основной источник URL:
- колонка "Ссылка OneDrive"
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

import requests

from zhpr_bot.config import (
    ATT_DB_ID,
    ATT_HEADERS,
)

log = logging.getLogger(__name__)

# Названия колонок в базе вложений (как в твоём скрине)
ATT_PROP_SECTION = "Раздел"
ATT_PROP_FILE = "Файл / Фото"
ATT_PROP_URL = "Ссылка OneDrive"
ATT_PROP_DATE = "Дата"


def find_photo_url_for_entry(date_obj: datetime, section_full: str) -> Optional[str]:
    """
    Ищет запись в базе вложений по дате и разделу,
    возвращает URL фото (если найдено).

    Логика:
    - фильтр по дате (equals)
    - фильтр по разделу (select == section_full)
    - сортировка по времени последнего редактирования (последняя сверху)
    """
    if not (ATT_HEADERS and ATT_DB_ID):
        # База вложений не настроена — просто выходим без ошибки
        return None

    date_str = date_obj.strftime("%Y-%m-%d")

    payload: Dict[str, Any] = {
        "filter": {
            "and": [
                {
                    "property": ATT_PROP_DATE,
                    "date": {"equals": date_str},
                },
                {
                    "property": ATT_PROP_SECTION,
                    "select": {"equals": section_full},
                },
            ]
        },
        "page_size": 1,
        "sorts": [
            {
                "timestamp": "last_edited_time",
                "direction": "descending",
            }
        ],
    }

    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{ATT_DB_ID}/query",
            headers=ATT_HEADERS,
            json=payload,
            timeout=20,
        )
    except Exception:
        log.exception("Ошибка запроса к Notion (Журнал вложений)")
        return None

    if r.status_code != 200:
        log.warning(
            "Журнал вложений: Notion вернул %s: %s",
            r.status_code,
            r.text,
        )
        return None

    try:
        data = r.json()
        results = data.get("results", [])
        if not results:
            return None

        props = results[0]["properties"]

        # Основной вариант — колонка "Ссылка OneDrive"
        url_prop = props.get(ATT_PROP_URL, {})
        url = url_prop.get("url")
        if url:
            return url

        # Запасной вариант — попытаться достать из "Файл / Фото"
        file_prop = props.get(ATT_PROP_FILE, {})
        files = file_prop.get("files") or []
        if files:
            f0 = files[0]
            if f0.get("type") == "external":
                return f0.get("external", {}).get("url")
            if f0.get("type") == "file":
                return f0.get("file", {}).get("url")

        return None
    except Exception:
        log.exception("Не удалось распарсить ответ Notion (Журнал вложений)")
        return None
