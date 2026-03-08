# -*- coding: utf-8 -*-
"""
notion_jpr.py — создание записей ЖПР в Notion
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

import requests
from telegram.ext import ContextTypes

from zhpr_bot.config import (
    NOTION_DB_ID,
    NOTION_HEADERS,
    PROP_TITLE,
    PROP_DATE,
    PROP_SECTION,
    PROP_SUBSECTION,
    PROP_WORKTYPE,
    PROP_PLAN,
    PROP_FACT,
    PROP_UNIT,
    PROP_WORKERS,
    PROP_EQUIP_TYPE,
    PROP_EQUIP_COUNT,
    PROP_WEATHER,
    PROP_RESPONSIBLE,
    PROP_PHOTO,
    PROP_COMMENT,
)
from zhpr_bot.services.id_generator import generate_zhpr_id
from zhpr_bot.services.notion_files import find_photo_url_for_entry

log = logging.getLogger(__name__)


async def create_notion_page_from_context(
    context: ContextTypes.DEFAULT_TYPE,
) -> Tuple[bool, str]:
    """
    Собираем данные из context.user_data["zhpr"] и создаём страницу в Notion.

    Возвращаем:
        (True, zhpr_id) при успехе
        (False, текст_ошибки) при ошибке
    """
    ud: Dict[str, Any] = context.user_data.get("zhpr", {}) or {}
    if not ud:
        return False, "Нет данных ЖПР в контексте."

    date_obj: datetime = ud.get("date_obj", datetime.now())
    zhpr_id: str = ud.get("zhpr_id") or generate_zhpr_id(date_obj)

    # === Автофото: если не задано в контексте, пробуем взять из Журнала вложений ===
    section_full: Optional[str] = ud.get("section")
    if not ud.get("photo_url") and section_full:
        auto_url = find_photo_url_for_entry(date_obj, section_full)
        if auto_url:
            ud["photo_url"] = auto_url

    props: Dict[str, Any] = {}

    # Title (ID + краткое описание)
    title_text = zhpr_id
    if ud.get("section"):
        title_text += f" — {ud.get('section')}"
    if ud.get("subsection"):
        title_text += f" / {ud.get('subsection')}"

    props[PROP_TITLE] = {
        "title": [{"text": {"content": title_text}}]
    }

    # Дата
    props[PROP_DATE] = {
        "date": {"start": date_obj.strftime("%Y-%m-%d")}
    }

    # Раздел (Select)
    section = ud.get("section")
    if section:
        props[PROP_SECTION] = {"select": {"name": section}}

    # Подраздел (Rich text)
    subsection = ud.get("subsection")
    if subsection:
        props[PROP_SUBSECTION] = {
            "rich_text": [{"text": {"content": subsection}}]
        }

    # Вид работ (Select — берём первый из списка)
    worktypes: List[str] = ud.get("worktypes", []) or []
    if worktypes:
        props[PROP_WORKTYPE] = {"select": {"name": worktypes[0]}}

    # Объёмы план/факт
    if ud.get("plan") is not None:
        props[PROP_PLAN] = {"number": ud.get("plan")}
    if ud.get("fact") is not None:
        props[PROP_FACT] = {"number": ud.get("fact")}

    # Ед. измерения (Select)
    unit = ud.get("unit")
    if unit:
        props[PROP_UNIT] = {"select": {"name": unit}}

    # Рабочие (Number)
    if ud.get("workers") is not None:
        props[PROP_WORKERS] = {"number": ud.get("workers")}

    # Техника (Multi-select)
    equip_types: List[str] = ud.get("equip_types", []) or []
    if equip_types:
        props[PROP_EQUIP_TYPE] = {
            "multi_select": [{"name": t} for t in equip_types]
        }

    # Кол-во техники (Rich text)
    equip_count = ud.get("equip_count")
    if equip_count:
        props[PROP_EQUIP_COUNT] = {
            "rich_text": [{"text": {"content": equip_count}}]
        }

    # Погода
    weather = ud.get("weather") or ""
    if weather:
        props[PROP_WEATHER] = {
            "rich_text": [{"text": {"content": weather}}]
        }

    # Ответственный
    responsible = ud.get("responsible")
    if responsible:
        props[PROP_RESPONSIBLE] = {
            "rich_text": [{"text": {"content": responsible}}]
        }

    # Фото (URL)
    photo_url = ud.get("photo_url")
    if photo_url:
        props[PROP_PHOTO] = {"url": photo_url}

    # Комментарий
    comment = ud.get("comment")
    if comment:
        props[PROP_COMMENT] = {
            "rich_text": [{"text": {"content": comment}}]
        }

    payload: Dict[str, Any] = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": props,
    }

    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json=payload,
            timeout=30,
        )
    except Exception as e:
        log.exception("Ошибка запроса к Notion при создании страницы ЖПР")
        return False, f"Ошибка сети при обращении к Notion: {e!r}"

    if r.status_code in (200, 201):
        return True, zhpr_id

    # Пытаемся достать человекопонятное сообщение об ошибке
    try:
        j = r.json()
        msg = j.get("message") or j.get("error") or str(j)
    except Exception:
        msg = r.text

    return False, f"Notion вернул ошибку: {msg}"
