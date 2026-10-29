"""Тесты загрузчика: подсчёт дипломов (count_true), замена записей файла (--replace)
и прогон всех CSV из репозитория с их соответствиями.

Запуск из корня репозитория: python -m pytest loader/tests
Тесты с базой подключаются к PostgreSQL по настройкам из .env (как сам загрузчик) и работают
во временной схеме loader_test_*, которую удаляют после себя. Рабочая таблица public.candidates
не затрагивается. Если база недоступна, эти тесты пропускаются (skip).
"""
import csv
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

LOADER_DIR = Path(__file__).resolve().parents[1]
ROOT = LOADER_DIR.parent
sys.path.insert(0, str(LOADER_DIR))

import load_csv  # noqa: E402

DIPLOMA = ["d1", "d2", "d3"]


def cells_of(values):
    """Ячейки так, как их отдаёт read_csv: пробелы обрезаны, пустая строка = None."""
    return {c: (v.strip() or None) for c, v in zip(DIPLOMA, values)}


def write_csv(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ----------------------------- дипломы -----------------------------

@pytest.mark.parametrize("value, expected", [
    ("да", 1),
    ("True", 1),
    ("нет", 0),
    ("False", 0),
    ("", None),
    ("неизвестно", None),
    ("Нет  данных", None),
])
def test_count_true_one_column(value, expected):
    notes = []
    assert load_csv.count_true(DIPLOMA[:1], cells_of([value]), notes) == expected
    assert notes == []


@pytest.mark.parametrize("values, expected", [
    (["да", "да", "да"], 3),
    (["да", "нет", "нет"], 1),
    (["нет", "нет", "нет"], 0),          # отсутствие дипломов указано явно
    (["да", "неизвестно", ""], 1),      # подтверждён как минимум один диплом
    (["да", "да", ""], 2),
    (["нет", "неизвестно", "нет"], None),  # неизвестная часть не считается ответом «нет»
    (["нет", "", ""], None),
    (["", "", ""], None),
])
def test_count_true_several_columns(values, expected):
    notes = []
    assert load_csv.count_true(DIPLOMA, cells_of(values), notes) == expected
    assert notes == []


def test_count_true_missing_column_is_unknown():
    cells = cells_of(["нет", "нет"])  # колонки d3 в CSV нет
    assert load_csv.count_true(DIPLOMA, cells, []) is None
    cells = cells_of(["да", "нет"])
    assert load_csv.count_true(DIPLOMA, cells, []) == 1


@pytest.mark.parametrize("values, expected", [
    (["может быть"], None),
    (["да", "может быть"], 1),
    (["нет", "может быть"], None),
])
def test_count_true_unrecognized_value_is_unknown_and_reported(values, expected):
    notes = []
    cols = DIPLOMA[:len(values)]
    assert load_csv.count_true(cols, cells_of(values), notes) == expected
    assert notes == [(cols[-1], "может быть")]


def test_unrecognized_values_are_shown_in_report(tmp_path, capsys):
    fields = {
        "last_name": {"type": "text", "columns": ["surname"]},
        "birth_date": {"type": "date", "columns": ["birth"]},
        "education_count": {"type": "count_true", "columns": ["has_diploma"]},
    }
    csv_path = write_csv(tmp_path / "people.csv", [
        "surname;birth;has_diploma",
        "Иванов;01.01.1990;да",
        "Петров;01.01.1990;может быть",
        "Сидоров;плохая дата;может быть",  # отклонена: о её значениях не предупреждаем
        "Козлов;01.01.1990;",
    ])
    header, loaded, rejected, notes = load_csv.read_csv(csv_path, ";", fields)

    assert [r["education_count"] for _, r in loaded] == [1, None, None]
    assert [row for row, *_ in rejected] == [4]
    assert notes == [(3, "has_diploma", "может быть")]

    load_csv.print_report(csv_path, header, loaded, rejected, notes, fields, "mapping.yaml")
    out = capsys.readouterr().out
    assert "колонка «has_diploma»: значение «может быть» не распознано как да/нет" in out
    assert "(записей: 1; 3)" in out


# ----------------------------- замена записей файла -----------------------------

class KeepOpen:
    """Соединение для main(): main закрывает его в конце, а тесту оно нужно и дальше."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def db_conn():
    psycopg2 = pytest.importorskip("psycopg2")
    args = SimpleNamespace(env_file=str(ROOT / ".env"), host=None, port=None, dbname=None, user=None, password=None)
    try:
        conn = load_csv.connect(args)
    except psycopg2.OperationalError as e:
        pytest.skip(f"PostgreSQL недоступен: {e}")
    schema = f"loader_test_{uuid.uuid4().hex[:8]}"
    try:
        with conn, conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {schema}")
            cur.execute(f"SET search_path TO {schema}")
            cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        yield conn
    finally:
        conn.rollback()
        with conn, conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.close()


def rows_of(conn, source_file):
    with conn, conn.cursor() as cur:
        cur.execute("SELECT last_name, source_row FROM candidates WHERE source_file = %s ORDER BY source_row",
                    (source_file,))
        return cur.fetchall()


def run_main(monkeypatch, conn, *argv):
    monkeypatch.setattr(load_csv, "connect", lambda args: KeepOpen(conn))
    monkeypatch.setattr(sys, "argv", ["load_csv.py", *argv])
    load_csv.main()


@pytest.fixture
def mapping(tmp_path):
    path = tmp_path / "mapping.yaml"
    path.write_text('fields:\n  last_name: "surname"\n  birth_date: "birth"\n', encoding="utf-8")
    return str(path)


OLD_A = [(2, {"last_name": "Старый-1"}), (3, {"last_name": "Старый-2"})]


def test_replace_with_all_rows_rejected_keeps_old_records(db_conn, tmp_path, mapping, monkeypatch):
    load_csv.write_to_db(db_conn, "a.csv", OLD_A, replace=False)
    bad = write_csv(tmp_path / "a.csv", [
        "surname;birth",
        "Новый-1;не дата",
        "Новый-2;32.13.2000",
    ])

    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, db_conn, str(bad), "--mapping", mapping, "--replace",
                 "--rejected", str(tmp_path / "a.rejected.csv"))

    assert exc.value.code == 2
    assert rows_of(db_conn, "a.csv") == [("Старый-1", 2), ("Старый-2", 3)]


def test_write_to_db_without_records_does_not_delete(db_conn):
    load_csv.write_to_db(db_conn, "a.csv", OLD_A, replace=False)

    with pytest.raises(load_csv.LoaderError):
        load_csv.write_to_db(db_conn, "a.csv", [], replace=True)

    assert rows_of(db_conn, "a.csv") == [("Старый-1", 2), ("Старый-2", 3)]


def test_replace_changes_only_records_of_its_file(db_conn, tmp_path, mapping, monkeypatch):
    rejected = str(tmp_path / "rejected.csv")
    a_v1 = write_csv(tmp_path / "a_v1.csv", ["surname;birth", "А-старый;01.01.1990"])
    b = write_csv(tmp_path / "b.csv", ["surname;birth", "Б-1;01.01.1990", "Б-2;02.02.1991"])
    a_v2 = write_csv(tmp_path / "a_v2.csv", ["surname;birth", "А-новый-1;01.01.1990", "А-новый-2;01.01.1990"])

    run_main(monkeypatch, db_conn, str(a_v1), "--mapping", mapping, "--source-name", "a.csv", "--rejected", rejected)
    run_main(monkeypatch, db_conn, str(b), "--mapping", mapping, "--rejected", rejected)
    run_main(monkeypatch, db_conn, str(a_v2), "--mapping", mapping, "--source-name", "a.csv", "--replace",
             "--rejected", rejected)

    assert rows_of(db_conn, "a.csv") == [("А-новый-1", 2), ("А-новый-2", 3)]
    assert rows_of(db_conn, "b.csv") == [("Б-1", 2), ("Б-2", 3)]


def test_reload_without_replace_is_refused(db_conn):
    load_csv.write_to_db(db_conn, "a.csv", OLD_A, replace=False)

    with pytest.raises(load_csv.LoaderError, match="--replace"):
        load_csv.write_to_db(db_conn, "a.csv", [(2, {"last_name": "Новый"})], replace=False)

    assert rows_of(db_conn, "a.csv") == [("Старый-1", 2), ("Старый-2", 3)]


def test_insert_error_rolls_back_delete(db_conn):
    psycopg2 = pytest.importorskip("psycopg2")
    load_csv.write_to_db(db_conn, "a.csv", OLD_A, replace=False)
    # Значение, которое PostgreSQL не примет в колонку DATE: вставка падает уже после DELETE.
    broken = [(2, {"last_name": "Новый", "birth_date": "не дата"})]

    with pytest.raises(psycopg2.Error):
        load_csv.write_to_db(db_conn, "a.csv", broken, replace=True)

    assert rows_of(db_conn, "a.csv") == [("Старый-1", 2), ("Старый-2", 3)]


# ----------------------------- CSV с соответствиями -----------------------------
# Проверяются все CSV, для которых в loader/mappings/ есть YAML с тем же именем
# (то же правило, по которому загрузчик сам выбирает соответствие). CSV ищется в data/
# и loader/examples/. Файлы без YAML (результаты 00-preprocess.sh, копии, ещё не
# размеченные файлы) не проверяются: загрузить их без соответствия нельзя.
# Тесты ловят поломки соответствий (опечатка в названии колонки) и проверяют,
# что source_row указывает на ту строку файла, откуда взята запись.

CSV_DIRS = [ROOT / "data", LOADER_DIR / "examples"]
ALL_SEARCH_FIELDS = sorted(load_csv.SEARCH_DEFAULTS)

# Точные ожидаемые результаты для известных файлов:
# имя → (принято, отклонено [(номер записи, причина)], поля поиска, пустые у всех записей).
# Новый файл без строки здесь проходит только общие проверки.
EXPECTED = {
    "candidates_synth": (49, [(12, "invalid_date")], []),
    "candidates_b": (20, [], []),
    "candidates_c_minimal": (20, [], ALL_SEARCH_FIELDS),
}


def find_mapped_files():
    params = []
    for mapping_path in sorted((LOADER_DIR / "mappings").glob("*.yaml")):
        found = [d / f"{mapping_path.stem}.csv" for d in CSV_DIRS if (d / f"{mapping_path.stem}.csv").is_file()]
        marks = [] if found else [pytest.mark.skip(reason=f"нет CSV для {mapping_path.name} в data/ и loader/examples/")]
        params.append(pytest.param(found[0] if found else None, mapping_path, id=mapping_path.stem, marks=marks))
    return params


MAPPED_FILES = find_mapped_files()


def read_mapped_file(csv_path, mapping_path):
    fields = load_csv.load_mapping(mapping_path)
    return fields, load_csv.read_csv(csv_path, ";", fields)


def test_known_files_are_found():
    found = {p.id for p in MAPPED_FILES if not p.marks}
    assert sorted(set(EXPECTED) - found) == [], "известный CSV или его YAML пропал"


@pytest.mark.parametrize("csv_path, mapping_path", MAPPED_FILES)
def test_mapped_file_is_read_with_its_mapping(csv_path, mapping_path):
    fields, (header, loaded, rejected, notes) = read_mapped_file(csv_path, mapping_path)

    mapped_columns = {c for spec in fields.values() for c in spec["columns"]}
    assert sorted(mapped_columns - set(header)) == [], "в CSV нет колонок из соответствия"
    assert loaded, "ни одна запись не принята"
    assert notes == [], "нераспознанные значения да/нет"

    if mapping_path.stem in EXPECTED:
        accepted, rejected_rows, empty_search_fields = EXPECTED[mapping_path.stem]
        assert len(loaded) == accepted
        assert [(row, reason) for row, reason, *_ in rejected] == rejected_rows
        empty = [f for f in ALL_SEARCH_FIELDS if all(r.get(f) is None for _, r in loaded)]
        assert empty == empty_search_fields


@pytest.mark.parametrize("csv_path, mapping_path", MAPPED_FILES)
def test_mapped_file_source_row_points_to_its_line(csv_path, mapping_path):
    fields, (header, loaded, rejected, notes) = read_mapped_file(csv_path, mapping_path)
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        raw = {num: row for num, row in enumerate(csv.reader(f, delimiter=";"), start=1)}
    surname_col = header.index(fields["last_name"]["columns"][0])

    numbers = sorted([row for row, _ in loaded] + [row for row, *_ in rejected])
    assert numbers == list(range(2, len(raw) + 1)), "каждая запись файла должна получить свой номер"
    for row_num, record in loaded:
        assert record["last_name"] == raw[row_num][surname_col].strip()


@pytest.mark.parametrize("csv_path, mapping_path", MAPPED_FILES)
def test_mapped_file_loads_into_db(db_conn, tmp_path, monkeypatch, csv_path, mapping_path):
    run_main(monkeypatch, db_conn, str(csv_path), "--mapping", str(mapping_path),
             "--rejected", str(tmp_path / "rejected.csv"))

    _, (_, loaded, _, _) = read_mapped_file(csv_path, mapping_path)
    assert rows_of(db_conn, csv_path.name) == [(r.get("last_name"), row_num) for row_num, r in loaded]
