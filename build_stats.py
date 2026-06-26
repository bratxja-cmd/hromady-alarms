#!/usr/bin/env python3
"""
Будує stats.json для дашборду з накопиченої бази.

Рахує по кожній громаді:
  - сумарну тривалість (год) і кількість тривог за весь період;
  - помісячну розбивку (лютий–червень) — тривалість і кількість;
  - розбивку за типами загроз (air_raid / artillery_shelling / ...).

Тривалість рахується лише для тривог із заповненим finished_at.
"""

import json
import sqlite3
import datetime as dt
from pathlib import Path
from collections import defaultdict

from hromady_config import HROMADY, ALERT_TYPES

DB = Path(__file__).parent / "data" / "alerts.db"
OUT = Path(__file__).parent / "data" / "stats.json"

MONTHS_UA = {2: "Лютий", 3: "Березень", 4: "Квітень", 5: "Травень", 6: "Червень"}


def parse_dt(s):
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.replace(tzinfo=None) if d.tzinfo else d
    except (ValueError, AttributeError):
        return None


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM alerts").fetchall()
    con.close()

    # uid -> агрегати
    agg = {h["uid"]: {
        "uid": h["uid"], "name": h["name"], "oblast": h["oblast"],
        "level": h.get("level", "hromada"),
        "count": 0, "total_minutes": 0.0,
        "by_month": defaultdict(lambda: {"count": 0, "minutes": 0.0}),
        "by_type": defaultdict(int),
        "calculated_share": 0,
    } for h in HROMADY}

    calc_counts = defaultdict(int)
    CUTOFF = dt.datetime(2026, 2, 1)  # відсікаємо артефакти, старіші за лютий 2026
    for r in rows:
        uid = r["hromada_uid"]
        if uid not in agg:
            continue
        a = agg[uid]
        s = parse_dt(r["started_at"])
        f = parse_dt(r["finished_at"])
        # пропускаємо тривоги поза розумним періодом (сміттєві/тестові записи)
        if s and s < CUTOFF:
            continue
        a["count"] += 1
        a["by_type"][r["alert_type"] or "unknown"] += 1
        if r["calculated"]:
            calc_counts[uid] += 1
        minutes = 0.0
        if s and f and f > s:
            minutes = (f - s).total_seconds() / 60.0
            a["total_minutes"] += minutes
        if s:
            mk = f"{s.year}-{s.month:02d}"
            a["by_month"][mk]["count"] += 1
            a["by_month"][mk]["minutes"] += minutes

    regions = []
    for uid, a in agg.items():
        months = {}
        for mk, v in sorted(a["by_month"].items()):
            months[mk] = {
                "label": MONTHS_UA.get(int(mk.split("-")[1]), mk),
                "count": v["count"],
                "hours": round(v["minutes"] / 60.0, 1),
            }
        types = {ALERT_TYPES.get(k, k): v for k, v in a["by_type"].items()}
        regions.append({
            "uid": uid, "name": a["name"], "oblast": a["oblast"],
            "level": a["level"],
            "count": a["count"],
            "total_hours": round(a["total_minutes"] / 60.0, 1),
            "avg_minutes": round(a["total_minutes"] / a["count"], 1) if a["count"] else 0,
            "calculated_share": round(calc_counts[uid] / a["count"] * 100) if a["count"] else 0,
            "by_month": months,
            "by_type": types,
        })

    regions.sort(key=lambda r: r["total_hours"], reverse=True)
    payload = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "source": "alerts.in.ua API (накопичувально) + історичний імпорт",
        "note": ("Тривалість — лише для тривог із зафіксованим завершенням. "
                 "calculated_share — частка тривог із прогнозованим часом завершення "
                 "(для громад буває висока, тож тривалість орієнтовна)."),
        "regions": regions,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Готово: {OUT} ({len(regions)} громад)")


if __name__ == "__main__":
    main()
