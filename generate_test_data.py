"""
generate_test_data.py
=====================

Заполняет CRM-базу реалистичными тестовыми данными:
  - ~1000 клиентов (русские имена, компании, телефоны, email)
  - ~1000 сделок (названия, статусы, суммы)
  - ~1000 задач (названия, приоритеты, дедлайны)

Запуск:  python generate_test_data.py
Требуется: запущен FastAPI-сервер на http://127.0.0.1:8000
"""
from __future__ import annotations

import random
import sys
import time
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API = "http://127.0.0.1:8000"


# =====================================================================
#  HTTP-хелпер
# =====================================================================

def api_post(path: str, body: dict) -> dict:
    url = f"{API}{path}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, method="POST",
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {err}")


# =====================================================================
#  Генератор реалистичных данных
# =====================================================================

FIRST_NAMES_M = [
    "Александр", "Дмитрий", "Максим", "Сергей", "Андрей",
    "Алексей", "Артем", "Илья", "Кирилл", "Михаил",
    "Даниил", "Никита", "Егор", "Владислав", "Роман",
    "Тимур", "Иван", "Павел", "Николай", "Виктор",
]

FIRST_NAMES_F = [
    "Анна", "Мария", "Елена", "Ольга", "Наталья",
    "Ирина", "Екатерина", "Светлана", "Юлия", "Татьяна",
    "Дарья", "Алина", "Виктория", "Полина", "Ксения",
    "Валентина", "Галина", "Людмила", "Марина", "Оксана",
]

LAST_NAMES_M = [
    "Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов",
    "Попов", "Васильев", "Соколов", "Михайлов", "Новиков",
    "Федоров", "Морозов", "Волков", "Алексеев", "Лебедев",
    "Семёнов", "Егоров", "Павлов", "Козлов", "Степанов",
]

LAST_NAMES_F = [
    "Иванова", "Петрова", "Сидорова", "Смирнова", "Кузнецова",
    "Попова", "Васильева", "Соколова", "Михайлова", "Новикова",
    "Федорова", "Морозова", "Волкова", "Алексеева", "Лебедева",
    "Семёнова", "Егорова", "Павлова", "Козлова", "Степанова",
]

COMPANIES = [
    "ООО «СтройИнвест»", "ООО «ТехноПром»", "ЗАО «Альфа-Групп»",
    "ООО «ГлобалТрейд»", "АО «МегаСтрой»", "ООО «ФармЛайн»",
    "ООО «Консалт-Плюс»", "ООО «ДатаСолюшнс»", "ЗАО «РосЛогистик»",
    "ООО «ЭнергоСервис»", "ООО «АгроХим»", "ООО «МедиаСофт»",
    "АО «ИнтехГрупп»", "ООО «ПромСервис»", "ООО «Логистика Плюс»",
    "ООО «РитейлДевелопмент»", "ООО «ФудТрейд»", "ООО «НефтеГазСервис»",
    "ООО «АэроТранс»", "ООО «КлинингСервис»", "ООО «ЛандшафтДизайн»",
    "ООО «ЭкоСтрой»", "ООО «МеталлТрейд»", "ООО «ИнфоКом»",
    "ООО «БизнесКонсалтинг»", "ООО «АвтоДетали»", "ООО «Фармацевт»",
    "ООО «СистемПро»", "ООО «ПроектМонтаж»", "ООО «ТоргСервис»",
]

DEAL_TITLES = [
    "Поставка оборудования", "Контракт на обслуживание", "Проектная документация",
    "Поставка стройматериалов", "Лицензия на ПО", "Консалтинговое обслуживание",
    "Монтаж и пусконаладка", "Грант на разработку", "Тендер на поставку",
    "Сервисный контракт", "Договор субподряда", "Аренда спецтехники",
    "Обучение персонала", "IT-аутсорсинг", "Дизайн-проект",
    "Поставка медикаментов", "Логистическое обслуживание", "Аудит предприятия",
    "Строительство объекта", "Модернизация производства",
    "Поставка мебели", "Дизайн интерьера", "Маркетинговое исследование",
    "Бухгалтерское обслуживание", "Юридическое сопровождение",
    "Поставка компьютерной техники", "Настройка серверов",
    "Разработка CRM-системы", "Техническое обслуживание",
    "Организация мероприятия",
]

DEAL_STATUSES = ["new", "new", "in_progress", "in_progress", "closed", "closed", "cancelled"]

TASK_TITLES = [
    "Подготовка коммерческого предложения", "Согласование договора",
    "Встреча с заказчиком", "Проведение презентации",
    "Сбор технической документации", "Согласование сметы",
    "Проверка качества поставки", "Оформление закрывающих документов",
    "Проведение обучения", "Техническая поддержка",
    "Мониторинг выполнения работ", "Инвентаризация",
    "Подготовка отчёта для руководства", "Участие в тендере",
    "Обзвон клиентов", "Обновление базы данных",
    "Проверка сроков поставки", "Контроль бюджета проекта",
    "Подготовка акта выполненных работ", "Согласование условий оплаты",
    "Настройка CRM-системы", "Анализ конкурентов",
    "Разработка стратегии продаж", "Проведение переговоров",
    "Составление плана мероприятий",
]

TASK_STATUSES = ["pending", "pending", "in_progress", "in_progress", "completed"]

TASK_PRIORITIES = ["low", "normal", "normal", "high", "urgent"]

NOTES = [
    "Постоянный клиент", "Первичный контакт", "Запрос цены",
    "Ожидание решения", "Требует внимания", "Перенос встречи",
    "Дополнительные требования", "Срочный заказ", "Рассрочка",
    "Партнёрская программа", "Рекомендация от партнёра", "Участник выставки",
    "Нужна скидка", "Долг просрочен", "Положительная обратная связь",
    "Запрос на доп. услуги", "Ожидание поставки", "Проверка документации",
]


def random_phone():
    codes = ["903", "916", "926", "905", "963", "915", "925", "909", "977", "999",
             "495", "499", "812", "817", "343"]
    return f"+7 ({random.choice(codes)}) {random.randint(100,999)}-{random.randint(10,99)}-{random.randint(10,99)}"


def random_email(first: str, last: str):
    domains = ["gmail.com", "mail.ru", "yandex.ru", "inbox.ru", "bk.ru"]
    return f"{first.lower()}.{last.lower()}@{random.choice(domains)}"


def random_date(start_year=2024, end_year=2026):
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    year = random.randint(start_year, end_year)
    return f"{year}-{month:02d}-{day:02d}"


def random_amount():
    return round(random.uniform(50_000, 5_000_000), 2)


# =====================================================================
#  Генерация и отправка
# =====================================================================

def generate_clients(n: int = 1000) -> list[dict]:
    clients = []
    for _ in range(n):
        use_m = random.random() < 0.5
        first = random.choice(FIRST_NAMES_M if use_m else FIRST_NAMES_F)
        last = random.choice(LAST_NAMES_M if use_m else LAST_NAMES_F)
        company = random.choice(COMPANIES)
        clients.append({
            "first_name": first,
            "last_name": last,
            "phone": random_phone(),
            "email": random_email(first, last),
            "status": random.choice(["active", "active", "active", "archived"]),
            "notes": f"{company}. {random.choice(NOTES)}",
        })
    return clients


def generate_deals(n: int = 1000, client_ids: list[int] | None = None) -> list[dict]:
    deals = []
    for _ in range(n):
        cid = random.choice(client_ids) if client_ids else random.randint(1, n)
        deals.append({
            "client_id": cid,
            "title": random.choice(DEAL_TITLES),
            "status": random.choice(DEAL_STATUSES),
            "amount": random_amount(),
            "description": f"Сделка #{random.randint(1000, 9999)}. {random.choice(NOTES)}",
        })
    return deals


def generate_tasks(n: int = 1000, client_ids: list[int] | None = None,
                   deal_ids: list[int] | None = None) -> list[dict]:
    tasks = []
    for _ in range(n):
        cid = random.choice(client_ids) if client_ids else random.randint(1, n)
        did = random.choice(deal_ids) if deal_ids else random.randint(1, n)
        tasks.append({
            "client_id": cid,
            "deal_id": did,
            "title": random.choice(TASK_TITLES),
            "status": random.choice(TASK_STATUSES),
            "priority": random.choice(TASK_PRIORITIES),
            "due_date": random_date(),
            "description": random.choice(NOTES),
        })
    return tasks


def bulk_insert(items: list[dict], path: str, label: str):
    total = len(items)
    batch = 50
    created = 0
    for i in range(0, total, batch):
        chunk = items[i : i + batch]
        try:
            for item in chunk:
                api_post(path, item)
                created += 1
        except RuntimeError as e:
            # Если дубликат или ошибка валидации — пропускаем и продолжаем
            pass
        if (i // batch + 1) % 10 == 0 or created == total:
            pct = min(100, created * 100 // total)
            print(f"  [{label}] {created}/{total} ({pct}%)  {time.strftime('%H:%M:%S')}")


def main():
    print("=" * 60)
    print("  Заполнение CRM тестовыми данными")
    print("=" * 60)

    # 1) Клиенты
    print("\n[1/3] Генерация клиентов...")
    clients = generate_clients(1000)
    print("[1/3] Отправка в API...")
    bulk_insert(clients, "/clients", "Клиенты")

    # 2) Сделки
    print("\n[2/3] Генерация сделок...")
    deals = generate_deals(1000)
    print("[2/3] Отправка в API...")
    bulk_insert(deals, "/deals", "Сделки")

    # 3) Задачи
    print("\n[3/3] Генерация задач...")
    tasks = generate_tasks(1000)
    print("[3/3] Отправка в API...")
    bulk_insert(tasks, "/tasks", "Задачи")

    print("\n" + "=" * 60)
    print("  Готово! Данные записаны.")
    print("=" * 60)


if __name__ == "__main__":
    main()
