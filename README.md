# SQL-HR

SQL-HR — сервис подбора кандидатов из CSV-базы с LLM (OpenAI-совместимый API), FastAPI и Streamlit.

## Деплой

1. Клонировать репозиторий и дать разрешения:
```bash
git clone -b prod-ready https://github.com/JGSnapp/SQL-prod2
cd SQL-prod2
mkdir -p results

# Для Linux
chmod 777 data results
chmod 755 db
```

2. Скопировать `candidates.csv` в папку `data/`.

3. В `.env` заполнить поля `MODEL`, `API_KEY`, `BASE_URL`.
Текущее значение:
```env
MODEL=gpt-oss:120b
API_KEY=secret_key
BASE_URL=http://192.168.103.19:11434/v1
```

4. Запуск:
```bash
docker-compose up --build
```

5. Чтобы пересоздать БД:
- остановить сервисы:
```bash
docker-compose down
```
- удалить данные Postgres из папки `db/postgres`.

6. Запустить заново:
```bash
docker-compose up --build
```