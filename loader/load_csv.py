#!/usr/bin/env python3
"""Загрузка CSV с кандидатами в таблицу candidates по файлу соответствия колонок (YAML).

Запуск из корня репозитория (подробности и ограничения в loader/README.md):
  python loader/load_csv.py <файл.csv> [--mapping <файл>.yaml] [--dry-run] [--replace]
Без --mapping берётся loader/mappings/<имя CSV>.yaml.

В БД для каждой записи сохраняются source_file и source_row (номер записи в CSV, заголовок = 1).
Настройки подключения берутся из .env, хост по умолчанию localhost.
"""
import argparse
import csv
import datetime as dt
import os
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import yaml

# Поля таблицы candidates, которые можно заполнять из CSV (id, source_file, source_row служебные).
TARGET_FIELDS = [
    "date_received", "last_name", "first_name", "middle_name", "previous_last_name", "sex",
    "birth_date", "birth_place", "snils", "passport_number", "passport_issued",
    "phone_mobile", "phone_2", "phone_3", "email_1", "email_2", "email_upgo",
    "residence_area", "appointment_date", "dismissal_date", "confirmed_experience_years",
    "source_info", "education_text", "education_count", "work_text", "extra_info_text",
    "status", "ready_to_work", "citizenship",
]
DATE_FIELDS = {"date_received", "birth_date", "appointment_date", "dismissal_date"}
# Типы значений: text, date, number (десятичное, 1 знак), int, count_true,
# experience_years (стаж по двум датам), citizenship (РФ / текст паспорта).
VALID_TYPES = {"text", "date", "number", "int", "count_true", "experience_years", "citizenship"}
TRUE_VALUES = {"true", "t", "1", "yes", "да", "истина", "верно"}

# Поля, по которым SQL-HR фильтрует кандидатов, если в запросе не указано иное
# (agent_server/main.py, get_from_query). Если поле пустое у всех записей файла,
# поиск по умолчанию не вернёт ни одну из них.
SEARCH_DEFAULTS = {
    "birth_date": "возраст 20–65 лет",
    "education_count": "не меньше одного образования",
    "citizenship": "гражданство РФ",
    "status": "статус «резервист»",
    "ready_to_work": "готовность «годен»",
}


# ----------------------------- соответствие колонок -----------------------------

def default_type(field):
    if field in DATE_FIELDS:
        return "date"
    if field == "confirmed_experience_years":
        return "number"
    if field == "education_count":
        return "int"
    return "text"


def load_mapping(path):
    """Читает YAML и приводит каждое поле к виду {type, columns, ...}. Проверяет названия."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("fields")
    if not isinstance(raw, dict) or not raw:
        sys.exit(f"Ошибка: в {path} нет раздела fields с соответствием колонок.")
    fields = {}
    for field, spec in raw.items():
        if field not in TARGET_FIELDS:
            sys.exit(f"Ошибка: поле «{field}» из соответствия отсутствует в таблице candidates.\n"
                     f"Допустимые поля: {', '.join(TARGET_FIELDS)}")
        if isinstance(spec, str):
            spec = {"column": spec}
        if not isinstance(spec, dict):
            sys.exit(f"Ошибка: поле «{field}»: ожидается название колонки или словарь.")
        ftype = spec.get("type", default_type(field))
        if ftype not in VALID_TYPES:
            sys.exit(f"Ошибка: поле «{field}»: неизвестный type «{ftype}». Допустимо: {', '.join(sorted(VALID_TYPES))}")
        if ftype == "experience_years":
            columns = [spec.get("start"), spec.get("end")]
            if not all(columns):
                sys.exit(f"Ошибка: поле «{field}»: для experience_years нужны start и end (колонки с датами).")
        else:
            columns = spec.get("columns") or ([spec["column"]] if "column" in spec else None)
            if not columns:
                sys.exit(f"Ошибка: поле «{field}»: укажите column или columns.")
        fields[field] = {"type": ftype, "columns": list(columns)}
    return fields


# ----------------------------- разбор значений -----------------------------

class BadValue(Exception):
    def __init__(self, reason, column, value):
        self.reason, self.column, self.value = reason, column, value


def parse_date(value):
    """Форматы как в db/00-preprocess.sh: гггг-мм-дд, дд.мм.гггг, дд-мм-гггг, дд/мм/гггг."""
    s = " ".join(value.split())
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        year, month, day = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s)
        if not m:
            return None
        day, month, year = map(int, m.groups())
    if year < 100:
        year += 2000
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def to_date(value, column):
    if value is None:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise BadValue("invalid_date", column, value)
    return parsed


def to_decimal(value, column):
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ".")).quantize(Decimal("0.1"), ROUND_HALF_UP)
    except InvalidOperation:
        raise BadValue("invalid_number", column, value)


def citizenship(value):
    """Как в db/add_rows.sql: «РФ», если в тексте паспорта есть россия/россии/рф, иначе сам текст."""
    if value is None:
        return None
    low = value.lower()
    return "РФ" if ("россия" in low or "россии" in low or "рф" in low) else value


def build_value(field, spec, cells):
    """cells: {название колонки: значение или None}. Возвращает значение для поля."""
    t, cols = spec["type"], spec["columns"]
    if t == "text":
        if len(cols) == 1:
            return cells.get(cols[0])
        parts = [f"{c}: {cells[c]}" for c in cols if cells.get(c)]
        return "; ".join(parts) or None
    if t == "date":
        return to_date(cells.get(cols[0]), cols[0])
    if t == "number":
        return to_decimal(cells.get(cols[0]), cols[0])
    if t == "int":
        v = cells.get(cols[0])
        if v is None:
            return None
        try:
            return int(v)
        except ValueError:
            raise BadValue("invalid_number", cols[0], v)
    if t == "count_true":
        present = [c for c in cols if c in cells]
        if not present:
            return None
        return sum(1 for c in present if (cells[c] or "").lower() in TRUE_VALUES)
    if t == "experience_years":
        start, end = to_date(cells.get(cols[0]), cols[0]), to_date(cells.get(cols[1]), cols[1])
        if start is None or end is None:
            return None
        return (Decimal((end - start).days) / Decimal("365.25")).quantize(Decimal("0.1"), ROUND_HALF_UP)
    if t == "citizenship":
        return citizenship(cells.get(cols[0]))
    raise AssertionError(t)


# ----------------------------- чтение CSV -----------------------------

def read_csv(path, delimiter, fields):
    """Возвращает (заголовок, записи, отклонённые). Номер записи: заголовок = 1."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = None
        loaded, rejected = [], []
        for row_num, row in enumerate(reader, start=1):
            if header is None:
                header = [h.strip() for h in row]
                continue
            if len(row) != len(header):
                reason = "too_few_columns" if len(row) < len(header) else "too_many_columns"
                rejected.append((row_num, reason, "", f"{len(row)} из {len(header)}"))
                continue
            cells = {h: (v.strip() or None) for h, v in zip(header, row)}
            record = {}
            try:
                for field, spec in fields.items():
                    record[field] = build_value(field, spec, cells)
            except BadValue as e:
                rejected.append((row_num, e.reason, e.column, e.value))
                continue
            loaded.append((row_num, record))
    return header, loaded, rejected


# ----------------------------- отчёт -----------------------------

def print_report(csv_path, header, loaded, rejected, fields, mapping_path):
    total = len(loaded) + len(rejected)
    print(f"Файл: {csv_path.name} (записей: {total}, колонок: {len(header)})")
    print(f"Соответствие: {mapping_path}")
    reasons = Counter(r[1] for r in rejected)
    rej_text = ", ".join(f"{k}={v}" for k, v in reasons.items()) or "нет"
    print(f"Принято: {len(loaded)} | Отклонено: {len(rejected)} ({rej_text})")
    for row_num, reason, column, value in rejected:
        where = f" в колонке «{column}»" if column else ""
        print(f"  запись {row_num}: {reason}{where}, значение «{value}»")

    warnings = []
    header_set = set(header)
    for field, spec in fields.items():
        for col in spec["columns"]:
            if col not in header_set:
                warnings.append(f"колонка «{col}» из соответствия не найдена в CSV (поле {field})")
    mapped_cols = {c for s in fields.values() for c in s["columns"]}
    unused = [h for h in header if h not in mapped_cols]

    print("\nЗаполненность полей (записей с непустым значением):")
    for field in TARGET_FIELDS:
        if field in fields:
            filled = sum(1 for _, r in loaded if r.get(field) is not None)
            print(f"  {field:28s} {filled}/{len(loaded)}")
        else:
            print(f"  {field:28s} не задано в соответствии")
    for field, rule in SEARCH_DEFAULTS.items():
        filled = sum(1 for _, r in loaded if r.get(field) is not None) if field in fields else 0
        if filled == 0 and loaded:
            warnings.append(f"поле {field} не заполнено ни у одной записи: поиск по умолчанию "
                            f"({rule}) не вернёт записи этого файла")
    print(f"\nКолонок CSV, не использованных в соответствии: {len(unused)} из {len(header)}")
    if 0 < len(unused) <= 12:
        print("  не использованы: " + ", ".join(unused))
    if warnings:
        print("\nПредупреждения:")
        for w in warnings:
            print(f"  - {w}")


# ----------------------------- база данных -----------------------------

def read_env_file(path):
    env = {}
    if path and Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("'\"")
    return env


def connect(args):
    import psycopg2  # импортируем здесь, чтобы --dry-run работал без библиотеки
    env = read_env_file(args.env_file)
    params = {
        "host": args.host or "localhost",
        "port": args.port or env.get("POSTGRES_PORT") or 5432,
        "dbname": args.dbname or env.get("POSTGRES_DB"),
        "user": args.user or env.get("POSTGRES_USER"),
        "password": args.password or os.environ.get("POSTGRES_PASSWORD") or env.get("POSTGRES_PASSWORD"),
    }
    params = {k: v for k, v in params.items() if v}
    return psycopg2.connect(**params)


def write_to_db(args, source_file, loaded):
    from psycopg2.extras import execute_values
    conn = connect(args)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.candidates')")
            if cur.fetchone()[0] is None:
                sys.exit("Ошибка: таблицы candidates нет. Сначала нужно создать базу (docker compose up).")
            cur.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS source_file TEXT")
            cur.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS source_row INTEGER")
            cur.execute("SELECT count(*) FROM candidates WHERE source_file = %s", (source_file,))
            existing = cur.fetchone()[0]
            if existing and not args.replace:
                sys.exit(f"Ошибка: в базе уже есть {existing} записей из файла «{source_file}». "
                         f"Чтобы заменить их, добавьте флаг --replace (иначе записи задвоятся).")
            if existing:
                cur.execute("DELETE FROM candidates WHERE source_file = %s", (source_file,))
                print(f"Удалено старых записей из «{source_file}»: {existing}")
            columns = [f for f in TARGET_FIELDS if any(f in r for _, r in loaded)] if loaded else []
            cols_sql = ", ".join(columns + ["source_file", "source_row"])
            values = [tuple(r.get(c) for c in columns) + (source_file, row_num) for row_num, r in loaded]
            if values:
                execute_values(cur, f"INSERT INTO candidates ({cols_sql}) VALUES %s", values, page_size=500)
    finally:
        conn.close()


# ----------------------------- main -----------------------------

def main():
    p = argparse.ArgumentParser(description="Загрузка CSV в таблицу candidates по файлу соответствия колонок.")
    p.add_argument("csv_path", help="путь к CSV")
    p.add_argument("--mapping", help="YAML с соответствием колонок (по умолчанию loader/mappings/<имя CSV>.yaml)")
    p.add_argument("--delimiter", default=";", help="разделитель CSV (по умолчанию ;)")
    p.add_argument("--source-name", help="значение source_file (по умолчанию имя CSV)")
    p.add_argument("--rejected", help="куда записать отклонённые записи (по умолчанию data/<имя>.rejected.csv)")
    p.add_argument("--dry-run", action="store_true", help="только проверить файл и показать отчёт, в БД не писать")
    p.add_argument("--replace", action="store_true", help="заменить записи, ранее загруженные из этого файла")
    p.add_argument("--allow-missing-columns", action="store_true",
                   help="загружать, даже если колонок из соответствия нет в CSV (они будут пустыми)")
    p.add_argument("--env-file", default=".env", help="файл с настройками БД (по умолчанию .env)")
    for name in ("--host", "--port", "--dbname", "--user", "--password"):
        p.add_argument(name)
    args = p.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.is_file():
        sys.exit(f"Ошибка: файл не найден: {csv_path}")
    if not args.mapping:
        default = Path(__file__).resolve().parent / "mappings" / f"{csv_path.stem}.yaml"
        if not default.is_file():
            sys.exit(f"Ошибка: не указан --mapping, а файла {default} нет. Создайте его или передайте --mapping.")
        args.mapping = str(default)
        print(f"Соответствие выбрано по имени файла: {args.mapping}")
    fields = load_mapping(args.mapping)
    header, loaded, rejected = read_csv(csv_path, args.delimiter, fields)
    print_report(csv_path, header, loaded, rejected, fields, args.mapping)

    if rejected:
        rej_path = Path(args.rejected) if args.rejected else Path("data") / f"{csv_path.stem}.rejected.csv"
        rej_path.parent.mkdir(parents=True, exist_ok=True)
        with open(rej_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["source_row", "reason", "column", "value"])
            w.writerows(rejected)
        print(f"\nОтклонённые записи сохранены: {rej_path}")

    missing = sorted({c for s_ in fields.values() for c in s_["columns"]} - set(header))
    if missing and not args.allow_missing_columns:
        print(f"\nОСТАНОВКА: в CSV нет {len(missing)} колонок из соответствия. Скорее всего, выбрано не то "
              "соответствие или в файле другие названия колонок. Поправьте YAML "
              "(или запустите с --allow-missing-columns, если пустые поля допустимы).")
        if not args.dry_run:
            sys.exit(2)
    if args.dry_run:
        print("\nРежим --dry-run: в базу ничего не записано.")
        return
    source_file = args.source_name or csv_path.name
    write_to_db(args, source_file, loaded)
    print(f"\nЗагружено в candidates: {len(loaded)} (source_file = «{source_file}»)")


if __name__ == "__main__":
    main()
