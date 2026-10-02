"""Brunel University sports hall courts, booked through GladstoneGo.

The booking site (https://brunelsport.gladstonego.cloud/book) asks this API for
the free sessions of each activity, e.g. NHBASKETBALL or SHBASKHALF12:

    GET /api/availability/V2/sessions?siteIds=UB&activityIds=...&dateFrom=...&dateTo=...

It needs an anonymous "Jwt" cookie, which /api/samlauthentication/anonymous
hands out, plus an "x-use-sso: 1" header. Times come back in UTC.

Each hourly session is listed once per court it covers, all with the same
status, so a session is 100% free when they're all "Available".
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from schoolhire import Slot, USER_AGENT, from_minutes, to_minutes

BASE = "https://brunelsport.gladstonego.cloud"
BOOK_URL = f"{BASE}/book"
SITE_ID = "UB"
CHANGEOVER_MIN = 5  # sessions run e.g. 18:00-18:54:59, then the next starts at 19:00


def uk_time(utc: dt.datetime) -> dt.datetime:
    """UTC -> UK local time (BST from 01:00 UTC on the last Sunday of March
    until 01:00 UTC on the last Sunday of October)."""
    def last_sunday(month: int) -> dt.datetime:
        d = dt.datetime(utc.year, month, 31, 1, tzinfo=dt.timezone.utc)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)
    bst = last_sunday(3) <= utc < last_sunday(10)
    return (utc + dt.timedelta(hours=1 if bst else 0)).replace(tzinfo=None)


def parse_utc(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_sessions(data: list[dict], activity_id: str) -> list[Slot]:
    """Turn a sessions response into one Slot per start time, in UK time."""
    # (date, start) -> [end, available count, total count]
    by_start: dict[tuple[str, str], list] = {}
    for activity in data:
        if activity.get("id") != activity_id:
            continue
        for location in activity.get("locations", []):
            for s in location.get("slots", []):
                start = uk_time(parse_utc(s["startTime"]))
                # round 18:54:59 up to 18:55
                end = uk_time(parse_utc(s["endTime"]) + dt.timedelta(seconds=59))
                key = (start.date().isoformat(), start.strftime("%H:%M"))
                entry = by_start.setdefault(key, [end.strftime("%H:%M"), 0, 0])
                free = s.get("status") == "Available" and (s.get("availability") or {}).get("inCentre", 0) > 0
                entry[1] += free
                entry[2] += 1

    starts: dict[str, set[int]] = {}
    for date, start in by_start:
        starts.setdefault(date, set()).add(to_minutes(start))

    slots = []
    for (date, start), (end, free, total) in sorted(by_start.items()):
        end_min = to_minutes(end)
        # stretch over the changeover gap so back-to-back sessions join up
        nxt = [m for m in starts[date] if end_min <= m <= end_min + CHANGEOVER_MIN]
        if nxt:
            end_min = min(nxt)
        pct = round(100 * free / total)
        slots.append(Slot(date, start, from_minutes(end_min), pct,
                          "available" if pct == 100 else "booked" if pct == 0 else "partially_booked"))
    return slots


def fetch_sessions(session, activity_id: str, start: dt.date, end: dt.date) -> list[dict]:
    headers = {"Accept": "application/json, text/plain, */*", "x-use-sso": "1",
               "Referer": BOOK_URL}
    session.get(f"{BASE}/api/samlauthentication/anonymous", timeout=30,
                headers=headers).raise_for_status()
    # the API rejects a dateFrom in the past, so start from now on today
    now = dt.datetime.now(dt.timezone.utc)
    date_from = max(dt.datetime.combine(start, dt.time(), dt.timezone.utc) - dt.timedelta(hours=1), now)
    date_to = dt.datetime.combine(end, dt.time(23, 59, 59), dt.timezone.utc)
    r = session.get(f"{BASE}/api/availability/V2/sessions", timeout=30, headers=headers, params={
        "webBookableOnly": "true", "siteIds": SITE_ID, "activityIds": activity_id,
        "dateFrom": date_from.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "dateTo": date_to.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
    })
    r.raise_for_status()
    return r.json()


def load_slots(court: dict, start: dt.date, end: dt.date, fixture: Path | None = None,
               session=None) -> list[Slot]:
    """All slots for one Brunel court. With a fixture, reads brunel.json next to it."""
    if fixture:
        data = json.loads(fixture.with_name("brunel.json").read_text(encoding="utf-8"))
    else:
        if session is None:
            import requests
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
        data = fetch_sessions(session, court["activity_id"], start, end)
    return [s for s in parse_sessions(data, court["activity_id"])
            if start.isoformat() <= s.date <= end.isoformat()]
