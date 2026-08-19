#!/usr/bin/env python3
"""
csv_to_sql.py

Converts CSV files into SQL files (CREATE TABLE + batched INSERT statements)
compatible with Cloudflare D1 (SQLite dialect), ready to load with:

    wrangler d1 execute <DB_NAME> --remote --file=./fonts_classified_out.sql
    wrangler d1 execute <DB_NAME> --remote --file=./websites_clean_out.sql

Usage (defaults tailored to this project — just run with no args):
    python3 csv_to_sql.py

Or explicitly:
    python3 csv_to_sql.py fonts_classified_out.csv fonts --pk font
    python3 csv_to_sql.py websites_clean_out.csv websites --pk domain

General form:
    python3 csv_to_sql.py <csv_path> <table_name> [--pk COLUMN] [--batch N] [--drop]

Column types are inferred per-column by sampling all values in that column:
INTEGER if every non-empty value parses as int, REAL if every non-empty value
parses as float (with at least one non-int), otherwise TEXT.
"""

import csv
import sys
import argparse
import os


def sniff_column_types(rows, fieldnames):
    """Infer a SQLite type for each column by scanning all rows."""
    types = {}
    for col in fieldnames:
        saw_value = False
        all_int = True
        all_float = True
        for row in rows:
            val = row.get(col)
            if val is None or val.strip() == "":
                continue
            saw_value = True
            v = val.strip()
            try:
                int(v)
            except ValueError:
                all_int = False
            try:
                float(v)
            except ValueError:
                all_float = False
        if not saw_value:
            types[col] = "TEXT"
        elif all_int:
            types[col] = "INTEGER"
        elif all_float:
            types[col] = "REAL"
        else:
            types[col] = "TEXT"
    return types


def sql_escape_string(value: str) -> str:
    """Escape a string for safe inclusion in a single-quoted SQL literal."""
    return value.replace("'", "''")


def format_value(value, col_type):
    """Format a single CSV cell as a SQL literal based on inferred column type."""
    if value is None or value.strip() == "":
        return "NULL"
    v = value.strip()
    if col_type == "INTEGER":
        try:
            return str(int(v))
        except ValueError:
            return f"'{sql_escape_string(v)}'"
    if col_type == "REAL":
        try:
            return str(float(v))
        except ValueError:
            return f"'{sql_escape_string(v)}'"
    return f"'{sql_escape_string(v)}'"


def sanitize_identifier(name: str) -> str:
    """Make a column/table name safe as a SQL identifier (quoted regardless)."""
    return name.strip().replace('"', "")


def convert(csv_path, table_name, pk_column=None, batch_size=200, drop_first=False):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames:
        sys.exit(f"ERROR: could not read header from {csv_path}")

    if pk_column and pk_column not in fieldnames:
        sys.exit(f"ERROR: --pk '{pk_column}' is not a column in {csv_path}. "
                  f"Columns are: {fieldnames}")

    col_types = sniff_column_types(rows, fieldnames)

    out_path = os.path.splitext(csv_path)[0] + ".sql"
    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"-- Generated from {csv_path}\n")
        out.write(f"-- {len(rows)} data rows\n\n")

        if drop_first:
            out.write(f'DROP TABLE IF EXISTS "{table_name}";\n\n')

        # CREATE TABLE
        col_defs = []
        for col in fieldnames:
            ident = sanitize_identifier(col)
            col_sql = f'  "{ident}" {col_types[col]}'
            if pk_column and col == pk_column:
                col_sql += " PRIMARY KEY"
            col_defs.append(col_sql)

        out.write(f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n')
        out.write(",\n".join(col_defs))
        out.write("\n);\n\n")

        # INSERT statements, batched
        ident_cols = ", ".join(f'"{sanitize_identifier(c)}"' for c in fieldnames)
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            value_tuples = []
            for row in batch:
                vals = [format_value(row.get(c), col_types[c]) for c in fieldnames]
                value_tuples.append(f"({', '.join(vals)})")
            out.write(
                f'INSERT INTO "{table_name}" ({ident_cols}) VALUES\n'
                + ",\n".join(value_tuples)
                + ";\n\n"
            )

    print(f"Wrote {len(rows)} rows across {len(fieldnames)} columns -> {out_path}")
    print(f"  Table: {table_name}")
    print(f"  Inferred types: {col_types}")
    if pk_column:
        print(f"  Primary key: {pk_column}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Convert a CSV to a D1/SQLite SQL file.")
    parser.add_argument("csv_path", nargs="?", help="Path to the CSV file")
    parser.add_argument("table_name", nargs="?", help="Name of the SQL table to create")
    parser.add_argument("--pk", dest="pk_column", default=None,
                         help="Column to use as PRIMARY KEY")
    parser.add_argument("--batch", dest="batch_size", type=int, default=200,
                         help="Rows per INSERT statement (default: 200)")
    parser.add_argument("--drop", dest="drop_first", action="store_true",
                         help="Add a DROP TABLE IF EXISTS before CREATE TABLE")
    args = parser.parse_args()

    if args.csv_path and args.table_name:
        # Explicit single-file mode
        convert(args.csv_path, args.table_name, args.pk_column, args.batch_size, args.drop_first)
        return

    if args.csv_path or args.table_name:
        sys.exit("ERROR: provide both csv_path and table_name, or neither to run project defaults.")

    # No args: run project defaults for this task
    defaults = [
        # (csv_path, table_name, pk_column)
        ("fonts_classified_out.csv", "fonts", "font"),
        ("websites_clean_out.csv", "websites", "domain"),
    ]
    for csv_path, table_name, pk in defaults:
        if not os.path.exists(csv_path):
            print(f"Skipping {csv_path} (not found in current directory)")
            continue
        convert(csv_path, table_name, pk_column=pk, batch_size=args.batch_size,
                drop_first=args.drop_first)


if __name__ == "__main__":
    main()