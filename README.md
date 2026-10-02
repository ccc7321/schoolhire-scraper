# schoolhire-scraper

A small local web app that checks the basketball courts in `courts.json` on
schoolhire.co.uk and Brunel University's sports centre, and shows every time window where **at least 50% of the hall
is free**, so you don't have to click through each court's calendar yourself.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Your browser opens at http://127.0.0.1:5000. On Windows you can just
double-click `start.bat` instead.

On the page you can:

- pick how far ahead to look (1–4 weeks), the minimum % free, and the shortest
  slot worth booking
- limit to certain times (e.g. from 18:00) and days (e.g. Sat, Sun)
- switch individual courts on or off, and sort by date, price or drive time from
  Pell St or Colindale (each slot shows minutes and miles from both)
- press **Book ↗** to open that court's calendar on schoolhire.co.uk for that day

Your filters are remembered between visits. Court data is cached for 10
minutes, so changing filters is instant. Press **Refresh from site** to fetch
new data.

Other ways to start it:

```bash
python app.py --fixture get.json   # demo with the saved sample, no internet needed
python app.py --host 0.0.0.0       # also reachable from your phone on the same Wi-Fi
python app.py --port 8080 --no-browser
```

## How it works

For each court the script loads the court page (to get fresh `XSRF-TOKEN` and
session cookies), then calls the same endpoint the site's calendar uses:

```
GET https://schoolhire.co.uk/calendar.json?facility_id=<id>&date=YYYY-MM-DD&view=week
```

Each slot in the response is converted to a "% free" figure:

| Site shows        | `className`        | % free |
|-------------------|--------------------|--------|
| `Available`       | `available`        | 100    |
| `50% busy`        | `partially_booked` | 50     |
| `75% busy`        | `partially_booked` | 25     |
| `Booked`          | `fully_booked`     | 0      |

Back-to-back slots that meet the threshold are joined into one window (e.g.
17:00–18:00 Available + 18:00–19:00 50% busy → 17:00–19:00, at least 50% free).
Windows shorter than `--min-minutes` are dropped. `get.json` is a saved sample
response, used by the tests.

### Brunel University

Courts with `"source": "brunel"` in `courts.json` come from Brunel's GladstoneGo
booking site instead. The script gets an anonymous `Jwt` cookie from
`/api/samlauthentication/anonymous`, then calls the same endpoint as
https://brunelsport.gladstonego.cloud/book:

```
GET https://brunelsport.gladstonego.cloud/api/availability/V2/sessions
    ?webBookableOnly=true&siteIds=UB&activityIds=<activity_id>&dateFrom=...&dateTo=...
```

Each hourly session is either `Available` (100% free) or `Unavailable` (0%).
Times are converted from UTC to UK time, and the 5-minute changeover between
sessions is counted as part of the session before it, so back-to-back sessions
join up (07:30–08:25 + 08:30–09:25 → 07:30–09:25). Two activities are listed:

| Court                | `activity_id`   | What it is                         |
|----------------------|-----------------|------------------------------------|
| Brunel Sports Hall   | `SHBASKHALF12`  | Basketball half court, courts 1&2  |
| Brunel Netball Hall  | `NHBASKETBALL`  | Basketball in the Netball Hall     |

(`SHBASKHALF34` exists too but currently has no bookable sessions.) Brunel
only shows the price when you book, so the prices in `courts.json` are
hardcoded from the booking page (£20 per hour for a half court, £40 for the
Netball Hall); update them if they change. A court with `"price": null` shows
"price on site" and sorts last by price. `brunel.json` is a saved sample response
used by the tests and demo mode.

## Command-line version

`schoolhire.py` does the same checks and prints a table, which is handy for
scripts:

```bash
python schoolhire.py                               # next 14 days, >=50% free, >=60 min
python schoolhire.py --days 21 --after 18:00       # evenings, next 3 weeks
python schoolhire.py --weekdays sat,sun --min-minutes 90
python schoolhire.py --min-free 100                # whole hall free only
python schoolhire.py --sort price --html results.html
python schoolhire.py --only bow                    # one court
python schoolhire.py --fixture get.json --start 2026-09-28 --days 7   # offline test
```

| Option          | Default | Meaning                                          |
|-----------------|---------|--------------------------------------------------|
| `--start`       | today   | first date to check                              |
| `--days`        | 14      | number of days to check                          |
| `--min-free`    | 50      | minimum % of the hall that must be free          |
| `--min-minutes` | 60      | shortest window worth listing                    |
| `--after` / `--before` | – | only times in this range, e.g. `18:00` `22:00` |
| `--weekdays`    | all     | e.g. `sat,sun` or `mon,wed,fri`                  |
| `--only`        | –       | only courts whose name contains this text        |
| `--group`       | all     | only one team's courts, e.g. `KongBaller`        |
| `--sort`        | date    | `date`, `price` or `drive`                       |
| `--from`        | first   | with `--sort drive`: e.g. `Colindale`            |
| `--html` / `--json` | –   | also save the results to a file                  |
| `--delay`       | 1       | seconds between requests                         |

Example output:

```
Date        Time         Mins  Free  Court                         £     Size  Drive  Link
Tue 29 Sep  17:00-19:00  120   50%   Dagenham Park Leisure Centre  28.5  half  37m    https://schoolhire.co.uk/...17294?date=2026-09-29
Sat 03 Oct  14:00-18:00  240   100%  Dagenham Park Leisure Centre  28.5  half  37m    https://schoolhire.co.uk/...17294?date=2026-10-03
```

"Free" is the lowest % free across the whole window.

## Adding or removing courts

Edit `courts.json`. The facility id is taken from the number at the end of
`url`; `price`, `court`, `drive` and `notes` are only used for display.
`group` is the team the court belongs to (`KongBaller` for the east London
courts, `Watford` for Brunel). Pick a team on the page, or pass
`--group Watford` on the command line, to check only that team's courts. For a
Brunel court, set `"source": "brunel"` and an `activity_id` instead. The Brunel drive times are OSRM × 1.29 estimates as well.

`drive` lists each starting point with its drive time and distance:

```json
"drive": {
  "Pell St": {"min": 21, "miles": 5.1},
  "Colindale": {"min": 50, "miles": 20.7}
}
```

Add another name there (for every court) and it appears on the page and as a
"Drive from …" sort option. Pell St times came from Google Maps. Miles come
from OSRM (OpenStreetMap routing). The Colindale times are OSRM times × 1.29,
which is how much slower Google's Pell St times were than OSRM's. They're
estimates, so replace them with real Google Maps times if you check them.

## Running it on GitHub

`.github/workflows/check-courts.yml` runs the command-line check when you press
**Run workflow** on the Actions tab (you can pass extra options there, e.g.
`--after 18:00`). Results appear in the run summary and as a downloadable
`results.html`. Add a `schedule:` trigger if you want it to run daily.

## Be polite

Each refresh makes about 2–3 requests per schoolhire court, with a 1 second
pause between them, and 2 requests per Brunel court. A few runs a day is plenty. Check the site's terms before
running it more often.

## Files

| File | What it is |
|------|------------|
| `app.py` | the web app (Flask) |
| `static/index.html` | the page |
| `schoolhire.py` | fetching, parsing and filtering, plus the command-line version |
| `brunel.py` | fetching and parsing Brunel University's GladstoneGo sessions |
| `courts.json` | your courts |
| `get.json` | saved schoolhire sample response, used by the tests and demo mode |
| `brunel.json` | saved Brunel sample response, used by the tests and demo mode |

## Tests

```bash
python -m unittest discover -s tests
```
