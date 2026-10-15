# Excelio CRM

Мини-CRM-система для ведения клиентов, сделок и задач с интеграцией Google Sheets/Drive для выгрузки отчётов.

## Структура

```
Excelio/
├── crm/                    # CRM-модуль
│   ├── crm_database.py     # SQLite-модели (clients, deals, tasks) + CRUD
│   ├── crm_api.py          # FastAPI REST-эндпоинты (port 8000)
│   ├── crm_app.py          # Tkinter GUI (вкладки Клиенты/Сделки/Задачи)
│   ├── crm_google_settings.py  # Сохранение настроек Google
│   ├── Dockerfile          # Контейнер API
│   └── __init__.py
├── sheets/                 # Google Sheets / Drive интеграция
│   ├── google_sheets_client.py       # Service Account Sheets API
│   ├── google_drive_client.py        # Service Account Drive API
│   ├── google_drive_user_client.py   # OAuth2 Drive API (личный аккаунт)
│   ├── google_sheets_user_client.py  # OAuth2 Sheets API (личный аккаунт)
│   └── ...                       # Старый генератор отчётов
├── credentials/            # OAuth2 + Service Account ключи (не коммитить!)
├── docker-compose.yml      # Запуск API в Docker
├── generate_test_data.py   # Генератор тестовых данных
├── requirements.txt        # Зависимости Python
└── config.example.json     # Шаблон конфига
```

## Быстрый старт

### 1. Установка зависимостей

```powershell
pip install -r requirements.txt
```

### 2. Запуск API (Docker)

```powershell
docker compose up -d
```

API доступен по адресу: `http://127.0.0.1:8000`
Документация Swagger: `http://127.0.0.1:8000/docs`

### 3. Запуск GUI

```powershell
python crm/crm_app.py
```

GUI подключается к API через `http://127.0.0.1:8000`.

### 4. Тестовые данные

Для заполнения базы ~1000 записей в каждую таблицу:

```powershell
python generate_test_data.py
```

## Google Sheets / Drive экспорт

Для выгрузки отчётов из GUI в Google Sheets:

### Настройка

1. Нажмите **«⚙ Google»** в статус-баре или **«Выгрузить отчёт»** на любой вкладке
2. В открывшемся окне укажите:
   - **Client Secret** — нажмите **«Обзор...»** и выберите `client_secret_*.json`
   - **Folder ID** — ID папки на Google Drive (необязательно, пустое = корень)
3. Нажмите **«Сохранить»**

### Авторизация

При первом экспорте откроется браузер для OAuth2-согласия. Токен кэшируется локально, повторный вход не требуется.

## Конфигурация

| Файл | Описание |
|---|---|
| `config.json` | Конфиг для старой генерации отчётов (credentials + spreadsheet ID) |
| `~/.excelio_crm_settings.txt` | Настройки CRM (client secret path + folder ID) |
| `sheets/token.json` | OAuth2-токен для Drive API |
| `sheets/token_sheets.json` | OAuth2-токен для Sheets API |

## Безопасность

**НИКОГДА не коммитьте файлы:**
- `credentials/` — все JSON-ключи
- `config.json` — реальные ID и пути
- `crm.db` — база данных клиентов
- `sheets/token*.json` — кэш OAuth-токенов

Эти файлы уже добавлены в `.gitignore`.

## API эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| GET | `/clients` | Список клиентов |
| POST | `/clients` | Создать клиента |
| PATCH | `/clients/{id}` | Обновить клиента |
| POST | `/clients/{id}/archive` | Архивировать |
| DELETE | `/clients/{id}` | Удалить |
| GET | `/deals` | Список сделок |
| POST | `/deals` | Создать сделку |
| PATCH | `/deals/{id}` | Обновить сделку |
| DELETE | `/deals/{id}` | Удалить |
| GET | `/tasks` | Список задач |
| POST | `/tasks` | Создать задачу |
| PATCH | `/tasks/{id}` | Обновить задачу |
| POST | `/tasks/{id}/complete` | Отметить выполненной |
| DELETE | `/tasks/{id}` | Удалить |

Полный список: `http://127.0.0.1:8000/docs`

## License

Personal / Internal Use Only
