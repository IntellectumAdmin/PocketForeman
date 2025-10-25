# -*- coding: utf-8 -*-
"""
Pocket Foreman: Cloudinary -> Notion
- Авто /sync при старте (чтение structure.txt, создание папок в Cloudinary, кэш)
- Авто-приветствие + кнопка «📸 Добавить фото» без /start
- /photo: выбрать раздел -> фото -> (опц.) комментарий -> Cloudinary -> запись в Notion
"""

import os
import io
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple


from structure_safe_sync import start_safe_sync


from dotenv import load_dotenv
import requests
import cloudinary
import cloudinary.uploader

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ===== Логи =====

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pf-bot")
log.setLevel(logging.INFO)

# Прижмём «шумные» библиотеки
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("cloudinary").setLevel(logging.WARNING)

# ===== .env =====
load_dotenv()

# === Notion ===
NOTION_TOKEN = os.getenv("NOTION_TOKEN_SCHOOL65", "")
DATABASE_ID  = os.getenv("NOTION_DATABASE_ID_SCHOOL65", "")

# === Cloudinary ===
CLOUD_NAME     = os.getenv("CLOUD_NAME", "")
CLOUD_API_KEY  = os.getenv("CLOUD_API_KEY", "")
CLOUD_API_SECRET = os.getenv("CLOUD_API_SECRET", "")
CLOUD_ROOT     = os.getenv("CLOUD_ROOT", "Project")

# === Telegram ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# === Колонки в Notion ===
PROP_SECTION = os.getenv("PROP_SECTION", "Раздел")
PROP_FILE    = os.getenv("PROP_FILE", "Файл / Фото")
PROP_URL     = os.getenv("PROP_URL", "Ссылка OneDrive")  # сюда кладём ссылку Cloudinary
PROP_DATE    = os.getenv("PROP_DATE", "Дата")
PROP_COMMENT = os.getenv("PROP_COMMENT", "Комментарий")

# === Кэш структуры ===
STRUCTURE_CACHE = "structure_cache.json"

# ==== Главное меню (reply-клавиатура) ====
BTN_ADD_PHOTO = "📸 Добавить фото"

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(BTN_ADD_PHOTO)]], resize_keyboard=True)

# Показывает главное меню, если пользователь пишет любой текст вне диалога
async def ensure_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ничего «умного» не делаем — просто возвращаем клавиатуру
    await update.message.reply_text("Выберите действие:", reply_markup=main_menu())

def quick_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📸 Добавить фото", callback_data="go")]])

# ===== Cloudinary config =====
if not (CLOUD_NAME and CLOUD_API_KEY and CLOUD_API_SECRET):
    raise RuntimeError("Заполни CLOUD_NAME/CLOUD_API_KEY/CLOUD_API_SECRET в .env")
cloudinary.config(
    cloud_name=CLOUD_NAME,
    api_key=CLOUD_API_KEY,
    api_secret=CLOUD_API_SECRET,
    secure=True,
)

# ===== Notion headers =====
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ===== Состояния разговора =====
PH1_WAIT_SECTION, PH2_WAIT_PHOTO, PH3_WAIT_COMMENT = range(100, 103)

# ====== Синхронизация структуры при старте ======
# делаем тут импорт, чтобы модуль был рядом с ботом
from structure_sync import sync_structure

try:
    info = sync_structure()
    log.info(f"✓ Структура синхронизирована при старте. Корень: {info['root']}, разделов: {len(info['paths'])}")
except Exception as e:
    log.warning(f"⚠️ Не удалось автоматически синхронизировать структуру: {e}")

# ====== Меню разделов: дерево из кэша ======
# Файл structure_cache.json создаётся /sync. Формат:
# {"root": "Школа_65", "paths": ["Здание школы/Архитектурная часть/Фасады", ...]}

from pathlib import Path

STRUCTURE_CACHE_PATH = Path("structure_cache.json")
STRUCT_ROOT = "Школа_65"     # если в кэше будет другой root — перезапишем ниже
STRUCT_INDEX: Dict[str, List[str]] = {}  # parent_path -> [child_name, ...]

def _build_index(paths: List[str]) -> Dict[str, List[str]]:
    """
    Из списка 'A/B/C' строим индекс:
      "" -> ["A", ...]
      "A" -> ["B", ...]
      "A/B" -> ["C", ...]
    """
    idx: Dict[str, set] = {}
    for p in paths:
        parts = [s.strip() for s in p.split("/") if s.strip()]
        for i in range(len(parts)):
            parent = "/".join(parts[:i])
            child  = parts[i]
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
    """Дети у данного 'parent_path' ('', 'A', 'A/B', ...)"""
    return STRUCT_INDEX.get(parent_path, [])

def format_path_for_notion(path_str: str) -> str:
    """Путь 'A/B/C' -> 'A / B / C' (как в колонке «Раздел» в Notion)"""
    parts = [s for s in path_str.split("/") if s]
    return " / ".join(parts)

# ===== Регистратор коротких id для путей (чтобы уложиться в 64 байта callback_data) =====
PATH2ID: Dict[str, str] = {}
ID2PATH: Dict[str, str] = {}
ID_SEQ = 1

def _id_for_path(path: str) -> str:
    """Выдаёт короткий id для пути 'A/B/C' и кэширует соответствие."""
    global ID_SEQ
    if path not in PATH2ID:
        PATH2ID[path] = str(ID_SEQ)
        ID2PATH[str(ID_SEQ)] = path
        ID_SEQ += 1
    return PATH2ID[path]

def _path_by_id(pid: str) -> str:
    """Возвращает путь по короткому id (или пустую строку)."""
    return ID2PATH.get(pid, "")

# ===== Notion =====
def _notion_create_row(section: str, file_name: str, url: str, comment: Optional[str]) -> Tuple[bool, str]:
    today_iso = datetime.now().strftime("%Y-%m-%d")
    props: Dict[str, Any] = {
        PROP_SECTION: {"select": {"name": section}},
        PROP_FILE:    {"rich_text": [{"text": {"content": file_name}}]},
        PROP_URL:     {"url": url},
        PROP_DATE:    {"date": {"start": today_iso}},
    }
    if comment:
        props[PROP_COMMENT] = {"rich_text": [{"text": {"content": comment}}]}

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": props}
    r = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
    if r.status_code in (200, 201):
        return True, "ok"
    try:
        return False, r.json().get("message", r.text)
    except Exception:
        return False, r.text

# ===== /start (оставили для совместимости) =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👷 Привет! Я Карманный Прораб.\n"
        "Нажми кнопку ниже, чтобы добавить фото к нужному разделу проекта:",
        reply_markup=main_menu()
    )
    await update.message.reply_text("Быстрые действия:", reply_markup=quick_inline_menu())

# ===== Автоприветствие при первом сообщении без команд =====
async def on_first_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Показываем приветствие только один раз на пользователя
    if context.user_data.get("welcomed"):
        return
    context.user_data["welcomed"] = True

    if update.message:
        await update.message.reply_text(
            "👷 Привет! Я Карманный Прораб.\n"
            "Нажми кнопку ниже, чтобы добавить фото:",
            reply_markup=main_menu()
        )
        await update.message.reply_text("Быстрые действия:", reply_markup=quick_inline_menu())

# ===== /sync (для ручного вызова админом, но не требуется пользователю) =====
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Синхронизация структуры…")
    try:
        info = sync_structure()
        await update.message.reply_text(
            f"✓ Готово. Корень: {info['root']}\nРазделов: {len(info['paths'])}",
            reply_markup=main_menu()
        )
    except Exception as e:
        await update.message.reply_text(f"✗ Ошибка синхронизации: {e}")

# ===== Клавиатуры для выбора разделов =====
def _kb_for_parent(parent_path: str) -> InlineKeyboardMarkup:
    """
    Клавиатура для уровня parent_path:
      - дочерние папки (2 в ряд),
      - ⬅️ Назад,
      - ✅ Выбрать здесь.
    В callback_data передаём только короткие id.
    """
    children = structure_children(parent_path)
    rows: List[List[InlineKeyboardButton]] = []

    row: List[InlineKeyboardButton] = []
    for name in children:
        full = f"{parent_path}/{name}" if parent_path else name
        pid = _id_for_path(full)
        row.append(InlineKeyboardButton(f"📂 {name}", callback_data=f"p|{pid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    ctrl: List[InlineKeyboardButton] = []
    if parent_path:
        parent_parent = "/".join(parent_path.split("/")[:-1])
        bid = _id_for_path(parent_parent)
        ctrl.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"b|{bid}"))
    cid = _id_for_path(parent_path)
    ctrl.append(InlineKeyboardButton("✅ Выбрать здесь", callback_data=f"c|{cid}"))
    rows.append(ctrl)

    return InlineKeyboardMarkup(rows)

# ===== Запуск выбора по инлайн-кнопке "go" =====
async def photo_quick_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # очищаем состояние и показываем корневые разделы
    context.user_data.clear()
    context.user_data["cursor_path"] = ""
    root, _ = structure_load_index()

    if not STRUCT_INDEX:
        await query.edit_message_text("Похоже, список разделов пустой. Запусти /sync.")
        return

    await query.edit_message_text(f"Выбери раздел проекта (корень: {root}):")
    await query.message.reply_text(
        text="Навигация по разделам:",
        reply_markup=_kb_for_parent("")
    )
    return PH1_WAIT_SECTION

# ===== /photo (вход через команду или reply-кнопку) =====
async def photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["cursor_path"] = ""
    root, _ = structure_load_index()

    if not STRUCT_INDEX:
        await update.message.reply_text("Похоже, список разделов пустой. Нажми /sync, чтобы обновить структуру.")
        return ConversationHandler.END

    await update.message.reply_text(
        f"Выбери раздел проекта (корень: {root}):",
        reply_markup=_kb_for_parent("")
    )
    return PH1_WAIT_SECTION

async def photo_pick_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка инлайн-кнопок:
      p|<id>  -> спуститься в путь с этим id
      b|<id>  -> подняться к пути с этим id
      c|<id>  -> выбрать путь с этим id и перейти к шагу «фото»
    """
    query = update.callback_query
    await query.answer()

    data = (query.data or "").strip()
    act, _, pid = data.partition("|")
    path = _path_by_id(pid)

    # Защитимся от устаревших callback'ов
    if act in ("p", "b", "c") and path is None:
        await query.answer("Меню устарело, начните заново: /photo", show_alert=True)
        return PH1_WAIT_SECTION

    if act == "p":
        context.user_data["cursor_path"] = path
        text = f"Раздел: {format_path_for_notion(path) if path else 'Корень'}\nВыбери подраздел:"
        await query.edit_message_text(text=text, reply_markup=_kb_for_parent(path))
        return PH1_WAIT_SECTION

    if act == "b":
        context.user_data["cursor_path"] = path
        text = f"Раздел: {format_path_for_notion(path) if path else 'Корень'}\nВыбери подраздел:"
        await query.edit_message_text(text=text, reply_markup=_kb_for_parent(path))
        return PH1_WAIT_SECTION

    if act == "c":
        if not path:
            await query.answer("Нужно выбрать хоть какой-то раздел.", show_alert=True)
            return PH1_WAIT_SECTION
        context.user_data["section_path"] = path
        nice = format_path_for_notion(path)
        await query.edit_message_text(
            f"✅ Раздел выбран:\n{nice}\n\nТеперь пришли фото одним сообщением (как изображение)."
        )
        return PH2_WAIT_PHOTO

    await query.answer("Неизвестная команда.", show_alert=True)
    return PH1_WAIT_SECTION

async def ph2_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Это не фото. Пришли изображение.")
        return PH2_WAIT_PHOTO

    photo = update.message.photo[-1]
    file = await photo.get_file()
    bio = io.BytesIO()
    await file.download_to_memory(out=bio)
    bio.seek(0)

    context.user_data["photo_bytes"] = bio.read()
    await update.message.reply_text("Комментарий (опционально) или «-»:")
    return PH3_WAIT_COMMENT

async def ph3_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment_raw = (update.message.text or "").strip()
    comment = None if comment_raw in ("-", "—", "") else comment_raw

    section_path = context.user_data.get("section_path", "")
    photo_bytes  = context.user_data.get("photo_bytes")

    if not photo_bytes:
        await update.message.reply_text("Не нашёл фото в сессии. Начни заново: /photo")
        return ConversationHandler.END

    if not section_path:
        await update.message.reply_text("Раздел потерян. Попробуй /photo заново.")
        return ConversationHandler.END

    # Загрузка в Cloudinary
    folder = f"{STRUCT_ROOT}/{section_path}" if STRUCT_ROOT else section_path
    leaf = section_path.split("/")[-1]
    public_id = f"{leaf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        up = cloudinary.uploader.upload(
            photo_bytes,
            folder=folder,
            public_id=public_id,
            resource_type="image",
        )
        url = up["secure_url"]
    except Exception as e:
        await update.message.reply_text(f"✗ Ошибка загрузки в Cloudinary: {e}")
        return ConversationHandler.END

    # Запись в Notion
    section_for_notion = format_path_for_notion(section_path)
    ok, info = _notion_create_row(
        section=section_for_notion,
        file_name="Фото со стройки",
        url=url,
        comment=comment,
    )
    if ok:
        await update.message.reply_text("✓ Фото загружено в Cloudinary и добавлено в Notion.")
    else:
        await update.message.reply_text(f"⚠️ Фото загружено, но Notion вернул ошибку: {info}")

    await update.message.reply_text("Готово. Что дальше?", reply_markup=main_menu())
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Операция отменена.", reply_markup=main_menu())
    return ConversationHandler.END

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN в .env")
    if not NOTION_TOKEN or not DATABASE_ID:
        raise RuntimeError("Нет NOTION_TOKEN_SCHOOL65 / NOTION_DATABASE_ID_SCHOOL65 в .env")

    # загрузим индекс структуры один раз при старте
    root, _ = structure_load_index()
    old_root, paths = root, []  # для печати

    print("=======================================")
    print("INTELLECTUM — Pocket Foreman (Cloudinary → Notion)")
    print(f"Подключено к базе: Школа 65 — Уральск")
    print(f"Notion база ID: {DATABASE_ID[:8]}...{DATABASE_ID[-5:]}")
    print(f"Cloudinary: {cloudinary.config().cloud_name}")
    print(f"Корень Cloudinary: {root}")
    print("=======================================")

    # ---- Автонаблюдение за изменениями structure.txt ----
    # def _on_synced(_info: dict):
    # при желании можно тут добавить логику уведомлений админу
    #     pass

    # start_watcher(on_synced=_on_synced)
    # ------------------------------------------------------

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    admin_chat_id = int(os.getenv("ADMIN_CHAT_ID", "0"))

    # создаём отложенный запуск Safe-Sync через JobQueue
    def _start_safe_sync_once(context):
        safe_sync = start_safe_sync(app, admin_chat_id=admin_chat_id)
        app.bot_data["safe_sync"] = safe_sync
        print("[SafeSync] ✅ Запущен наблюдатель за structure.txt")

    # регистрируем задачу на запуск SafeSync через 1 секунду
    app.job_queue.run_once(_start_safe_sync_once, 1.0)

    # обработчик inline-кнопок
    async def _on_safe_sync_callback(update, context):
        ss = context.application.bot_data.get("safe_sync")
        if ss:
            await ss.on_callback(update, context)

    app.add_handler(CallbackQueryHandler(
        _on_safe_sync_callback,
        pattern=r"^safesync:(apply|cancel)\|\d+$"
    ))

    # --- конец SafeSync вставки ---


    # /photo диалог
    # паттерн ловит и "📸 Добавить фото", и "Добавить фото", и "добавить фото"
    ADD_PHOTO_PATTERN = r"(?i)(?:^|\s)добавить фото$"

    photo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("photo", photo_start),
            MessageHandler(filters.Regex(ADD_PHOTO_PATTERN), photo_start),
        ],
        states={
            PH1_WAIT_SECTION: [CallbackQueryHandler(photo_pick_cb, pattern=r"^(p|b|c)\|")],
            PH2_WAIT_PHOTO:   [MessageHandler(filters.PHOTO, ph2_photo)],
            PH3_WAIT_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ph3_comment)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="photo_conv",
        persistent=False,
        # per_message=False  # просто удаляем эту строку
   )

    


    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sync", cmd_sync))

    # СНАЧАЛА диалог /photo и инлайн-кнопка "go"
    app.add_handler(photo_conv)
    app.add_handler(CallbackQueryHandler(photo_quick_start, pattern=r"^go$"))

    # ПОТОМ общий обработчик любого текста (меню)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ensure_menu))


    
    log.info("Pocket Foreman (Cloudinary -> Notion) is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
