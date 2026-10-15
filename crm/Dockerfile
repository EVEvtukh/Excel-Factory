FROM python:3.12-slim

# Установить зависимости из requirements.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Создать рабочую директорию
WORKDIR /app

# Скопировать код (базовый слой — для кэша Docker)
COPY crm/ /app/crm/

# Порт API
EXPOSE 8000

# Запуск uvicorn с автоперезапуском при изменении файлов
CMD ["uvicorn", "crm.crm_api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
