# SQL-HR

SQL-HR — сервис подбора кандидатов из CSV-базы с LLM (OpenAI-совместимый API), FastAPI и Streamlit.

## Исследовательская ветка `research/track-b-paper-02.1`

Ветка предназначена для подготовки статьи по первому этапу трека B — [02.1: соответствие кандидата роли, поиск и оценка свидетельств](docs/track-b/02.1_neurosymbolic_evidence_assessment/README.md). Общая навигация по исследованию — в [материалах трека B](docs/track-b/README.md).

Текущий [английский черновик статьи](docs/track-b/literature/paper.docx) пока охватывает более широкий трек B и готовится как задание по английскому языку в аспирантуре. В дальнейшем он станет основой исследовательской статьи: постановку и текст планируется сузить под этап 02.1. В обновлении от 19.11.2026 добавлены два абзаца; новых источников не добавлено. Черновик не означает, что метод и эксперименты этапа 02.1 уже завершены.

Рядом находятся [рабочий обзор литературы](docs/track-b/literature/paper.md), [библиография](docs/track-b/literature/references.md) и [матрица литературы](docs/track-b/literature/track-b-literature-matrix.xlsx).

## Деплой

1. Клонировать репозиторий и дать разрешения:
```bash
git clone -b main https://github.com/LISA-ITMO/SQL-HR
cd SQL-HR
mkdir -p results

# Для Linux
chmod 777 data results
chmod 755 db
```

2. Скопировать `candidates.csv` в папку `data/`.

3. Переименовать 'example.env' в `.env` заполнить поля `MODEL`, `API_KEY`, `BASE_URL`.
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
