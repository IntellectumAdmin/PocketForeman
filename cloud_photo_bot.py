# -*- coding: utf-8 -*-
"""
Pocket Foreman: Cloudinary -> Notion
- Главное меню и /photo
- Навигация по структуре
- Камера через WebApp (приём web_app_data)
- Галерея (одно фото)
"""

import os, io, re, json, time, logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
import requests
import cloudinary, cloudinary.uploader

from structure_sync import sync_structure  # структура берётся из кэша/файла

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram._update import Update as _RawUpdate

# ===== Анти-дубль web_app_data =====
RECENT_URLS: Dict[str, float] = {}  # url -> ts
def _seen_recent(url: str) -> bool:
    now = time.time()
    for k in list(RECENT_URLS.keys()):
        if now - RECENT_URLS[k] > 120:
            RECENT_URLS.pop(k, None)
    if not url: return False
    if url in RECENT_URLS: return True
    RECENT_URLS[url] = now
    return False

# ===== Логи =====
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pf-bot")
log.setLevel(logging.INFO)

# ===== .env =====
load_dotenv()
NOTION_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65", "")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID_SCHOOL65", "")

CLOUD_NAME   = os.getenv("CLOUD_NAME", "")
CLOUD_API_KEY= os.getenv("CLOUD_API_KEY", "")
CLOUD_API_SECRET = os.getenv("CLOUD_API_SECRET", "")
CLOUD_UNSIGNED_PRESET = os.getenv("CLOUD_UNSIGNED_PRESET", "pf_unsigned")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Колонки Notion
PROP_SECTION = os.getenv("PROP_SECTION", "Раздел")
PROP_FILE    = os.getenv("PROP_FILE", "Файл / Фото")
PROP_URL     = os.getenv("PROP_URL", "Ссылка OneDrive")
PROP_DATE    = os.getenv("PROP_DATE", "Дата")
PROP_COMMENT = os.getenv("PROP_COMMENT", "Комментарий")

# Структура
STRUCTURE_CACHE_PATH = Path("structure_cache.json")
STRUCT_ROOT = "Школа_65"
STRUCT_INDEX: Dict[str, List[str]] = {}

# UI-тексты
BTN_ADD_PHOTO = "📸 Добавить фото"
BTN_OPEN_CAM  = "📷 Открыть камеру"
BTN_CHANGE    = "🔄 Сменить раздел"
BTN_CANCEL    = "❌ Отмена"

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_ADD_PHOTO)]], resize_keyboard=True)

def cam_menu(cam_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(text=BTN_OPEN_CAM, web_app=WebAppInfo(cam_url))],
         [KeyboardButton(text=BTN_CHANGE), KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True
    )

# Cloudinary
if not (CLOUD_NAME and CLOUD_API_KEY and CLOUD_API_SECRET):
    raise RuntimeError("Заполни CLOUD_NAME/CLOUD_API_KEY/CLOUD_API_SECRET в .env")
cloudinary.config(cloud_name=CLOUD_NAME, api_key=CLOUD_API_KEY, api_secret=CLOUD_API_SECRET, secure=True)

# Notion
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Состояния
PH1_WAIT_SECTION, PH2_WAIT_PHOTO, PH3_WAIT_COMMENT = range(100, 103)

# ===== Структура (кэш) =====
def _build_index(paths: List[str]) -> Dict[str, List[str]]:
    idx: Dict[str, set] = {}
    for p in paths:
        parts = [s.strip() for s in p.split("/") if s.strip()]
        for i in range(len(parts)):
            parent = "/".join(parts[:i]); child = parts[i]
            idx.setdefault(parent, set()).add(child)
    return {k: sorted(list(v)) for k, v in idx.items()}

def structure_load_index():
    global STRUCT_ROOT, STRUCT_INDEX
    if STRUCTURE_CACHE_PATH.exists():
        data  = json.loads(STRUCTURE_CACHE_PATH.read_text(encoding="utf-8"))
        STRUCT_ROOT = data.get("root", STRUCT_ROOT)
        paths = data.get("paths", [])
        STRUCT_INDEX = _build_index(paths)
    else:
        STRUCT_INDEX = {}
    return STRUCT_ROOT, STRUCT_INDEX

def structure_children(parent_path: str) -> List[str]:
    return STRUCT_INDEX.get(parent_path, [])

def format_path_for_notion(path_str: str) -> str:
    parts = [s for s in path_str.split("/") if s]
    return " / ".join(parts)

# id ↔ path
PATH2ID: Dict[str, str] = {}
ID2PATH: Dict[str, str]  = {}
ID_SEQ = 1
def _id_for_path(path: str) -> str:
    global ID_SEQ
    if path not in PATH2ID:
        PATH2ID[path] = str(ID_SEQ)
        ID2PATH[str(ID_SEQ)] = path
        ID_SEQ += 1
    return PATH2ID[path]
def _path_by_id(pid: str) -> str:
    return ID2PATH.get(pid, "")

# ===== Notion helpers =====
def _notion_create_row_once(section: str, file_name: str, url: str, comment: Optional[str]) -> Tuple[bool, str]:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    props: Dict[str, Any] = {
        PROP_SECTION: {"select": {"name": section}},
        PROP_FILE: {"files": [{"name": file_name, "type": "external", "external": {"url": url}}]},
        PROP_URL: {"url": url},
        PROP_DATE: {"date": {"start": today_iso}},
    }
    if comment:
        props[PROP_COMMENT] = {"rich_text": [{"text": {"content": comment}}]}
    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload, timeout=30)
    if r.status_code in (200, 201):
        return True, "ok"
    try:
        j = r.json()
        return False, str(j.get("message") or j.get("error") or j)
    except Exception:
        return False, r.text

def _notion_create_row(section: str, file_name: str, url: str, comment: Optional[str]) -> Tuple[bool, str]:
    err = "unknown"
    for _ in range(3):
        ok, info = _notion_create_row_once(section, file_name, url, comment)
        if ok: return True, info
        err = info; time.sleep(1.0)
    return False, err

# ===== Команды =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👷 Привет! Я Карманный Прораб.\nНажми кнопку ниже, чтобы добавить фото к нужному разделу:",
        reply_markup=main_menu()
    )

async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Синхронизация структуры…")
    try:
        info = sync_structure()
        await update.message.reply_text(f"✓ Готово. Корень: {info['root']} | Разделов: {len(info['paths'])}",
                                        reply_markup=main_menu())
    except Exception as e:
        await update.message.reply_text(f"✗ Ошибка синхронизации: {e}")

# ===== Навигация по разделам =====
def _kb_for_parent(parent_path: str) -> InlineKeyboardMarkup:
    children = structure_children(parent_path)
    rows, row = [], []
    for name in children:
        full = f"{parent_path}/{name}" if parent_path else name
        pid = _id_for_path(full)
        row.append(InlineKeyboardButton(f"📂 {name}", callback_data=f"p|{pid}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    ctrl = []
    if parent_path:
        parent_parent = "/".join(parent_path.split("/")[:-1])
        ctrl.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"b|{_id_for_path(parent_parent)}"))
    ctrl.append(InlineKeyboardButton("✅ Выбрать здесь", callback_data=f"c|{_id_for_path(parent_path)}"))
    rows.append(ctrl)
    return InlineKeyboardMarkup(rows)

async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    root, _ = structure_load_index()
    if not STRUCT_INDEX:
        await update.message.reply_text("Похоже, список разделов пустой. Нажми /sync.")
        return ConversationHandler.END
    await update.message.reply_text(f"Выбери раздел проекта (корень: {root}):", reply_markup=_kb_for_parent(""))
    return PH1_WAIT_SECTION

async def photo_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = (q.data or "")
    act, _, pid = data.partition("|")
    path = _path_by_id(pid)

    if act in ("p", "b"):
        context.user_data["cursor_path"] = path
        await q.edit_message_text(
            text=f"Раздел: {format_path_for_notion(path) if path else 'Корень'}\nВыбери подраздел:",
            reply_markup=_kb_for_parent(path)
        )
        return PH1_WAIT_SECTION

    if act == "c":
        if not path:
            await q.answer("Нужно выбрать раздел.", show_alert=True)
            return PH1_WAIT_SECTION

        context.user_data["section_path"] = path
        nice = format_path_for_notion(path)

        cam_base = os.getenv("GHPAGES_CAMERA_URL", "https://intellectumadmin.github.io/PocketForeman/camera.html")
        folder = f"{STRUCT_ROOT}/{path}" if STRUCT_ROOT else path
        ts = int(time.time())
        cam_url = (f"{cam_base}?cloud={quote(CLOUD_NAME)}&preset={quote(CLOUD_UNSIGNED_PRESET)}"
                   f"&folder={quote(folder)}&section={quote(nice)}&cam=back&v={ts}")

        await q.edit_message_text(f"✅ Раздел выбран:\n{nice}\n\nСделайте фото:")
        await q.message.reply_text("Откройте камеру, снимите и жмите «Отправить».",
                                   reply_markup=cam_menu(cam_url))

        # На случай проблем с клавиатурной кнопкой — дублируем web_app inline:
        kb_open_inline = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📷 Открыть камеру (если снизу не работает)", web_app=WebAppInfo(cam_url))]]
        )
        await q.message.reply_text("Если кнопка снизу не открывает окно — нажмите эту:",
                                   reply_markup=kb_open_inline)
        return PH2_WAIT_PHOTO

    return PH1_WAIT_SECTION
# ===== Быстрый старт из inline-кнопки "go" (если будем её показывать) =====
async def photo_quick_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открывает выбор раздела так же, как /photo."""
    query = update.callback_query
    if query:
        await query.answer()
        # просто переиспользуем то, что делает /photo
        fake_update = Update(update.update_id, message=update.effective_message)
        await photo_start(fake_update, context)
    else:
        await photo_start(update, context)
    return PH1_WAIT_SECTION


# ===== Попросить прислать фото из галереи =====
async def on_ask_gallery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сообщение перед приёмом фото (если нажали 'Из галереи')."""
    q = update.callback_query
    if q:
        await q.answer()
    await update.effective_message.reply_text(
        "Пришли фото одним сообщением (можно альбомом). Если придёт альбом — возьму первый кадр.",
        reply_markup=ReplyKeyboardRemove()
    )
    return PH2_WAIT_PHOTO


# ===== Отмена диалога =====
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Операция отменена.", reply_markup=main_menu())
    return ConversationHandler.END

# ===== Галерея (одно фото) =====
async def ph2_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        await update.message.reply_text("Это не фото. Пришлите изображение.")
        return PH2_WAIT_PHOTO

    photo = update.message.photo[-1]
    file = await photo.get_file()
    bio = io.BytesIO()
    await file.download_to_memory(out=bio); bio.seek(0)
    context.user_data["photo_bytes"] = bio.read()

    await update.message.reply_text(
        "Комментарий (опционально) или «-»:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CHANGE), KeyboardButton(BTN_CANCEL)]],
                                         resize_keyboard=True)
    )
    return PH3_WAIT_COMMENT

async def ph3_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt == BTN_CANCEL:
        context.user_data.clear()
        await update.message.reply_text("Операция отменена.", reply_markup=main_menu())
        return ConversationHandler.END
    if txt == BTN_CHANGE:
        context.user_data.pop("section_path", None)
        context.user_data.pop("photo_bytes", None)
        root, _ = structure_load_index()
        await update.message.reply_text(f"Выбери новый раздел (корень: {root}):", reply_markup=_kb_for_parent(""))
        return PH1_WAIT_SECTION

    comment = None if txt in ("-", "—", "") else txt
    section_path = context.user_data.get("section_path", "")
    photo_bytes  = context.user_data.get("photo_bytes")

    if not photo_bytes:
        await update.message.reply_text("Не нашёл фото. Начните заново: /photo", reply_markup=main_menu())
        return ConversationHandler.END
    if not section_path:
        await update.message.reply_text("Раздел потерян. Попробуйте /photo заново.", reply_markup=main_menu())
        return ConversationHandler.END

    folder = f"{STRUCT_ROOT}/{section_path}" if STRUCT_ROOT else section_path
    leaf = section_path.split("/")[-1]
    public_id = f"{leaf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        up = cloudinary.uploader.upload(photo_bytes, folder=folder, public_id=public_id, resource_type="image")
        url = up["secure_url"]
    except Exception as e:
        await update.message.reply_text(f"✗ Ошибка загрузки в Cloudinary: {e}", reply_markup=main_menu())
        return ConversationHandler.END

    ok, info = _notion_create_row(
        section=format_path_for_notion(section_path), file_name="Фото со стройки", url=url, comment=comment
    )
    if ok:
        await update.message.reply_text("✓ Фото загружено в Cloudinary и добавлено в Notion.",
                                        reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(f"⚠️ Фото загружено, но Notion вернул ошибку: {info}",
                                        reply_markup=ReplyKeyboardRemove())

    await update.message.reply_text("Готово. Что дальше?", reply_markup=main_menu())
    context.user_data.clear()
    return ConversationHandler.END

# ===== Приём данных из WebApp (камера) =====
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    wad = getattr(msg, "web_app_data", None)
    if not wad:
        return

    # Пытаемся распарсить JSON
    try:
        payload = json.loads(wad.data)
    except Exception:
        await msg.reply_text("Не могу прочитать данные камеры.", reply_markup=main_menu())
        return

    # Принимаем только события нашего типа
    if payload.get("type") != "photo_uploaded":
        return

    url     = (payload.get("url") or "").strip()
    section = (payload.get("section") or "—")
    comment = payload.get("comment") or None

    if not url:
        await msg.reply_text("Не получил ссылку на фото из камеры.", reply_markup=main_menu())
        return

    # Защита от дублей (если WebApp прислал 2-3 раза)
    if _seen_recent(url):
        await msg.reply_text("✓ Принято (повтор игнорирован).", reply_markup=main_menu())
        return

    # Пишем строку в Notion
    ok, info = _notion_create_row(
        section=section,
        file_name="Фото (камера)",
        url=url,
        comment=comment
    )

    if ok:
        # Отправляем миниатюру в чат и подтверждение
        try:
            await msg.reply_photo(photo=url, caption=f"✅ Фото загружено и добавлено в Notion.\nРаздел: {section}")
        except Exception:
            await msg.reply_text("✅ Ссылка сохранена в Notion (миниатюру не получилось показать).")
    else:
        await msg.reply_text(f"⚠️ Notion ответил ошибкой: {info}")

    # Возврат к главному меню
    await msg.reply_text("Готово.", reply_markup=main_menu())


# ===== Кнопки вне диалога =====
async def on_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt == BTN_CHANGE:
        root, _ = structure_load_index()
        await update.message.reply_text(f"Выбери раздел проекта (корень: {root}):", reply_markup=_kb_for_parent(""))
        return
    if txt == BTN_CANCEL:
        await update.message.reply_text("Ок, отменил.", reply_markup=main_menu())
        return
    if txt == BTN_ADD_PHOTO:
        # быстрый вход в выбор раздела
        await photo_start(update, context)
        return

# ===== main =====
def main():
    if not BOT_TOKEN: raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в .env")
    if not NOTION_TOKEN or not DATABASE_ID: raise RuntimeError("Нет NOTION_* в .env")

    # Синхронизация структуры при старте (молча в лог)
    try: sync_structure()
    except Exception as e: log.warning(f"Не удалось синхронизировать структуру: {e}")

    structure_load_index()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

        # 1) WEB_APP_DATA — обязательно РАНЬШЕ всего остального
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))

    # 2) Диалог /photo (выбор раздела → фото → комментарий)
    ADD_PHOTO_PATTERN = r"(?i)(?:^|\s)добавить фото$"
    photo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("photo", photo_start),
            MessageHandler(filters.Regex(ADD_PHOTO_PATTERN), photo_start),
        ],
        states={
            PH1_WAIT_SECTION: [CallbackQueryHandler(photo_pick_cb, pattern=r"^(p|b|c)\|")],
            PH2_WAIT_PHOTO:   [
                CallbackQueryHandler(on_ask_gallery, pattern=r"^ask_gallery$"),
                MessageHandler(filters.PHOTO, ph2_photo),
            ],
            PH3_WAIT_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ph3_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="photo_conv",
        persistent=False,
    )
    app.add_handler(photo_conv)

    # 3) Быстрые действия и команды
    app.add_handler(CallbackQueryHandler(photo_quick_start, pattern=r"^go$"))          # опционально
    app.add_handler(CallbackQueryHandler(photo_pick_cb, pattern=r"^(p|b|c)\|"))        # запасной ловец
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sync", cmd_sync))

    # 4) Кнопки вне диалога
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_buttons))
    
    print("Pocket Foreman (Cloudinary -> Notion) — running…")
    app.run_polling(allowed_updates=_RawUpdate.ALL_TYPES)
        
if __name__ == "__main__":
    main()
