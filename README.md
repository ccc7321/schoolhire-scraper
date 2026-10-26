# schoolhire-scraper

A small local web app that checks basketball courts on schoolhire.co.uk and
shows every time window where **at least 50% of the hall is free**, so you
don't have to click through each court's calendar yourself.

Keep your courts in **groups**: one for the courts near home, one for the
courts your Tuesday crew plays at, and so on. Add a court by pasting its
schoolhire.co.uk link.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Your browser opens at http://127.0.0.1:5000. On Windows you can just
double-click `start.bat` instead.

It starts with an example group, **East London**, with seven courts in it.
Change it, delete it or make your own under **Manage groups & courts**.

On the page you can:

- pick a group, or **All**, to check only those courts
- pick how far ahead to look (1–4 weeks), the minimum % free, and the shortest
  slot worth booking
- limit to certain times (e.g. from 18:00) and days (e.g. Sat, Sun)
- switch individual courts on or off, and sort by date or price
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

## Groups and courts

Open **Manage groups & courts** on the page:

- **+ New group**, **Rename** and **Delete group** do what they say.
- To add a court, find it on schoolhire.co.uk, copy the address from your
  browser (it looks like
  `https://schoolhire.co.uk/london-brent/kingsbury-high-school-upper/basketball-court/4532?date=…`),
  paste it into the box and press **Add court**. The app reads the school's
  name, postcode and hourly prices from that page. It uses the half-hall
  price when there is one and notes the full-hall price.
- Check the **£ / hour** and **Size** of each court and change them if needed.
  Changes save straight away. **Remove** takes a court out of the group.

The same court can be in more than one group; it's only checked once.

Your groups are saved in `courts.json` next to `app.py`. It's in `.gitignore`,
so everyone keeps their own list. The first time, it starts as a copy of
`courts.example.json`. To start again from the example, delete `courts.json`.

## How it works

For each court the script loads the court page (to get fresh `XSRF-TOKEN` and
session cookies), then calls the same endpoint the site's calendar uses:

```
GET https://schoolhire.co.uk/calendar.json?facility_id=<id>&date=YYYY-MM-DD&view=week
```

The facility id is the number at the end of the court's link. Each slot in the
response is converted to a "% free" figure:

| Site shows        | `className`        | % free |
|-------------------|--------------------|--------|
| `Available`       | `available`        | 100    |
| `50% busy`        | `partially_booked` | 50     |
| `75% busy`        | `partially_booked` | 25     |
| `Booked`          | `fully_booked`     | 0      |

Back-to-back slots that meet the threshold are joined into one window (e.g.
17:00–18:00 Available + 18:00–19:00 50% busy → 17:00–19:00, at least 50% free).
Windows shorter than `--min-minutes` are dropped. `get.json` is a saved sample
response, used by the tests and demo mode.

## Command-line version

`schoolhire.py` does the same checks and prints a table, which is handy for
scripts:

```bash
python schoolhire.py                               # next 14 days, >=50% free, >=60 min
python schoolhire.py --group "East London"         # one group
python schoolhire.py --days 21 --after 18:00       # evenings, next 3 weeks
python schoolhire.py --weekdays sat,sun --min-minutes 90
python schoolhire.py --min-free 100                # whole hall free only
python schoolhire.py --sort price --html results.html
python schoolhire.py --only bow                    # one court
python schoolhire.py --fixture get.json --start 2026-09-28 --days 7   # offline test
```

| Option          | Default | Meaning                                          |
|-----------------|---------|--------------------------------------------------|
| `--group`       | all     | only one group's courts (name or id)             |
| `--start`       | today   | first date to check                              |
| `--days`        | 14      | number of days to check                          |
| `--min-free`    | 50      | minimum % of the hall that must be free          |
| `--min-minutes` | 60      | shortest window worth listing                    |
| `--after` / `--before` | – | only times in this range, e.g. `18:00` `22:00` |
| `--weekdays`    | all     | e.g. `sat,sun` or `mon,wed,fri`                  |
| `--only`        | –       | only courts whose name contains this text        |
| `--sort`        | date    | `date` or `price`                                |
| `--courts`      | `courts.json` | a different groups file                    |
| `--html` / `--json` | –   | also save the results to a file                  |
| `--delay`       | 1       | seconds between requests                         |

Example output:

```
Date        Time         Mins  Free  Court                         £     Size  Link
Tue 29 Sep  17:00-19:00  120   50%   Dagenham Park Leisure Centre  28.5  half  https://schoolhire.co.uk/...17294?date=2026-09-29
Sat 03 Oct  14:00-18:00  240   100%  Dagenham Park Leisure Centre  28.5  half  https://schoolhire.co.uk/...17294?date=2026-10-03
```

"Free" is the lowest % free across the whole window.

## Running it on GitHub

`.github/workflows/check-courts.yml` runs the command-line check when you press
**Run workflow** on the Actions tab (you can pass extra options there, e.g.
`--group east-london --after 18:00`; use the group's id from `courts.example.json`,
as names with spaces get split up). Results appear in the run summary and
as a downloadable `results.html`. Your own `courts.json` isn't in git, so on
GitHub it checks the courts in `courts.example.json`; edit that file in your
copy of the repo if you want it to check others. Add a `schedule:` trigger if
you want it to run daily.

## Be polite

Each refresh makes about 2–3 requests per court, with a 1 second pause between
them, and adding a court reads its page once. A few runs a day is plenty.
Check the site's terms before running it more often.

## Files

| File | What it is |
|------|------------|
| `app.py` | the web app (Flask) |
| `static/index.html` | the page |
| `schoolhire.py` | fetching, parsing and filtering, plus the command-line version |
| `courts.py` | your groups of courts, and adding a court from its link |
| `courts.example.json` | the example group you start with |
| `courts.json` | your own groups (made on first use, not in git) |
| `get.json` | saved schoolhire sample response, used by the tests and demo mode |

## Tests

```bash
python -m unittest discover -s tests
```
