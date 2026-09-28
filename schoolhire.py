#!/usr/bin/env python3
"""Find basketball court slots on schoolhire.co.uk that are at least N% free.

Fetches the calendar.json week view for every court in courts.json, works out
how much of the hall is free in each slot ("Available" = 100% free,
"50% busy" = 50% free, "Booked" = 0% free), joins back-to-back slots that
qualify, and prints the windows that are long enough to be worth booking.

Examples:
    python schoolhire.py                          # next 14 days, >=50% free, >=60 min
    python schoolhire.py --days 21 --after 18:00  # evenings only, three weeks
    python schoolhire.py --weekdays sat,sun --min-minutes 90
    python schoolhire.py --fixture get.json       # parse a saved response, no network
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote

BASE = "https://schoolhire.co.uk"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
BUSY_PCT_RE = re.compile(r"(\d+)\s*%\s*busy", re.IGNORECASE)
TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")


@dataclass
class Slot:
    date: str   # YYYY-MM-DD
    start: str  # HH:MM
    end: str    # HH:MM
    free_pct: int
    status: str  # className from the site, e.g. available / partially_booked


@dataclass
class Window:
    court: str
    date: str
    start: str
    end: str
    minutes: int
    min_free_pct: int
    price: float | None
    court_size: str
    drive_min: int | None
    notes: str
    link: str


# --------------------------------------------------------------------------- parsing

def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def from_minutes(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def free_pct(item: dict) -> int | None:
    """Percentage of the hall that is free for one calendar item.

    Returns None if the item can't be understood, so the caller can warn
    instead of silently treating it as free.
    """
    if not item.get("busy"):
        return 100
    text = item.get("text", "")
    match = BUSY_PCT_RE.search(text)
    if match:
        return max(0, 100 - int(match.group(1)))
    if item.get("className") == "fully_booked" or "booked" in text.lower():
        return 0
    return None


def item_times(item: dict) -> tuple[str, str] | None:
    if item.get("startTime") and item.get("endTime"):
        return item["startTime"], item["endTime"]
    match = TIME_RANGE_RE.search(item.get("text", ""))
    return (match.group(1), match.group(2)) if match else None


def parse_calendar(data: dict, facility_id: int | None = None) -> list[Slot]:
    """Turn a calendar.json response into a flat list of slots."""
    slots: list[Slot] = []
    for facility in data.get("facilities", []):
        if facility_id is not None and facility.get("id") != facility_id:
            continue
        for day in facility.get("days", []):
            if day.get("closed"):
                continue
            for item in day.get("items", []):
                times = item_times(item)
                pct = free_pct(item)
                if times is None or pct is None:
                    print(f"  warning: couldn't parse item on {day.get('date')}: "
                          f"{item.get('text')!r}", file=sys.stderr)
                    continue
                slots.append(Slot(day["date"], times[0], times[1], pct,
                                  item.get("className", "")))
    return slots


def find_windows(slots: list[Slot], min_free: int, min_minutes: int,
                 after: str | None = None, before: str | None = None,
                 weekdays: set[int] | None = None) -> list[tuple[str, int, int, int]]:
    """Join back-to-back slots that are at least `min_free`% free.

    Returns (date, start_min, end_min, lowest_free_pct) for each window that is
    at least `min_minutes` long after clipping to the after/before times.
    """
    lo = to_minutes(after) if after else 0
    hi = to_minutes(before) if before else 24 * 60

    by_date: dict[str, list[Slot]] = {}
    for s in slots:
        by_date.setdefault(s.date, []).append(s)

    windows = []
    for date, day_slots in sorted(by_date.items()):
        if weekdays is not None and dt.date.fromisoformat(date).weekday() not in weekdays:
            continue
        current: list[int] | None = None  # [start, end, lowest free pct]
        for s in sorted(day_slots, key=lambda s: to_minutes(s.start)):
            start = max(to_minutes(s.start), lo)
            end = min(to_minutes(s.end), hi)
            if s.free_pct < min_free or end <= start:
                if current:
                    windows.append((date, *current))
                current = None
                continue
            if current and current[1] == start:
                current[1] = end
                current[2] = min(current[2], s.free_pct)
            else:
                if current:
                    windows.append((date, *current))
                current = [start, end, s.free_pct]
        if current:
            windows.append((date, *current))

    return [w for w in windows if w[2] - w[1] >= min_minutes]


# --------------------------------------------------------------------------- fetching

def facility_id_from_url(url: str) -> int:
    match = re.search(r"/(\d+)/?(?:\?.*)?$", url)
    if not match:
        raise ValueError(f"can't find a facility id at the end of {url}")
    return int(match.group(1))


def fetch_weeks(session, court_url: str, start: dt.date, end: dt.date,
                delay: float) -> list[Slot]:
    """Fetch every week between start and end for one court."""
    page = court_url.split("?")[0]
    facility_id = facility_id_from_url(page)

    # Load the court page first to pick up fresh XSRF-TOKEN / session cookies.
    session.get(page, timeout=30).raise_for_status()
    token = session.cookies.get("XSRF-TOKEN")
    headers = {"Accept": "application/json", "Referer": page,
               "X-Requested-With": "XMLHttpRequest"}
    if token:
        headers["X-XSRF-TOKEN"] = unquote(token)

    slots: dict[tuple[str, str, str], Slot] = {}
    day = start
    while day <= end:
        time.sleep(delay)
        r = session.get(f"{BASE}/calendar.json", timeout=30, headers=headers,
                        params={"facility_id": facility_id,
                                "date": day.isoformat(), "view": "week"})
        r.raise_for_status()
        for s in parse_calendar(r.json(), facility_id):
            if start.isoformat() <= s.date <= end.isoformat():
                slots[(s.date, s.start, s.end)] = s
        day += dt.timedelta(days=7)
    return list(slots.values())


# --------------------------------------------------------------------------- output

def print_table(windows: list[Window]) -> None:
    if not windows:
        print("No slots found that match your filters.")
        return
    rows = [("Date", "Time", "Mins", "Free", "Court", "£", "Size", "Drive", "Link")]
    for w in windows:
        day = dt.date.fromisoformat(w.date).strftime("%a %d %b")
        rows.append((day, f"{w.start}-{w.end}", str(w.minutes), f"{w.min_free_pct}%",
                     w.court, "" if w.price is None else f"{w.price:g}",
                     w.court_size, "" if w.drive_min is None else f"{w.drive_min}m",
                     w.link))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    for n, row in enumerate(rows):
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(row[:-1])) + "  " + row[-1])
        if n == 0:
            print("  ".join("-" * w for w in widths) + "  ----")


def write_html(windows: list[Window], path: Path, criteria: str) -> None:
    body = "".join(
        "<tr>"
        f"<td>{dt.date.fromisoformat(w.date).strftime('%a %d %b')}</td>"
        f"<td>{w.start}–{w.end}</td><td>{w.minutes}</td><td>{w.min_free_pct}%</td>"
        f"<td>{html.escape(w.court)}</td>"
        f"<td>{'' if w.price is None else f'£{w.price:g}'}</td>"
        f"<td>{html.escape(w.court_size)}</td>"
        f"<td>{'' if w.drive_min is None else f'{w.drive_min} min'}</td>"
        f"<td>{html.escape(w.notes)}</td>"
        f"<td><a href=\"{html.escape(w.link)}\">book</a></td></tr>"
        for w in windows
    ) or '<tr><td colspan="10">No slots found that match your filters.</td></tr>'
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Free Basketball Courts</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#111}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:6px 8px;border-bottom:1px solid #ddd;text-align:left;white-space:nowrap}}
th{{background:#f4f4f4}} .wrap{{overflow-x:auto}}
@media (prefers-color-scheme: dark){{body{{background:#111;color:#eee}}
th{{background:#222}} th,td{{border-color:#333}} a{{color:#8ab4f8}}}}
</style></head><body>
<h1>Free basketball courts</h1>
<p>{html.escape(criteria)}. Generated {generated}.</p>
<div class="wrap"><table><thead><tr><th>Date</th><th>Time</th><th>Mins</th>
<th>Free</th><th>Court</th><th>Price</th><th>Size</th><th>Drive</th><th>Notes</th>
<th></th></tr></thead><tbody>{body}</tbody></table></div>
</body></html>
""", encoding="utf-8")


# --------------------------------------------------------------------------- main

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--courts", default=Path(__file__).with_name("courts.json"), type=Path,
                   help="court list (default: courts.json next to this script)")
    p.add_argument("--start", type=dt.date.fromisoformat, default=dt.date.today(),
                   help="first date to check, YYYY-MM-DD (default: today)")
    p.add_argument("--days", type=int, default=14, help="how many days to check (default: 14)")
    p.add_argument("--min-free", type=int, default=50,
                   help="minimum %% of the hall that must be free (default: 50)")
    p.add_argument("--min-minutes", type=int, default=60,
                   help="shortest window worth reporting (default: 60)")
    p.add_argument("--after", help="only times from HH:MM, e.g. 18:00")
    p.add_argument("--before", help="only times until HH:MM, e.g. 22:00")
    p.add_argument("--weekdays", help="comma list, e.g. sat,sun or mon,wed,fri")
    p.add_argument("--only", help="only courts whose name contains this text")
    p.add_argument("--sort", choices=["date", "price", "drive"], default="date")
    p.add_argument("--delay", type=float, default=1.0,
                   help="seconds between requests, be gentle (default: 1)")
    p.add_argument("--html", type=Path, help="also write the results to this HTML file")
    p.add_argument("--json", type=Path, help="also write the results to this JSON file")
    p.add_argument("--fixture", type=Path,
                   help="parse a saved calendar.json instead of fetching (for testing)")
    args = p.parse_args(argv)
    if args.weekdays:
        try:
            args.weekdays = {WEEKDAYS.index(d.strip().lower()[:3])
                             for d in args.weekdays.split(",")}
        except ValueError:
            p.error(f"--weekdays must use {','.join(WEEKDAYS)}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    courts = json.loads(args.courts.read_text(encoding="utf-8"))
    if args.only:
        courts = [c for c in courts if args.only.lower() in c["name"].lower()]
    end = args.start + dt.timedelta(days=args.days - 1)

    session = None
    if not args.fixture:
        import requests  # imported here so --fixture works without it installed
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

    results: list[Window] = []
    for court in courts:
        page = court["url"].split("?")[0]
        facility_id = facility_id_from_url(page)
        if args.fixture:
            data = json.loads(args.fixture.read_text(encoding="utf-8"))
            if not any(f.get("id") == facility_id for f in data.get("facilities", [])):
                continue
            slots = parse_calendar(data, facility_id)
        else:
            print(f"Checking {court['name']}...", file=sys.stderr)
            try:
                slots = fetch_weeks(session, page, args.start, end, args.delay)
            except Exception as e:  # keep going if one court fails
                print(f"  failed: {e}", file=sys.stderr)
                continue

        for date, s, e, pct in find_windows(slots, args.min_free, args.min_minutes,
                                            args.after, args.before, args.weekdays):
            results.append(Window(
                court=court["name"], date=date, start=from_minutes(s), end=from_minutes(e),
                minutes=e - s, min_free_pct=pct, price=court.get("price"),
                court_size=court.get("court", ""), drive_min=court.get("drive_min"),
                notes=court.get("notes", ""), link=f"{page}?date={date}"))

    sort_keys = {
        "date": lambda w: (w.date, w.start, w.price or 0, w.drive_min or 0),
        "price": lambda w: (w.price or 0, w.date, w.start),
        "drive": lambda w: (w.drive_min or 0, w.date, w.start),
    }
    results.sort(key=sort_keys[args.sort])

    criteria = (f"At least {args.min_free}% free for {args.min_minutes}+ min, "
                f"{args.start:%d %b}–{end:%d %b}")
    if args.after or args.before:
        criteria += f", {args.after or '00:00'}–{args.before or '24:00'}"
    if args.weekdays:
        criteria += ", " + "/".join(WEEKDAYS[d] for d in sorted(args.weekdays))
    print(criteria + "\n")
    print_table(results)
    if args.html:
        write_html(results, args.html, criteria)
        print(f"\nWrote {args.html}", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps([asdict(w) for w in results], indent=2), encoding="utf-8")
        print(f"Wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
