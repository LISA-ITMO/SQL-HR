#!/usr/bin/env bash
set -euo pipefail

INPUT=${INPUT:-/data/candidates.csv}
CLEAN=${CLEAN:-/data/candidates_clean.csv}
BAD=${BAD:-/data/candidates_bad.csv}
LOG=${LOG:-/data/candidates_bad_rows.txt}
DELIM=${DELIM:-';'}

if [[ ! -f "$INPUT" ]]; then
  echo "preprocess: input file not found: $INPUT" >&2
  exit 1
fi

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "preprocess: python not found in container; cannot preprocess CSV" >&2
  exit 1
fi

export INPUT CLEAN BAD LOG DELIM

${PYTHON_BIN} - <<'PY'
import csv
import os
import re
import sys

input_path = os.environ["INPUT"]
clean_path = os.environ["CLEAN"]
bad_path = os.environ["BAD"]
log_path = os.environ["LOG"]
delim = os.environ["DELIM"]

expected_cols = None
header = None
date_indices = {}
header_in_index = {}
bad_count = 0
bad_date_count = 0

DATE_COLUMNS = {
    "Дата поступления документов",
    "Дата рождения",
    "Дата назначения",
    "Дата увольнения",
}

HEADER_SPEC_PATH = os.environ.get("HEADER_SPEC", "/db/header_spec.txt")


def load_expected_header(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f_spec:
            lines = [line.strip() for line in f_spec]
    except OSError:
        return None

    cols = [line for line in lines if line and not line.startswith("#")]
    return cols or None


EXPECTED_HEADER = load_expected_header(HEADER_SPEC_PATH)
if EXPECTED_HEADER is None:
    print(
        f"preprocess: header spec not found or empty: {HEADER_SPEC_PATH}",
        file=sys.stderr,
    )
    sys.exit(1)



def _date_from_parts(day, month, year):
    if year < 100:
        year += 2000
    try:
        import datetime as _dt
        return _dt.date(year, month, day)
    except ValueError:
        return None


def parse_date(value):
    s = value.strip()
    if not s:
        return None

    s = " ".join(s.split())

    # yyyy-mm-dd or yyyy/mm/dd
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        year, month, day = map(int, m.groups())
        return _date_from_parts(day, month, year)

    # dd.mm.yyyy or dd-mm-yyyy or dd/mm/yyyy (also allows 2-digit year)
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s)
    if m:
        day, month, year = map(int, m.groups())
        return _date_from_parts(day, month, year)

    return None

with open(input_path, newline="", encoding="utf-8") as f_in, \
     open(clean_path, "w", newline="", encoding="utf-8") as f_clean, \
     open(bad_path, "w", newline="", encoding="utf-8") as f_bad, \
     open(log_path, "w", encoding="utf-8") as f_log:

    reader = csv.reader(f_in, delimiter=delim, strict=False)
    clean_writer = csv.writer(f_clean, delimiter=delim)
    bad_writer = csv.writer(f_bad, delimiter=delim)

    f_log.write("row_number\treason\tcolumn\tvalue\tfound\texpected\n")

    for row_num, row in enumerate(reader, start=1):
        if expected_cols is None:
            expected_cols = len(row)
            header_in = row
            header_in_index = {name: idx for idx, name in enumerate(header_in)}
            header = EXPECTED_HEADER
            missing = [name for name in header if name not in header_in_index]
            extra = [name for name in header_in if name not in set(header)]
            if missing:
                f_log.write(
                    f"0\theader_missing\t\t{', '.join(missing)}\t{len(header_in)}\t{len(header)}\n"
                )
            if extra:
                f_log.write(
                    f"0\theader_extra\t\t{', '.join(extra)}\t{len(header_in)}\t{len(header)}\n"
                )

            date_indices = {
                name: header.index(name)
                for name in DATE_COLUMNS
                if name in header
            }

            clean_writer.writerow(header)
            bad_writer.writerow(header)
            continue

        if len(row) != expected_cols:
            bad_count += 1
            reason = "too_few_columns" if len(row) < expected_cols else "too_many_columns"
            f_log.write(f"{row_num}\t{reason}\t\t\t{len(row)}\t{expected_cols}\n")
            bad_writer.writerow(row)
            continue

        row = [row[header_in_index[name]] if name in header_in_index else "" for name in header]

        # Validate and normalize required date columns.
        invalid_date = None
        for name, idx in date_indices.items():
            raw = row[idx].strip()
            if not raw:
                continue
            parsed = parse_date(raw)
            if parsed is None:
                invalid_date = (name, raw)
                break
            row[idx] = parsed.isoformat()

        if invalid_date:
            bad_count += 1
            bad_date_count += 1
            col, val = invalid_date
            f_log.write(f"{row_num}\tinvalid_date\t{col}\t{val}\t{len(row)}\t{expected_cols}\n")
            bad_writer.writerow(row)
            continue

        clean_writer.writerow(row)

print(
    f"preprocess: done. bad_rows={bad_count} (invalid_date={bad_date_count}), "
    f"clean={clean_path}, bad={bad_path}, log={log_path}",
    file=sys.stderr,
)
PY
