#!/usr/bin/env python3
"""
Накопичувальний збір тривог по 20 громадах (alerts.in.ua API).

ЧОМУ НАКОПИЧУВАЛЬНИЙ:
  API віддає історію лише за period=month_ago (останній місяць).
  Старіші місяці заднім числом недоступні. Тому скрипт запускають
  регулярно (раз на місяць/тиждень), і він ДОКЛАДАЄ нові тривоги в базу,
  не дублюючи вже збережені (дедуплікація за полем id).

  Так база поступово накопичує повну історію вперед. Історичні місяці
  (лютий–квітень) додаються окремо через import_history.py (вивантаження
  від власника даних).

ЛІМІТИ:
  History-ендпоінт має окремий ліміт 2 запити/хв. Для 20 громад це ~10 хв.
  Скрипт робить паузу 31 секунда між громадами, щоб не впертися в 429.

API-ключ — у змінній середовища ALERTS_TOKEN. НЕ вшивайте в код.
"""

import os
import sys
import time
import json
import sqlite3
import datetime as dt
from pathlib import Path
from urllib import request, error

from hromady_config import HROMADY

API_BASE = "https://api.alerts.in.ua/v1"
TOKEN = os.environ.get("ALERTS_TOKEN", "").strip()
DB = Path(__file__).parent / "data" / "alerts.db"

# History-ендпоінт має ОКРЕМИЙ ліміт: 2 запити/хв (офіційна документація).
# Тому пауза 31с між громадами. Загальні ліміти API інші (8-10 м'який,
# 12 жорсткий запитів/хв), але саме історія обмежена жорсткіше.
HISTORY_DELAY_SEC = 31


def init_db(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id            INTEGER PRIMARY KEY,   -- id тривоги з API (дедуплікація)
            hromada_uid   INTEGER NOT NULL,
            hromada_name  TEXT NOT NULL,
            oblast        TEXT,
            alert_type    TEXT,
            started_at    TEXT,
            finished_at   TEXT,
            calculated    INTEGER,               -- 1 якщо час завершення прогнозований
            source        TEXT DEFAULT 'api'     -- 'api' або 'import'
        )
    """)
    con.commit()


def fetch_history(uid):
    """Тягне місячну історію тривог по громаді."""
    url = f"{API_BASE}/regions/{uid}/alerts/month_ago.json"
    req = request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("alerts", []) if isinstance(data, dict) else []
    except error.HTTPError as e:
        if e.code == 429:
            print(f"    429 (ліміт), чекаю 60с...", file=sys.stderr)
            time.sleep(60)
            return fetch_history(uid)
        print(f"    HTTP {e.code} для uid={uid}: {e.reason}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"    помилка uid={uid}: {e}", file=sys.stderr)
        return []


def upsert_alerts(con, h, alerts):
    """Докладає тривоги в базу, не дублюючи (INSERT OR IGNORE за id).

    Назва й область беруться з конфіга (h), але якщо API віддав власні
    location_title / location_oblast — вони мають пріоритет як точніші.
    Поля тривоги (id, alert_type, started_at, finished_at, calculated)
    відповідають офіційній моделі Alert у документації alerts.in.ua.
    """
    added = 0
    for a in alerts:
        if not isinstance(a, dict) or "id" not in a:
            continue
        name = a.get("location_title") or h["name"]
        oblast = a.get("location_oblast") or h.get("oblast")
        cur = con.execute(
            """INSERT OR IGNORE INTO alerts
               (id, hromada_uid, hromada_name, oblast, alert_type,
                started_at, finished_at, calculated, source)
               VALUES (?,?,?,?,?,?,?,?, 'api')""",
            (
                a["id"], h["uid"], name, oblast,
                a.get("alert_type"), a.get("started_at"),
                a.get("finished_at"),
                1 if a.get("calculated") else 0,
            ),
        )
        added += cur.rowcount
    con.commit()
    return added


def main():
    if not TOKEN:
        print("ПОМИЛКА: не задано ALERTS_TOKEN. Отримайте токен на "
              "https://alerts.in.ua/api-request і:\n"
              "  export ALERTS_TOKEN='ваш_ключ'", file=sys.stderr)
        sys.exit(1)

    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    init_db(con)

    ready = [h for h in HROMADY if h.get("uid") is not None]
    skipped = len(HROMADY) - len(ready)
    if skipped:
        print(f"УВАГА: {skipped} громад без uid буде пропущено. "
              f"Впишіть їхні uid у hromady_config.py (див. інструкцію у файлі).")
    if not ready:
        print("Жодної громади з заданим uid. Спершу заповніть uid у hromady_config.py.",
              file=sys.stderr)
        con.close()
        sys.exit(1)

    print(f"Збираю місячну історію по {len(ready)} громадах "
          f"(~{len(ready)*HISTORY_DELAY_SEC//60} хв через ліміт API)...")
    total_added = 0
    for i, h in enumerate(ready, 1):
        print(f"[{i}/{len(ready)}] {h['name']} (uid={h['uid']})")
        alerts = fetch_history(h["uid"])
        added = upsert_alerts(con, h, alerts)
        total_added += added
        print(f"    отримано {len(alerts)}, нових у базі: {added}")
        if i < len(ready):
            time.sleep(HISTORY_DELAY_SEC)

    con.close()
    print(f"\nГотово. Нових записів додано: {total_added}. База: {DB}")
    print("Далі запустіть build_stats.py, щоб оновити дашборд.")


if __name__ == "__main__":
    main()
