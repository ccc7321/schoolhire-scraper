"""Drive time estimates from TomTom, for courts that don't have your own guess.

Places are turned into coordinates first: UK postcodes with postcodes.io (free,
no key), anything else ("Pell St, London") with TomTom's geocoder. Then
TomTom's Routing API works out the drive for a chosen departure, e.g. the next
Tuesday at 18:00, using its typical traffic for that time:

    GET https://api.tomtom.com/routing/1/calculateRoute/<lat,lon>:<lat,lon>/json
        ?key=...&travelMode=car&traffic=true&departAt=2026-10-27T18:00:00

A free TomTom key (https://developer.tomtom.com, no card needed) goes in
settings.json next to this file, or the TOMTOM_API_KEY environment variable.
settings.json isn't in git.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

import courts as store

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "settings.json"
POSTCODES_API = "https://api.postcodes.io/postcodes/"
TOMTOM_API = "https://api.tomtom.com"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
POSTCODE_RE = re.compile(r"^\s*[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\s*$", re.I)
CALL_GAP = 0.25  # seconds between TomTom calls, well inside the free tier's rate limit

_lock = threading.Lock()
_places: dict[str, tuple[float, float]] = {}  # place text -> (lat, lon), for this run


class DriveError(store.CourtError):
    """Something the person can fix: no key, a place that can't be found, ...

    fatal: it would fail for every court too (bad key, rate limit), so stop.
    """

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


# --------------------------------------------------------------------------- key

def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def api_key() -> str:
    return os.environ.get("TOMTOM_API_KEY") or load_settings().get("tomtom_key", "")


def save_key(key: str) -> None:
    key = str(key or "").strip()
    if key and not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", key):
        raise DriveError("that doesn't look like a TomTom key; copy it from "
                         "developer.tomtom.com → Dashboard → Keys")
    with _lock:
        settings = load_settings()
        if key:
            settings["tomtom_key"] = key
        else:
            settings.pop("tomtom_key", None)
        SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def key_status() -> dict:
    """Whether there's a key, without ever sending the key itself to the page."""
    key = api_key()
    return {"tomtom_key_set": bool(key), "key_hint": f"…{key[-4:]}" if key else "",
            "from_env": bool(os.environ.get("TOMTOM_API_KEY"))}


# --------------------------------------------------------------------------- departure

def parse_depart(text: str | None) -> tuple[str, str] | None:
    """"tue 18:00" -> ("tue", "18:00"); "now" or "" -> None (leave now)."""
    text = " ".join(str(text or "").lower().split())
    if text in ("", "now"):
        return None
    m = re.fullmatch(r"(mon|tue|wed|thu|fri|sat|sun)\w* (\d{1,2}):(\d{2})", text)
    if not m or int(m.group(2)) > 23 or int(m.group(3)) > 59:
        raise DriveError('the departure must be "now" or a day and time, e.g. "tue 18:00"')
    return m.group(1), f"{int(m.group(2)):02d}:{m.group(3)}"


def next_departure(day: str, hhmm: str, now: dt.datetime) -> dt.datetime:
    """The next time it's that day and time, at least 10 minutes from now."""
    h, m = map(int, hhmm.split(":"))
    when = now.replace(hour=h, minute=m, second=0, microsecond=0)
    when += dt.timedelta(days=(WEEKDAYS.index(day) - now.weekday()) % 7)
    if when < now + dt.timedelta(minutes=10):
        when += dt.timedelta(days=7)
    return when


def depart_label(depart: tuple[str, str] | None) -> str:
    return "now" if depart is None else f"{depart[0].title()} {depart[1]}"


# --------------------------------------------------------------------------- lookups

def new_session():
    import requests
    from schoolhire import USER_AGENT
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def get_json(session, url: str, params: dict | None = None) -> dict:
    r = session.get(url, params=params, timeout=30)
    if r.status_code in (401, 403):
        raise DriveError("TomTom refused the key; check it on developer.tomtom.com", fatal=True)
    if r.status_code == 429:
        raise DriveError("TomTom says too many requests; wait a minute and try again", fatal=True)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return r.json()


def locate(place: str, key: str, session) -> tuple[float, float]:
    """(lat, lon) for a UK postcode or a place name."""
    place = " ".join(str(place or "").split())
    if not place:
        raise DriveError("no place to look up")
    if place.lower() in _places:
        return _places[place.lower()]
    found = None
    if POSTCODE_RE.match(place):
        result = get_json(session, POSTCODES_API + quote(place.replace(" ", ""))).get("result")
        if result and result.get("latitude") is not None:
            found = (result["latitude"], result["longitude"])
    if found is None:
        time.sleep(CALL_GAP)
        results = get_json(session, f"{TOMTOM_API}/search/2/geocode/{quote(place)}.json",
                           {"key": key, "countrySet": "GB", "limit": 1}).get("results") or []
        if results:
            found = (results[0]["position"]["lat"], results[0]["position"]["lon"])
    if found is None:
        raise DriveError(f"couldn't find {place!r} on the map; try a postcode")
    _places[place.lower()] = found
    return found


def route(origin: tuple[float, float], dest: tuple[float, float], key: str, session,
          depart_at: dt.datetime | None = None) -> dict:
    """{"min": whole minutes (rounded up), "miles": one decimal place}."""
    params = {"key": key, "travelMode": "car", "traffic": "true", "routeType": "fastest"}
    if depart_at:
        # no time zone: TomTom takes it as local time at the start, i.e. UK time
        params["departAt"] = depart_at.strftime("%Y-%m-%dT%H:%M:%S")
    time.sleep(CALL_GAP)
    path = f"{origin[0]},{origin[1]}:{dest[0]},{dest[1]}"
    routes = get_json(session, f"{TOMTOM_API}/routing/1/calculateRoute/{path}/json",
                      params).get("routes") or []
    if not routes:
        raise DriveError("TomTom found no driving route")
    summary = routes[0]["summary"]
    return {"min": math.ceil(summary["travelTimeInSeconds"] / 60),
            "miles": round(summary["lengthInMeters"] / 1609.344, 1)}


# --------------------------------------------------------------------------- whole group

def estimate_group(group_id: str, depart: str | None = None, replace_guesses: bool = False,
                   session=None, now: dt.datetime | None = None) -> dict:
    """Fill in TomTom drive times for a group's courts.

    Courts with your own guess are left alone unless replace_guesses is set;
    earlier TomTom estimates are always refreshed. Returns
    {"updated": [names], "skipped": [names with your guess], "failed": {name: reason}}.
    """
    key = api_key()
    if not key:
        raise DriveError("add your free TomTom key first (Settings below)")
    when = parse_depart(depart)
    group = store.find_group(store.load(), group_id)
    if not (group.get("from") or "").strip():
        raise DriveError("set where this group is driving from first, e.g. a postcode")
    session = session or new_session()
    depart_at = next_departure(*when, now or dt.datetime.now()) if when else None
    label = depart_label(when)
    origin = locate(group["from"], key, session)

    results, skipped, failed = {}, [], {}
    for court in group["courts"]:
        if court.get("drive_min") is not None and court.get("drive_source") != "tomtom" \
                and not replace_guesses:
            skipped.append(court["name"])
            continue
        try:
            dest = locate(court.get("postcode") or court["name"], key, session)
            results[court["url"]] = route(origin, dest, key, session, depart_at)
        except DriveError as e:
            if e.fatal:
                raise  # no point trying the other courts
            failed[court["name"]] = str(e)
        except Exception as e:  # network trouble: keep going with the others
            failed[court["name"]] = str(e)

    def save(data):
        g = store.find_group(data, group_id)
        g["depart"] = label.lower()
        for c in g["courts"]:
            if c["url"] in results:
                c.update(drive_min=results[c["url"]]["min"], drive_miles=results[c["url"]]["miles"],
                         drive_source="tomtom", drive_when=label)
    store.change(save)
    names = {c["url"]: c["name"] for c in group["courts"]}
    return {"updated": [names[u] for u in results], "skipped": skipped, "failed": failed,
            "depart": label}
