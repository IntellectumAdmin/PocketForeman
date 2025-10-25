# Простой скрипт для онлайн-вахты INTELLECTUM
# Функции: напоминания, фиксация рисков, XAI-трассировка
# Для школы №65, чтобы прорабы получали уведомления и логи

from datetime import datetime, timedelta
import json

# Функция для создания напоминания
def create_reminder(task, deadline):
    reminders = []
    reminder_time = datetime.strptime(deadline, "%Y-%m-%d") - timedelta(days=1)
    reminders.append({"task": task, "reminder": reminder_time.strftime("%Y-%m-%d")})
    return reminders

# Функция для фиксации риска
def log_risk(task, issue):
    risk_log = {
        "task": task,
        "issue": issue,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return risk_log

# Функция для XAI-трассировки (объяснимость)
def xai_trace(task, action, source):
    return f"XAI-трассировка: Задача '{task}', Действие: {action}, Источник: {source}, Grok 17.09.2025"

# Пример для школы №65
tasks = [
    {"name": "Проверить бетон", "deadline": "2025-09-20"},
    {"name": "Поставка кирпича", "deadline": "2025-09-25"}
]

# Создаём напоминания
for task in tasks:
    reminders = create_reminder(task["name"], task["deadline"])
    print(f"Напоминание: {reminders[0]['task']} — за день до {reminders[0]['reminder']}")

# Фиксируем риск
risk = log_risk("Проверить бетон", "Задержка поставки на 3 дня")
print("Риск зафиксирован:", json.dumps(risk, ensure_ascii=False))

# XAI-трассировка для прозрачности
trace = xai_trace("Проверить бетон", "Создано напоминание и риск", "Данные Notion школы №65")
print(trace)