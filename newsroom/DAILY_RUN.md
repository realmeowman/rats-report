# Runbook

Two scheduled tasks run the newsroom:

- **Every morning (5:41 AM Pacific): the daily brief.** On Tuesdays it also refreshes the weekly
  edition with Monday's full play-by-play and any stat corrections.
- **Monday night (9:37 PM Pacific): the weekly edition**, published as soon as the last Monday
  game is final. This is the big one.

## Set up (fresh machine)
`pip install --break-system-packages pandas jinja2 playwright` if missing. Chromium for
Playwright must be available (it is in Claude's cloud sessions).

## The daily brief (every morning)
1. `python3 pipeline/fetch.py --week <last completed week>` (Sleeper's current week minus one;
   on Tuesday morning Sleeper still shows the week that just ended as current, so use it as is).
2. `python3 pipeline/daily.py`
3. Read `content/daily/<today>/facts.json` and yesterday's brief (don't repeat yourself).
   Write `content/daily/<today>/stories.json` per the daily section of `newsroom/STYLE.md`.
4. `python3 pipeline/validate.py --daily <today>` must report 0 errors.
5. **Tuesday only, refresh the weekly edition**: `python3 pipeline/facts.py --week N`. If it now
   reports `pbp complete True`, re-run `python3 pipeline/validate.py --week N`, fix anything that
   changed (stat corrections), and add Monday's lead-change times and swing plays where they
   improve the story. If the Monday-night edition didn't publish (e.g. a late game), write it now.
6. Build, check, publish (below).

## The weekly edition (Monday night)
1. Make sure the week is over: every game in the week has kicked off at least 3.5 hours ago
   (`data/raw/games.csv`) and Sleeper's matchup totals stop changing across two pulls a few
   minutes apart. If not, schedule a one-time retry 45 minutes later and stop.
2. `python3 pipeline/fetch.py --week N`, then `python3 pipeline/facts.py --week N`.
   Monday's games usually have no play-by-play yet (`pbp_complete` false); that's expected.
   `timelines match official` must still be true.
3. Write `content/<season>-w<NN>/stories.json` per `newsroom/STYLE.md` (see "Monday-night
   editions"), reading prior weeks for continuity.
4. `python3 pipeline/validate.py --week N` must report 0 errors.
5. Build, check, publish (below).

## Build, check, publish
- `python3 pipeline/build.py`; open `/`, today's `/daily/<date>/` and the edition page to check.
- Commit `content/` and `site/` and push to `main`. Netlify deploys automatically.
- Report back with the headline and the link.
