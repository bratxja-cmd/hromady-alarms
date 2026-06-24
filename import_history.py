#!/usr/bin/env python3
"""
Імпорт історичного вивантаження тривог (лютий–квітень) у базу.

НАВІЩО: API не віддає старі місяці заднім числом. Якщо ви отримали
вивантаження від власника даних (air-alarms.in.ua / alerts.in.ua),
цей скрипт кладе його в ту саму базу, що й накопичувальний збір,
тож дашборд бачитиме повну історію лютий–червень.

ФОРМАТ CSV (заголовки можна підлаштувати під ваше вивантаження):
  id,hromada_uid,hromada_name,oblast,alert_type,started_at,finished_at,calculated

  - id: унікальний; якщо у вивантаженні немає id, скрипт згенерує
        стабільний з (uid + started_at), щоб уникнути дублів.
  - дати: ISO 8601 (2026-02-14T20:31:00Z) або інший формат — підправте parse_dt.

ЗАПУСК:
  python3 import_history.py шлях/до/вивантаження.csv
"""

import sys
import csv
import sqlite3
import hashlib
import datetime as dt
from pathlib import Path

DB = Path(__file__).parent / "data" / "alerts.db"


def stable_id(uid, started_at):
    """Стабільний числовий id, якщо у вивантаженні немає власного id."""
    raw = f"{uid}|{started_at}".encode("utf-8")
    return int(hashlib.sha1(raw).hexdigest()[:12], 16)


def main():
    if len(sys.argv) < 2:
        print("Використання: python3 import_history.py файл.csv", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Файл не знайдено: {path}", file=sys.stderr)
        sys.exit(1)

    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY, hromada_uid INTEGER, hromada_name TEXT,
        oblast TEXT, alert_type TEXT, started_at TEXT, finished_at TEXT,
        calculated INTEGER, source TEXT DEFAULT 'import')""")

    added = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row.get("hromada_uid") or row.get("uid")
            started = row.get("started_at") or row.get("start")
            rid = row.get("id") or stable_id(uid, started)
            cur = con.execute(
                """INSERT OR IGNORE INTO alerts
                   (id, hromada_uid, hromada_name, oblast, alert_type,
                    started_at, finished_at, calculated, source)
                   VALUES (?,?,?,?,?,?,?,?, 'import')""",
                (
                    int(rid), int(uid), row.get("hromada_name") or row.get("name"),
                    row.get("oblast"), row.get("alert_type"),
                    started, row.get("finished_at") or row.get("finish"),
                    1 if str(row.get("calculated", "")).lower() in ("1", "true", "так") else 0,
                ),
            )
            added += cur.rowcount
    con.commit()
    con.close()
    print(f"Імпортовано нових записів: {added}")
    print("Далі запустіть build_stats.py.")


if __name__ == "__main__":
    main()
