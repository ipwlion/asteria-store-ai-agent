"""Esporta le tabelle sintetiche SQLite in CSV leggibili anche con Excel."""

import csv
from pathlib import Path
from database import connect, init_db

BASE = Path(__file__).resolve().parent


def main():
    init_db()
    output = BASE / "data" / "export"
    output.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        for table in ("products", "customers", "orders", "order_items"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            names = [desc[1] for desc in conn.execute(f"PRAGMA table_info({table})")]
            file = output / f"{table}.csv"
            with file.open("w", newline="", encoding="utf-8-sig") as fp:
                writer = csv.writer(fp, delimiter=";")
                writer.writerow(names)
                writer.writerows([tuple(row) for row in rows])
            print(f"{file.name}: {len(rows)} righe")
    print("Esportazione completata:", output)


if __name__ == "__main__":
    main()
