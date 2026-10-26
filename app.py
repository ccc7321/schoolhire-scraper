#!/usr/bin/env python3
"""Local web page showing basketball court slots that are at least N% free.

    python app.py                    # opens http://127.0.0.1:5050
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
import drive
import search
import schoolhire as sh

HERE = Path(__file__).resolve().parent
CACHE_MINUTES = 10
MAX_DAYS = 42

app = Flask(__name__)
app.json.sort_keys = False
config = {"fixture": None, "delay": 1.0}

# court url -> {"key": (start, days), "at": epoch secs, "slots": [...], "error": str|None}
_cache: dict[str, dict] = {}
_lock = threading.Lock()  # guards _cache and _court_locks, never held while fetching
_court_locks: dict[str, threading.Lock] = {}  # one per court, so a court is fetched once at a time
REFETCH_GAP = 5  # seconds: a refresh right after a fetch (e.g. a double click) reuses it
ERROR_RETRY = 60  # seconds: a court that failed is tried again after this, or on Refresh


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


def is_fresh(url: str, start: dt.date, days: int) -> bool:
    """Whether the cache has a recent answer for this court and date range: its
    slots, or an error that's too recent to be worth trying again yet."""
    entry = _cache.get(url)
    max_age = ERROR_RETRY if entry and entry["error"] else CACHE_MINUTES * 60
    return bool(entry and entry["key"] == (start, days) and time.time() - entry["at"] <= max_age)


def fetch_court(court: dict, start: dt.date, days: int, refresh: bool = False) -> dict:
    """Make sure one court is in the cache (fetching it if needed) and return its entry.

    Different courts are fetched in parallel; the same court waits for a fetch
    that's already running instead of starting a second one.
    """
    url = court["url"]
    with _lock:
        court_lock = _court_locks.setdefault(url, threading.Lock())
    with court_lock:
        with _lock:
            entry = _cache.get(url)
            just_fetched = (entry and entry["key"] == (start, days)
                            and time.time() - entry["at"] < REFETCH_GAP)
            if is_fresh(url, start, days) and (not refresh or just_fetched):
                return entry
        entry = fetch_one(court, start, days)
        with _lock:
            _cache[url] = entry
        return entry


def get_slots(courts: list[dict], start: dt.date, days: int, refresh: bool) -> None:
    """Fill the cache for every court that is missing, stale or refreshed."""
    if courts:
        with ThreadPoolExecutor(max_workers=len(courts)) as pool:
            list(pool.map(lambda c: fetch_court(c, start, days, refresh), courts))


def groups_summary(data: dict) -> list[dict]:
    return [{"id": g["id"], "name": g["name"], "from": g.get("from", ""),
             "depart": g.get("depart", ""), "courts": g["courts"]} for g in data["groups"]]


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
    # fetch=0: answer straight away from what's loaded so far, marking the rest
    # "pending"; the page then asks /api/fetch for each pending court.
    fetch = q.get("fetch") != "0"
    if fetch:
        get_slots(courts, start, days, refresh=q.get("refresh") == "1")

    windows, statuses = [], []
    for court in courts:
        with _lock:
            entry = _cache.get(court["url"])
            pending = not fetch and not is_fresh(court["url"], start, days)
        if entry is None or (pending and entry["key"] != (start, days)):
            entry = {"at": None, "slots": [], "error": None}  # nothing usable yet
        statuses.append({
            "name": court["name"], "price": court.get("price"), "court": court.get("court", ""),
            "notes": court.get("notes", ""), "url": court["url"], "drive": court["drive"],
            "directions": court["directions"],
            "pending": pending, "error": None if pending else entry["error"],
            "slots": len(entry["slots"]),
            "fetched_at": entry["at"] and dt.datetime.fromtimestamp(entry["at"]).strftime("%H:%M"),
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

@app.errorhandler(search.SearchError)
def search_error(e):
    return jsonify({"error": str(e)}), 400


@app.get("/api/search")
def api_search():
    """?place=NW9 4GD&miles=10: basketball courts near a postcode, nearest first,
    each marked with the groups it's already in."""
    try:
        miles = int(request.args.get("miles", 10))
    except ValueError:
        return jsonify({"error": "bad distance"}), 400
    place = request.args.get("place", "")
    try:
        if config["fixture"]:  # demo: the saved search near NW9, no network
            page = (HERE / "tests" / "search_results.html").read_text(encoding="utf-8")
            center = search.center_from_page(page)
            found = {"place": "NW9 (demo)", "center": {"lat": center[0], "lng": center[1]},
                     "miles": 10, "results": search.parse_results(page, center)}
            found["total"] = len(found["results"])
        else:
            found = search.find_courts(place, miles)
    except search.SearchError:
        raise
    except Exception as e:  # schoolhire.co.uk or postcodes.io down, a timeout, …
        return jsonify({"error": f"couldn't search schoolhire.co.uk: {e}"}), 502
    groups = store.load()["groups"]
    for r in found["results"]:
        r["in_groups"] = [g["name"] for g in groups if any(c["url"] == r["url"] for c in g["courts"])]
    return jsonify(found)


@app.post("/api/fetch")
def api_fetch():
    """{"url": a court in your groups, "days": 14, "refresh": true}: fetch that one
    court (unless it's already cached) so the page can show progress court by court."""
    body = request.get_json(force=True)
    try:
        days = max(1, min(MAX_DAYS, int(body.get("days", 14))))
    except (TypeError, ValueError):
        return jsonify({"error": "bad days"}), 400
    court = next((c for c in store.courts_in(store.load()) if c["url"] == body.get("url")), None)
    if court is None:  # only courts you've added are ever fetched
        return jsonify({"error": "that court isn't in any of your groups"}), 404
    entry = fetch_court(court, default_start(), days, bool(body.get("refresh")))
    return jsonify({"url": court["url"], "error": entry["error"], "slots": len(entry["slots"])})


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


@app.post("/api/groups/<gid>/estimate")
def api_estimate(gid):
    """{"depart": "tue 18:00" or "now", "replace": true to overwrite your own guesses}."""
    body = request.get_json(force=True)
    try:
        result = drive.estimate_group(gid, body.get("depart"), bool(body.get("replace")))
    except store.CourtError:
        raise
    except Exception as e:  # TomTom or postcodes.io down, a timeout, …
        return jsonify({"error": f"couldn't get drive times: {e}"}), 502
    return jsonify({**result, "groups": groups_summary(store.load())})


@app.get("/api/settings")
def api_settings():
    return jsonify(drive.key_status())


@app.put("/api/settings")
def api_save_settings():
    """{"tomtom_key": "..."}; an empty key removes it."""
    drive.save_key(request.get_json(force=True).get("tomtom_key", ""))
    return jsonify(drive.key_status())


@app.get("/")
def index():
    return (HERE / "static" / "index.html").read_text(encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", type=int, default=5050,
                   help="default 5050 (macOS uses 5000 for AirPlay Receiver)")
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
