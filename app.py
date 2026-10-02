#!/usr/bin/env python3
"""Local web page showing basketball court slots that are at least N% free.

    python app.py                    # opens http://127.0.0.1:5000
    python app.py --fixture get.json # demo with the saved sample, no network

The court calendars are fetched in parallel and cached for a few minutes, so
changing the filters on the page is instant and doesn't hit schoolhire.co.uk
or Brunel again. Press "Refresh" on the page to fetch fresh data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, request

import schoolhire as sh

HERE = Path(__file__).resolve().parent
CACHE_MINUTES = 10
MAX_DAYS = 42

app = Flask(__name__)
app.json.sort_keys = False  # keep the drive origins in courts.json order
config = {"courts": HERE / "courts.json", "fixture": None, "delay": 1.0}

# court name -> {"key": (start, days), "at": epoch secs, "slots": [...], "error": str|None}
_cache: dict[str, dict] = {}
_lock = threading.Lock()


def load_courts() -> list[dict]:
    return json.loads(config["courts"].read_text(encoding="utf-8"))


def default_start() -> dt.date:
    """Today, or the first date in the fixture file so the demo shows something."""
    if config["fixture"]:
        data = json.loads(config["fixture"].read_text(encoding="utf-8"))
        return dt.date.fromisoformat(data["days"][0]["date"])
    return dt.date.today()


def fetch_one(court: dict, start: dt.date, days: int) -> dict:
    end = start + dt.timedelta(days=days - 1)
    try:
        slots = sh.load_court_slots(court, start, end, config["delay"], config["fixture"])
        return {"key": (start, days), "at": time.time(), "slots": slots, "error": None}
    except Exception as e:  # show the error on the page, keep the other courts
        return {"key": (start, days), "at": time.time(), "slots": [], "error": str(e)}


def get_slots(courts: list[dict], start: dt.date, days: int, refresh: bool) -> None:
    """Fill the cache for every court that is missing, stale or refreshed."""
    with _lock:
        now = time.time()
        stale = [c for c in courts
                 if refresh
                 or c["name"] not in _cache
                 or _cache[c["name"]]["key"] != (start, days)
                 or _cache[c["name"]]["error"]
                 or now - _cache[c["name"]]["at"] > CACHE_MINUTES * 60]
        if stale:
            with ThreadPoolExecutor(max_workers=len(stale)) as pool:
                for court, entry in zip(stale, pool.map(
                        lambda c: fetch_one(c, start, days), stale)):
                    _cache[court["name"]] = entry


@app.get("/api/slots")
def api_slots():
    q = request.args
    try:
        days = max(1, min(MAX_DAYS, int(q.get("days", 14))))
        min_free = int(q.get("min_free", 50))
        min_minutes = int(q.get("min_minutes", 60))
        after = q.get("after") or None
        before = q.get("before") or None
        for t in (after, before):
            if t:
                sh.to_minutes(t)
        weekdays = ({int(d) for d in q["weekdays"].split(",") if d != ""}
                    if q.get("weekdays") else None)
    except ValueError as e:
        return jsonify({"error": f"bad filter value: {e}"}), 400
    # "drive:Colindale" sorts by the drive time from Colindale
    sort, _, origin = q.get("sort", "date").partition(":")
    if sort not in sh.SORTS:
        sort, origin = "date", ""
    hidden = set(filter(None, q.get("hide", "").split("|")))

    all_courts = load_courts()
    groups = list(dict.fromkeys(c["group"] for c in all_courts if c.get("group")))
    # only the chosen team's courts are fetched and shown
    courts = [c for c in all_courts if sh.in_group(c, q.get("group"))]
    start = default_start()
    get_slots(courts, start, days, refresh=q.get("refresh") == "1")

    windows, statuses = [], []
    for court in courts:
        entry = _cache[court["name"]]
        statuses.append({
            "name": court["name"], "group": court.get("group", ""),
            "price": court.get("price"),
            "court": court.get("court", ""), "drive": court.get("drive", {}),
            "notes": court.get("notes", ""), "url": court["url"].split("?")[0],
            "error": entry["error"], "slots": len(entry["slots"]),
            "fetched_at": dt.datetime.fromtimestamp(entry["at"]).strftime("%H:%M"),
        })
        if court["name"] not in hidden:
            windows += sh.court_windows(court, entry["slots"], min_free, min_minutes,
                                        after, before, weekdays)
    windows.sort(key=sh.sort_key(sort, origin or None))
    origins = list(dict.fromkeys(o for c in courts for o in c.get("drive", {})))
    return jsonify({
        "origins": origins,
        "groups": groups,
        "start": start.isoformat(),
        "end": (start + dt.timedelta(days=days - 1)).isoformat(),
        "demo": bool(config["fixture"]),
        "courts": statuses,
        "windows": [asdict(w) for w in windows],
    })


@app.get("/")
def index():
    return (HERE / "static" / "index.html").read_text(encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--host", default="127.0.0.1",
                   help="use 0.0.0.0 to open it from your phone on the same Wi-Fi")
    p.add_argument("--courts", type=Path, default=config["courts"])
    p.add_argument("--fixture", type=Path, help="use a saved calendar.json, no network")
    p.add_argument("--delay", type=float, default=1.0,
                   help="seconds between requests to the same court (default: 1)")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = p.parse_args()
    config.update(courts=args.courts, fixture=args.fixture, delay=args.delay)

    url = f"http://127.0.0.1:{args.port}"
    print(f"Court finder running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
