# -*- coding: utf-8 -*-
"""
Safe-Sync: наблюдение за structure.txt с подтверждением админом.
- Отслеживает изменения файла (watchdog)
- Считает diff (добавлено / убрано)
- Присылает админу запрос на подтверждение с inline-кнопками
- По подтверждению вызывает sync_structure() и пересобирает кэш
ВНИМАНИЕ: НИЧЕГО НЕ УДАЛЯЕМ В CLOUDINARY. Это мягкая синхронизация.
"""

from __future__ import annotations
import os
import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# наш старый модуль синхронизации
from structure_sync import sync_structure

STRUCTURE_FILE = Path(os.getenv("STRUCTURE_FILE", "structure.txt"))
CACHE_FILE     = Path("structure_cache.json")

# ---------------- utils ----------------

def _read_cache_paths() -> Tuple[str, List[str]]:
    if CACHE_FILE.exists():
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data.get("root", ""), data.get("paths", [])
    return "", []

def _parse_structure_txt(path: Path) -> List[str]:
    """
    Упрощённый парсер: каждая строка — узел (с отступами по 2 пробела),
    как вы уже используете.
    """
    if not path.exists():
        return []
    lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines()]
    paths, stack = [], []
    for ln in lines:
        if not ln.strip():
            continue
        raw = ln.rstrip("/")
        level = 0
        while raw.startswith("  " * (level + 1)):
            level += 1
        name = raw.replace("  " * level, "", 1).strip("/").strip()
        stack = stack[:level] + [name]
        paths.append("/".join(stack))
    # уникализируем
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            out.append(p); seen.add(p)
    return out

def _diff(old_paths: List[str], new_paths: List[str]) -> Dict[str, List[str]]:
    old_set, new_set = set(old_paths), set(new_paths)
    added   = sorted(list(new_set - old_set))
    removed = sorted(list(old_set - new_set))
    common  = sorted(list(old_set & new_set))
    return {"added": added, "removed": removed, "same": common}

def _format_diff_text(root: str, d: Dict[str, List[str]]) -> str:
    parts = []
    parts.append(f"⚙️ Изменения в структуре (root: {root}):")
    parts.append(f"➕ Добавится: {len(d['added'])}")
    if d["added"]:
        parts += [f"  • {p}" for p in d["added"][:10]]
        if len(d["added"]) > 10:
            parts.append(f"  … и ещё {len(d['added']) - 10}")
    parts.append(f"➖ Исключится из дерева: {len(d['removed'])} (данные не удаляем)")
    if d["removed"]:
        parts += [f"  • {p}" for p in d["removed"][:10]]
        if len(d["removed"]) > 10:
            parts.append(f"  … и ещё {len(d['removed']) - 10}")
    return "\n".join(parts)

# --------------- SafeSync core ---------------

class _DebounceHandler(FileSystemEventHandler):
    def __init__(self, on_change: Callable[[], None], delay: float = 1.0):
        self.on_change = on_change
        self.delay = delay
        self._timer: Optional[threading.Timer] = None

    def on_modified(self, event):
        if event.src_path.endswith(str(STRUCTURE_FILE)):
            self._arm()

    def on_created(self, event):
        if event.src_path.endswith(str(STRUCTURE_FILE)):
            self._arm()

    def _arm(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.delay, self.on_change)
        self._timer.daemon = True
        self._timer.start()

class SafeSync:
    """
    Инкапсулирует наблюдение + подтверждение.
    """
    def __init__(self, application, admin_chat_id: int):
        self.app = application
        self.admin_chat_id = admin_chat_id
        self.observer: Optional[Observer] = None
        self.pending: Dict[int, Dict] = {}  # change_id -> diff/info
        self._seq = 1
        self._lock = threading.Lock()

    # ---- public ----

    def start(self):
        # при старте сразу проверим — вдруг structure.txt уже отличается
        self._check_and_notify()
        # затем включим watchdog
        handler = _DebounceHandler(self._check_and_notify, delay=1.5)
        self.observer = Observer()
        watch_dir = str(STRUCTURE_FILE.parent.resolve())
        self.observer.schedule(handler, watch_dir, recursive=False)
        self.observer.daemon = True
        self.observer.start()

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=3)

    # ---- callbacks from Telegram ----

    async def on_callback(self, update, context):
        """
        Обработчик inline-кнопок вида:
        safesync:apply|<id>  или  safesync:cancel|<id>
        """
        query = update.callback_query
        await query.answer()
        data = (query.data or "")
        try:
            _, payload = data.split(":", 1)
            action, sid = payload.split("|", 1)
            cid = int(sid)
        except Exception:
            return

        if cid not in self.pending:
            await query.edit_message_text("Эта операция уже обработана или устарела.")
            return

        info = self.pending.pop(cid)
        if action == "apply":
            # применяем: просто вызываем существующий sync_structure()
            res = sync_structure()
            txt = (f"✓ Структура обновлена.\n"
                   f"Root: {res['root']}\n"
                   f"Путей в дереве: {len(res['paths'])}\n\n"
                   f"Ранее обнаруженные изменения были применены.")
            await query.edit_message_text(txt)
        else:
            await query.edit_message_text("Операция отменена. Изменения не применялись.")

    # ---- internals ----

    def _next_id(self) -> int:
        with self._lock:
            k = self._seq
            self._seq += 1
            return k

    def _check_and_notify(self):
        """
        Вычисляем diff между текущим кэшем и structure.txt.
        Если есть изменения — отправляем админу подтверждение.
        """
        try:
            root, old_paths = _read_cache_paths()
            new_paths = _parse_structure_txt(STRUCTURE_FILE)
            d = _diff(old_paths, new_paths)
            if not d["added"] and not d["removed"]:
                return  # ничего не менялось

            change_id = self._next_id()
            self.pending[change_id] = {"root": root, "diff": d}
            text = _format_diff_text(root, d)

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Применить", callback_data=f"safesync:apply|{change_id}"),
                InlineKeyboardButton("❌ Отменить",  callback_data=f"safesync:cancel|{change_id}"),
            ]])

            # ПЛАНИРУЕМ отправку через JobQueue (внутри главного event loop)
            async def _notify_job(context):
                try:
                    await context.bot.send_message(
                        chat_id=self.admin_chat_id,
                        text=text,
                        reply_markup=kb
                    )
                except Exception as e:
                    print(f"[SafeSync] Не удалось уведомить админа: {e}")

            # запускаем "сразу" (через 0 сек) — это потокобезопасно
            self.app.job_queue.run_once(_notify_job, when=0)

            print(f"[SafeSync] Обнаружены изменения. Отправлен запрос на подтверждение (id={change_id}).")

            
            

        except Exception as e:
            print(f"[SafeSync] Ошибка при проверке изменений: {e}")

# ---- factory ----

def start_safe_sync(application, admin_chat_id: int) -> SafeSync:
    """
    Создаёт SafeSync, запускает наблюдение и возвращает объект.
    Не забудьте повесить его on_callback на CallbackQueryHandler.
    """
    ss = SafeSync(application, admin_chat_id=admin_chat_id)
    ss.start()
    return ss
