# -*- coding: utf-8 -*-
"""
id_generator.py — генерация ID записей ЖПР и работа с порядковыми номерами
"""

import logging
from datetime import datetime
from typing import Dict, Any

import requests

from zhpr_bot.config import (
    NOTION_DB_ID,
    NOTION_HEADERS,
)
from zhpr_bot.config import PROP_DATE

log = logging.getLogger(__name__)


def get_next_seq_for_date(date_obj: datetime) -> int:
    """
    Возвращает следующий порядковый номер записи ЖПР за указанную дату.

    Считает, сколько страниц уже есть в базе Notion по полю даты,
    и возвращает count + 1.
    """
    date_str = date_obj.strftime("%Y-%m-%d")

    payload: Dict[str, Any] = {
        "filter": {
            "property": PROP_DATE,
            "date": {"equals": date_str},
        }
    }

    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=30,
        )
    except Exception:
        log.exception("Ошибка при запросе Notion для подсчёта записей за день")
        return 1

    if r.status_code != 200:
        log.warning(
            "Не удалось получить список ЖПР за дату %s: %s %s",
            date_str,
            r.status_code,
            r.text,
        )
        return 1

    try:
        data = r.json()
        count = len(data.get("results", []))
        return count + 1
    except Exception:
        log.exception("Не удалось распарсить ответ Notion при подсчёте записей")
        return 1


def generate_zhpr_id(date_obj: datetime) -> str:
    """
    Генерирует ID вида: ЖПР-ГГГГММДД-XXX,
    где XXX — порядковый номер записи за день.
    """
    seq = get_next_seq_for_date(date_obj)
    date_part = date_obj.strftime("%Y%m%d")
    return f"ЖПР-{date_part}-{seq:03d}"
