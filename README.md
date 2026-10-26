# schoolhire-scraper

A small local web app that checks basketball courts on schoolhire.co.uk and
shows every time window where **at least 50% of the hall is free**, so you
don't have to click through each court's calendar yourself.

Keep your courts in **groups**: one for the courts near home, one for the
courts your Tuesday crew plays at, and so on. Add a court by pasting its
schoolhire.co.uk link.

## Quick start

You need Python 3. The start scripts below set everything else up the first
time (in a `.venv` folder inside the project) and then open the app in your
browser at http://127.0.0.1:5050. Leave the window that opens running while
you use the app; close it, or press **Ctrl+C** in it, to stop.

### Windows

1. Install Python 3 from https://www.python.org/downloads/ if you don't have
   it. In the installer, tick **Add python.exe to PATH**.
2. Double-click **`start.bat`** in the project folder.

Or in Command Prompt / PowerShell, from the project folder:

```bat
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Next time, just `.venv\Scripts\python app.py` (or double-click `start.bat`).

### Mac

1. Check you have Python 3: open **Terminal** and run `python3 --version`. If
   it says "command not found", install it from
   https://www.python.org/downloads/ or with Homebrew: `brew install python`.
   (There's no separate `pip` to install; it comes with Python.)
2. Double-click **`start.command`** in the project folder. The first time,
   macOS may say it's from an unidentified developer: right-click it, choose
   **Open**, then **Open** again. If it says you don't have permission, run
   `chmod +x start.command` in Terminal from the project folder once.

Or in Terminal, from the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Next time, just `source .venv/bin/activate` then `python app.py` (or
double-click `start.command`).

Use the private `.venv` environment rather than a plain `pip install`: Homebrew's
Python refuses system-wide installs ("externally-managed-environment").

The app uses port 5050, because macOS uses port 5000 for AirPlay Receiver. If
5050 is taken too, start it with another, e.g. `python app.py --port 8080`.

It starts with an example group, **East London**, with seven courts in it.
Change it, delete it or make your own under **Manage groups & courts**.

On the page you can:

- pick a group, or **All**, to check only those courts
- pick how far ahead to look (1–4 weeks), the minimum % free, and the shortest
  slot worth booking
- limit to certain times (e.g. from 18:00) and days (e.g. Sat, Sun)
- switch individual courts on or off, and sort by date, price or drive time
- press **Book ↗** to open that court's calendar on schoolhire.co.uk for that day
- sort by **Best match** to rank slots on price, drive time, how much of the
  hall is free and length all at once. Sliders set what matters most to you
  (0 = ignore it), and each slot shows its score and why, e.g. "Match 88 ·
  cheap · close". Price and drive are compared with the other slots on screen;
  a court with no price or drive time counts as middling. Slots of 3 hours or
  more count as fully long
- switch **Show** to **Week grid** to see each day as a timeline: a bar per
  court, green where the whole hall is free, amber where at least your chosen
  share is free, striped where it's booked, and blank where it isn't open. Tap a
  coloured block to book it

While courts are being checked, each court's button shows a small spinner and
a bar shows how many are done. Slots appear as soon as each court is checked, so
you don't wait for the slowest one. A court that fails turns red with the reason
underneath, and the others carry on.

Your filters are remembered between visits. Court data is cached for 10
minutes, so changing filters is instant. Press **Refresh from site** to fetch
new data: the old slots stay on screen, faded, until each court is re-checked.
A court that failed is tried again after a minute, or when you press Refresh.

Other ways to start it:

```bash
python app.py --fixture get.json   # demo with the saved sample, no internet needed
python app.py --host 0.0.0.0       # also reachable from your phone on the same Wi-Fi
python app.py --port 8080 --no-browser   # any free port
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
- **Driving from** is where the group usually sets off from (e.g. `Home`,
  `Pell St` or a postcode). Put your guess of the drive from there to each court
  in its **Drive (min)** box, or leave it blank if you don't know. Each slot
  then shows e.g. "🚗 ~25 min from Pell St", and **Sort by → Drive time** puts
  the closest courts first (courts with no guess go last). When you look at
  **All**, a court that's in several groups shows the guess from each.

Once a group has a **Driving from** place, each slot also gets a
**Directions ↗** link that opens Google Maps with driving directions from there
to the court (by its postcode), and each court in **Manage groups & courts** has
a **map ↗** link. Google Maps shows its own live drive time, which is handy for
checking a guess. No key is needed.

### Drive times from TomTom

Instead of guessing, you can let TomTom work the drive times out, including
its usual traffic for when you'd set off:

1. Get a free key at https://developer.tomtom.com (sign up, then
   **Dashboard → Keys**; no card needed). Paste it into **Estimate drive times
   with TomTom** and press **Save key**. It's saved in `settings.json` next to
   `app.py`, which isn't in git, and the page only ever shows its last four
   characters. You can also set the `TOMTOM_API_KEY` environment variable.
2. Set **Driving from** for the group. A postcode works best (`E1 6AN`); a
   place name (`Pell St, London`) works too.
3. Pick when you'd leave, e.g. **Tuesday 18:00** (the next one coming up), or
   **Now**, and press **Estimate drive times**.

Each court then shows e.g. "37 min (12 mi) from E1 6AN · TomTom, Tue 18:00".
Courts where you typed your own number keep it unless you tick **also replace my
own guesses**; typing a number over an estimate makes it your guess again.
Courts are found by their postcode (via the free postcodes.io), which is read
from the court's page when you add it.

One press uses about two TomTom requests per court, far inside the free
allowance (around 2,500 a day).

- **Find basketball courts near a postcode** searches schoolhire.co.uk for you:
  type a postcode (`NW9 4GD`) or just its first half (`NW9`), pick a distance
  and press **Search**. Every court in range is listed nearest first, with its
  address and price where the site gives one. **+ Add** puts it in the group
  you're looking at (it reads the court's page, like pasting its link), and
  courts already in the group are marked ✓.

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
python schoolhire.py --sort drive                  # closest first, using your guesses
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
