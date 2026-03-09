# -*- coding: utf-8 -*-
"""
zhpr_queries.py — вспомогательные запросы к базе ЖПР в Notion

Сейчас здесь:
- получение последней даты записи ЖПР
"""

import logging
from datetime import datetime, date
from typing import Optional, Dict, Any

import requests

from zhpr_bot.config import NOTION_DB_ID, NOTION_HEADERS, PROP_DATE

log = logging.getLogger(__name__)


def get_last_zhpr_date() -> Optional[date]:
    """
    Берём последнюю дату из Notion по полю PROP_DATE.

    Возвращает:
        date или None, если записей нет или произошла ошибка.
    """
    try:
        payload: Dict[str, Any] = {
            "page_size": 1,
            "sorts": [
                {
                    "property": PROP_DATE,
                    "direction": "descending",
                }
            ],
        }

        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=20,
        )
        if resp.status_code != 200:
            log.warning("Не удалось получить последнюю дату ЖПР: %s", resp.text)
            return None

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None

        props = results[0]["properties"]
        date_prop = props.get(PROP_DATE, {}).get("date")
        if not date_prop or not date_prop.get("start"):
            return None

        d = datetime.fromisoformat(date_prop["start"]).date()
        return d

    except Exception:
        log.exception("Ошибка при запросе последней даты ЖПР из Notion")
        return None
