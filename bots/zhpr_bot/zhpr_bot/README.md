# 👷 INTELLECTUM — ЖПР-бот (PocketForeman.JPR)

Телеграм-бот для ведения **Журнала производства работ** на стройплощадке.

## 🎯 Назначение

- Ввод записи ЖПР за **30–40 секунд**
- Минимум ручного ввода, максимум автозаполнения
- Строгая структура данных для технадзора, ПТО и руководства
- Полная интеграция с **Notion** и проектом **PocketForeman**

## 🔗 Интеграции

- **Telegram Bot API** — отдельный бот `TELEGRAM_BOT_TOKEN_ZHPR`
- **Notion**:
  - База ЖПР (основной журнал)
  - База вложений (фото, файлы)
- **OpenWeather** — автопогода по городу/координатам

## 🧱 Текущая структура проекта

```text
zhpr_bot/
├── README.md          # это описание (ты здесь)
├── __init__.py        # метка пакета (создадим позже)
├── config.py          # работа с .env и константами Notion/Telegram
├── constants.py       # кнопки, состояния FSM, пути к файлам
├── main.py            # запуск Telegram-бота
│
├── services/          # работа с внешними сервисами
│   ├── notion_jpr.py      # создание записей ЖПР в Notion
│   ├── notion_files.py    # поиск фото в журнале вложений
│   ├── weather_service.py # погодный сервис
│   └── id_generator.py    # генерация ID "ЖПР-YYYYMMDD-XXX"
│
├── structure/
│   └── section_tree.py    # дерево разделов ГПР (structure.txt)
│
├── dialog/            # шаги диалога FSM
│   ├── date_step.py
│   ├── section_step.py
│   ├── subsection_step.py
│   ├── work_step.py
│   ├── people_equip_step.py
│   ├── comment_step.py
│   └── review_step.py
│
└── utils/
    └── keyboards.py       # клавиатуры и вспомогательные функции
