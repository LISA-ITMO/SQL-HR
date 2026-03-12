# SQL-HR

SQL-HR — сервис подбора кандидатов из CSV-базы с LLM (OpenAI-совместимый API), FastAPI и Streamlit.

## Деплой

1. Клонировать репозиторий:
```bash
git clone -b prod-ready https://github.com/JGSnapp/SQL-prod2
cd SQL-prod2
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

## Docker Hub (обход ошибки сборки torch)

1. На машине, где сборка проходит, указать тег в Docker Hub:
```bash
$env:AGENT_SERVER_IMAGE="DOCKERHUB_USERNAME/sql-prod2-agent_server:torch-cpu"
```

2. Авторизоваться и отправить образ:
```bash
docker login
docker compose build agent_server
docker compose push agent_server
```

3. На машине, где падает сборка `torch`, использовать готовый образ:
```bash
$env:AGENT_SERVER_IMAGE="DOCKERHUB_USERNAME/sql-prod2-agent_server:torch-cpu"
docker compose pull agent_server
docker compose up -d --no-build
```
