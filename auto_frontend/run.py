#!/usr/bin/env python3
"""
auto_frontend/run.py

Автоматический фронтенд для бенчмаркинга.

Читает запросы из QUERIES_FILE построчно, отправляет каждый в агента,
ждёт результата. Если агент не начал поиск — повторяет с подсказкой
"Ищи так". Сохраняет top-15 кандидатов на каждый запрос в OUTPUT_CSV.

Переменные окружения:
  AGENT_URL     — базовый URL агента  (default: http://localhost:8010)
  QUERIES_FILE  — путь к файлу запросов (default: ../data/queries.txt)
  OUTPUT_CSV    — путь к выходному CSV  (default: ../data/results.csv)
  TOP_K         — сколько кандидатов сохранять (default: 15)
  MAX_ATTEMPTS  — максимум попыток на запрос   (default: 3)
  POLL_INTERVAL — интервал поллинга candidates/current, сек (default: 1.0)
"""

import csv
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from textwrap import dedent

import requests

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_URL", "http://localhost:8010")

_script_dir = os.path.dirname(os.path.abspath(__file__))
_data_dir   = os.path.join(_script_dir, "..", "data")

QUERIES_FILE  = os.getenv("QUERIES_FILE",  os.path.join(_data_dir, "queries.txt"))
OUTPUT_CSV    = os.getenv("OUTPUT_CSV",    os.path.join(_data_dir, "results.csv"))

TOP_K         = int(os.getenv("TOP_K",         "15"))
MAX_ATTEMPTS  = int(os.getenv("MAX_ATTEMPTS",  "3"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))

SEARCH_SYSTEM = "sql_hr"
RETRY_PROMPT  = "Ищи так"

# ---------------------------------------------------------------------------
# CSV-колонки
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "query_id",
    "candidate_id",
    "search_system",
    "rank",
    "score",
    "latency_to_first_ms",
    "latency_ms",
    "retrieved_at",
]

# ---------------------------------------------------------------------------
# HTTP-хелперы
# ---------------------------------------------------------------------------


def post_message(session_id: str, message: str) -> tuple[dict, float]:
    """Отправить сообщение агенту. Возвращает (response_json, latency_ms)."""
    t0 = time.monotonic()
    resp = requests.post(
        BASE_URL + "/",
        json={"session_id": session_id, "message": message},
        timeout=600,
    )
    latency_ms = (time.monotonic() - t0) * 1000
    resp.raise_for_status()
    return resp.json(), latency_ms


def poll_current_candidates(session_id: str) -> list:
    """Разовый опрос /candidates/current. Возвращает список или []."""
    try:
        resp = requests.get(
            f"{BASE_URL}/session/{session_id}/candidates/current",
            timeout=5,
        )
        if resp.ok:
            return resp.json().get("candidates") or []
    except Exception:
        pass
    return []


def search_started(response: dict) -> bool:
    """Агент выполнил поиск и вернул хотя бы одного кандидата."""
    return bool(response.get("candidates"))


# ---------------------------------------------------------------------------
# Поллинг в фоновом потоке
# ---------------------------------------------------------------------------


class FirstCandidateWatcher:
    """
    Поллит /candidates/current пока poll_active=True.
    Записывает latency_to_first_ms с момента старта до первого непустого ответа.
    """

    def __init__(self, session_id: str, t0: float):
        self.session_id = session_id
        self.t0 = t0
        self.latency_to_first_ms: float | None = None
        self.poll_active = True
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.poll_active = False
        if not self._thread.is_alive():
            return
        if threading.current_thread() is self._thread:
            return
        # Не блокируем основной цикл надолго, если фоновый poll завис в HTTP.
        self._thread.join(timeout=0.2)

    def _run(self) -> None:
        while self.poll_active:
            candidates = poll_current_candidates(self.session_id)
            if candidates:
                self.latency_to_first_ms = (time.monotonic() - self.t0) * 1000
                return
            time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Основная логика запроса
# ---------------------------------------------------------------------------


def process_query(
    query_id: int,
    query_text: str,
    writer: csv.DictWriter,
) -> bool:
    """
    Обработать одну строку запроса.

    Логика:
      - attempt 1: оригинальный запрос
      - attempt 2+: «Ищи так» (подсказка агенту, та же сессия)
      - если после MAX_ATTEMPTS поиск так и не начат — пропускаем

    latency_to_first_ms = время до первых кандидатов (через поллинг).
    latency_ms          = суммарное время всех HTTP-попыток по запросу.
    score               = rerank_score из CrossEncoder.
    """
    session_id = str(uuid.uuid4())
    cumulative_ms = 0.0
    watcher: FirstCandidateWatcher | None = None
    global_t0 = time.monotonic()  # старт всей обработки запроса

    for attempt in range(MAX_ATTEMPTS):
        msg = query_text if attempt == 0 else RETRY_PROMPT

        print(f"  попытка {attempt + 1}/{MAX_ATTEMPTS}: {msg[:80]}")

        # Запускаем поллинг только на первой попытке
        if attempt == 0:
            watcher = FirstCandidateWatcher(session_id, global_t0)
            watcher.start()

        try:
            resp, latency_ms = post_message(session_id, msg)
            cumulative_ms += latency_ms
        except requests.exceptions.Timeout:
            print("  TIMEOUT — пропускаем попытку")
            continue
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue
        finally:
            # Останавливаем поллинг после завершения каждой попытки
            if watcher and watcher.poll_active:
                watcher.stop()

        if not search_started(resp):
            print(f"  поиск не начат (+{round(latency_ms)} ms)")
            # Для следующей попытки запустим новый watcher (уже идёт та же сессия)
            watcher = FirstCandidateWatcher(session_id, global_t0)
            watcher.start()
            continue

        # Поиск состоялся — записываем результаты
        candidates = resp["candidates"]
        top = candidates[:TOP_K]
        retrieved_at = datetime.now(timezone.utc).isoformat()

        # latency_to_first_ms: из поллинга, иначе fallback на full_latency_ms
        latency_to_first = (
            round(watcher.latency_to_first_ms)
            if watcher and watcher.latency_to_first_ms is not None
            else round(cumulative_ms)
        )

        for rank, candidate in enumerate(top, start=1):
            cid = (
                candidate.get("id")
                or candidate.get("candidate_id")
                or ""
            )
            score = candidate.get("rerank_score")

            writer.writerow(
                {
                    "query_id":             query_id,
                    "candidate_id":         cid,
                    "search_system":        SEARCH_SYSTEM,
                    "rank":                 rank,
                    "score":                score,
                    "latency_to_first_ms":  latency_to_first,
                    "latency_ms":           round(cumulative_ms),
                    "retrieved_at":         retrieved_at,
                }
            )

        print(
            f"  ✓ {len(top)} кандидатов"
            f" | first={latency_to_first} ms"
            f" | full={round(cumulative_ms)} ms"
            f" (попыток: {attempt + 1})"
        )
        return True

    # Убеждаемся что поллинг остановлен
    if watcher and watcher.poll_active:
        watcher.stop()

    print(f"  → пропускаем запрос #{query_id} (поиск не начат после {MAX_ATTEMPTS} попыток)")
    return False


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------


def _last_completed_query_id(csv_path: str) -> int:
    """
    Читает уже готовый results.csv и возвращает максимальный query_id.
    Если файл не существует или пуст — возвращает 0.
    """
    if not os.path.exists(csv_path):
        return 0
    last_id = 0
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    qid = int(row.get("query_id", 0))
                    if qid > last_id:
                        last_id = qid
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return last_id


def _existing_header_matches(csv_path: str) -> bool:
    """Проверяет, совпадает ли заголовок текущего CSV с ожидаемым форматом."""
    if not os.path.exists(csv_path):
        return True

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return False

    return header == FIELDNAMES


def _agent_unavailable_message(base_url: str, exc: Exception) -> str:
    repo_root = os.path.abspath(os.path.join(_script_dir, ".."))
    return dedent(
        f"""
        [ERROR] Агент недоступен по {base_url}: {exc}

        auto_frontend не поднимает agent_server автоматически.

        Что сделать:
          1. Из корня репозитория запустить API:
             docker compose -f docker-compose-api.yml up --build postgres agent_server
          2. Дождаться статуса /health:
             {base_url}/health
          3. Повторно запустить:
             python run.py

        Альтернатива:
          - полный локальный стек: docker compose -f docker-compose-test.yml up --build
          - другой адрес агента: задать переменную AGENT_URL

        Корень репозитория: {repo_root}
        """
    ).strip()


def main() -> None:
    if not os.path.exists(QUERIES_FILE):
        print(f"[ERROR] Файл запросов не найден: {QUERIES_FILE}", file=sys.stderr)
        sys.exit(1)

    try:
        requests.get(BASE_URL + "/health", timeout=10).raise_for_status()
    except Exception as exc:
        print(_agent_unavailable_message(BASE_URL, exc), file=sys.stderr)
        sys.exit(1)

    with open(QUERIES_FILE, encoding="utf-8") as f:
        queries = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]

    if not queries:
        print("[ERROR] Файл запросов пустой", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_CSV)), exist_ok=True)

    header_matches = _existing_header_matches(OUTPUT_CSV)
    resume_from = _last_completed_query_id(OUTPUT_CSV) + 1 if header_matches else 1

    print(f"Агент:     {BASE_URL}")
    print(f"Запросы:   {QUERIES_FILE}  ({len(queries)} строк)")
    print(f"Результат: {OUTPUT_CSV}")
    print(f"TOP_K={TOP_K}  MAX_ATTEMPTS={MAX_ATTEMPTS}  POLL_INTERVAL={POLL_INTERVAL}s")
    if not header_matches and os.path.exists(OUTPUT_CSV):
        print("Формат существующего CSV отличается от ожидаемого. Файл будет перезаписан.")
    if resume_from > 1:
        print(f"RESUME:    продолжаем с запроса #{resume_from} (уже готово: {resume_from - 1})")
    print("-" * 60)

    found_total   = 0
    skipped_total = 0

    # Открываем CSV на дозапись если resuming, иначе создаём заново
    file_mode = "a" if resume_from > 1 and header_matches else "w"
    with open(OUTPUT_CSV, file_mode, newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=FIELDNAMES)
        if file_mode == "w":
            writer.writeheader()

        for query_id, query_text in enumerate(queries, start=1):
            if query_id < resume_from:
                continue

            print(f"\n[{query_id}/{len(queries)}] {query_text}")

            success = process_query(query_id, query_text, writer)

            if success:
                found_total += 1
            else:
                skipped_total += 1

            f_out.flush()

    print("\n" + "=" * 60)
    print(f"Готово: успешно={found_total}, пропущено={skipped_total}")
    print(f"CSV сохранён: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
