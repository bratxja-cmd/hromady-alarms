#!/usr/bin/env python3
"""
Будує stats.json для дашборду з накопиченої бази.

ЗЛИТТЯ ПЕРЕКРИТТІВ:
  Кілька тривог в одній області, що накладаються або стикаються в часі,
  рахуються як ОДНА подія (об'єднаний проміжок). Це прибирає подвійний
  рахунок і кількості, і годин — і наближає числа до сайту-джерела.

  Тривоги без часу завершення (відкриті) у злиття не входять — вони
  рахуються окремо у кількості, але не дають годин.

Відсікаються артефакти, датовані раніше за лютий 2026.
"""

import json
import sqlite3
import datetime as dt
from pathlib import Path
from collections import defaultdict

from hromady_config import HROMADY, ALERT_TYPES

DB = Path(__file__).parent / "data" / "alerts.db"
OUT = Path(__file__).parent / "data" / "stats.json"

MONTHS_UA = {1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
             5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
             9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"}

CUTOFF = dt.datetime(2026, 2, 1)


def parse_dt(s):
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.replace(tzinfo=None) if d.tzinfo else d
    except (ValueError, AttributeError):
        return None


def merge_intervals(intervals):
    """Зливає перекривні/стичні інтервали [(start, end), ...] в окремі події.
    Повертає список об'єднаних (start, end)."""
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        last = merged[-1]
        if s <= last[1]:           # перекривається або стикається з попереднім
            if e > last[1]:
                last[1] = e        # розширюємо подію
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM alerts").fetchall()
    con.close()

    agg = {h["uid"]: {
        "uid": h["uid"], "name": h["name"], "oblast": h["oblast"],
        "level": h.get("level", "oblast"),
        "intervals": [],           # (start, end) тривог із завершенням
        "open_count": 0,           # тривоги без завершення (рахуємо окремо)
        "by_type": defaultdict(int),
    } for h in HROMADY}

    for r in rows:
        uid = r["hromada_uid"]
        if uid not in agg:
            continue
        s = parse_dt(r["started_at"])
        f = parse_dt(r["finished_at"])
        if s and s < CUTOFF:
            continue               # відсікаємо артефакти
        if not s:
            continue
        agg[uid]["by_type"][r["alert_type"] or "unknown"] += 1
        if f and f > s:
            agg[uid]["intervals"].append((s, f))
        else:
            agg[uid]["open_count"] += 1

    regions = []
    for uid, a in agg.items():
        events = merge_intervals(a["intervals"])
        # кількість подій = злиті інтервали + відкриті тривоги
        count = len(events) + a["open_count"]
        total_minutes = sum((e - s).total_seconds() / 60.0 for s, e in events)

        # помісячна розбивка — за місяцем початку злитої події
        by_month = defaultdict(lambda: {"count": 0, "minutes": 0.0})
        for s, e in events:
            mk = f"{s.year}-{s.month:02d}"
            by_month[mk]["count"] += 1
            by_month[mk]["minutes"] += (e - s).total_seconds() / 60.0
        months = {}
        for mk, v in sorted(by_month.items()):
            months[mk] = {
                "label": MONTHS_UA.get(int(mk.split("-")[1]), mk),
                "count": v["count"],
                "hours": round(v["minutes"] / 60.0, 1),
            }

        types = {ALERT_TYPES.get(k, k): v for k, v in a["by_type"].items()}
        regions.append({
            "uid": uid, "name": a["name"], "oblast": a["oblast"],
            "level": a["level"],
            "count": count,
            "total_hours": round(total_minutes / 60.0, 1),
            "avg_minutes": round(total_minutes / len(events), 1) if events else 0,
            "by_month": months,
            "by_type": types,
        })

    regions.sort(key=lambda r: r["total_hours"], reverse=True)
    payload = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "source": "alerts.in.ua API (накопичувально, зі злиттям перекриттів)",
        "note": ("Кілька тривог області, що перекриваються в часі, рахуються "
                 "як одна подія. Тривалість — лише для тривог із зафіксованим "
                 "завершенням."),
        "regions": regions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Готово: {OUT} ({len(regions)} областей)")


if __name__ == "__main__":
    main()
