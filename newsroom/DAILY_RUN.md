# Daily run

This is what the morning scheduled task does every day. A person can do the same by hand.

1. **Set up** (fresh machine): `pip install --break-system-packages pandas jinja2 playwright`
   if missing. Chromium for Playwright must be available (it is in Claude's cloud sessions).
2. **Refresh the data**: `python3 pipeline/fetch.py --week <last completed week>`
   (Sleeper's current week minus one, except on Tuesday when the week that just ended is still
   "current": use the current week then).
3. **Tuesday only, the weekly edition** for the week that just ended:
   - `python3 pipeline/facts.py --week N`; it must print `pbp complete True` and
     `timelines match official: True`. If play-by-play isn't complete (nflverse updates
     overnight), skip the weekly edition this run and say so; retry later in the day.
   - Write `content/<season>-w<NN>/stories.json` per `newsroom/STYLE.md`, reading prior weeks
     for continuity. `python3 pipeline/validate.py --week N` must report 0 errors.
4. **Every day, the brief**:
   - `python3 pipeline/daily.py`
   - Read `content/daily/<today>/facts.json` and yesterday's brief (don't repeat yourself).
   - Write `content/daily/<today>/stories.json` per the daily section of `newsroom/STYLE.md`.
   - `python3 pipeline/validate.py --daily <today>` must report 0 errors.
5. **Build**: `python3 pipeline/build.py`; open `/` and today's `/daily/<date>/` to check they render.
6. **Publish**: commit `content/` and `site/` (`Daily brief <date>`, plus `Week N edition` on
   Tuesdays) and push to `main`. Netlify deploys automatically.
7. **Report back** with today's headline and the link.
