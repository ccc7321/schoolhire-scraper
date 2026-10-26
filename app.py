#!/usr/bin/env python3
"""Local web page showing basketball court slots that are at least N% free.

    python app.py                    # opens http://127.0.0.1:5000
    python app.py --fixture get.json # demo with the saved sample, no network

Courts are kept in groups that you make on the page (saved in courts.json).
Add a court by pasting its schoolhire.co.uk link. The court calendars are
fetched in parallel and cached for a few minutes, so changing the filters on
the page is instant and doesn't hit schoolhire.co.uk again. Press "Refresh"
on the page to fetch fresh data.
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

import courts as store
import schoolhire as sh

HERE = Path(__file__).resolve().parent
CACHE_MINUTES = 10
MAX_DAYS = 42

app = Flask(__name__)
app.json.sort_keys = False
config = {"fixture": None, "delay": 1.0}

# court url -> {"key": (start, days), "at": epoch secs, "slots": [...], "error": str|None}
_cache: dict[str, dict] = {}
_lock = threading.Lock()


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
                 or c["url"] not in _cache
                 or _cache[c["url"]]["key"] != (start, days)
                 or _cache[c["url"]]["error"]
                 or now - _cache[c["url"]]["at"] > CACHE_MINUTES * 60]
        if stale:
            with ThreadPoolExecutor(max_workers=len(stale)) as pool:
                for court, entry in zip(stale, pool.map(
                        lambda c: fetch_one(c, start, days), stale)):
                    _cache[court["url"]] = entry


def groups_summary(data: dict) -> list[dict]:
    return [{"id": g["id"], "name": g["name"], "from": g.get("from", ""), "courts": g["courts"]}
            for g in data["groups"]]


@app.errorhandler(store.CourtError)
def court_error(e):
    return jsonify({"error": str(e)}), 400


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
    sort = q.get("sort") if q.get("sort") in sh.SORTS else "date"
    hidden = set(filter(None, q.get("hide", "").split("|")))

    data = store.load()
    group = q.get("group") or ""
    if group and not any(g["id"] == group for g in data["groups"]):
        group = ""  # deleted meanwhile: show every court
    courts = store.courts_in(data, group or None)  # only the chosen group's courts are fetched
    start = default_start()
    get_slots(courts, start, days, refresh=q.get("refresh") == "1")

    windows, statuses = [], []
    for court in courts:
        entry = _cache[court["url"]]
        statuses.append({
            "name": court["name"], "price": court.get("price"), "court": court.get("court", ""),
            "notes": court.get("notes", ""), "url": court["url"], "drive": court["drive"],
            "error": entry["error"], "slots": len(entry["slots"]),
            "fetched_at": dt.datetime.fromtimestamp(entry["at"]).strftime("%H:%M"),
        })
        if court["url"] not in hidden:
            windows += sh.court_windows(court, entry["slots"], min_free, min_minutes,
                                        after, before, weekdays)
    windows.sort(key=sh.SORT_KEYS[sort])
    return jsonify({
        "group": group,
        "groups": [{"id": g["id"], "name": g["name"]} for g in data["groups"]],
        "start": start.isoformat(),
        "end": (start + dt.timedelta(days=days - 1)).isoformat(),
        "demo": bool(config["fixture"]),
        "courts": statuses,
        "windows": [asdict(w) for w in windows],
    })


# --------------------------------------------------------------------------- groups & courts

@app.get("/api/groups")
def api_groups():
    return jsonify(groups_summary(store.load()))


@app.post("/api/groups")
def api_add_group():
    data = store.add_group(request.get_json(force=True).get("name"))
    return jsonify(groups_summary(data))


@app.put("/api/groups/<gid>")
def api_update_group(gid):
    """{"name": ...} and/or {"from": "Pell St"}, where the group drives from."""
    body = request.get_json(force=True)
    data = store.update_group(gid, {k: body[k] for k in ("name", "from") if k in body})
    return jsonify(groups_summary(data))


@app.delete("/api/groups/<gid>")
def api_delete_group(gid):
    return jsonify(groups_summary(store.delete_group(gid)))


@app.post("/api/groups/<gid>/courts")
def api_add_court(gid):
    """{"url": "<a schoolhire.co.uk court link>"}: reads the court's page and adds it."""
    link = request.get_json(force=True).get("url", "")
    try:
        court = store.add_court(gid, link)
    except store.CourtError:
        raise
    except Exception as e:  # the site is down, a timeout, …
        return jsonify({"error": f"couldn't read that court's page: {e}"}), 502
    return jsonify({"added": court, "groups": groups_summary(store.load())})


@app.patch("/api/groups/<gid>/courts")
def api_edit_court(gid):
    """{"url": ..., and any of "name", "price", "court", "notes", "drive_min"}."""
    body = request.get_json(force=True)
    data = store.edit_court(gid, body.get("url", ""), body)
    return jsonify(groups_summary(data))


@app.delete("/api/groups/<gid>/courts")
def api_remove_court(gid):
    data = store.remove_court(gid, request.args.get("url", ""))
    return jsonify(groups_summary(data))


@app.get("/")
def index():
    return (HERE / "static" / "index.html").read_text(encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--host", default="127.0.0.1",
                   help="use 0.0.0.0 to open it from your phone on the same Wi-Fi")
    p.add_argument("--courts", type=Path,
                   help="where your groups are saved (default: courts.json next to app.py)")
    p.add_argument("--fixture", type=Path, help="use a saved calendar.json, no network")
    p.add_argument("--delay", type=float, default=1.0,
                   help="seconds between requests to the same court (default: 1)")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = p.parse_args()
    config.update(fixture=args.fixture, delay=args.delay)
    if args.courts:
        store.PATH = args.courts

    url = f"http://127.0.0.1:{args.port}"
    print(f"Court finder running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
