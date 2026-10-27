# Weekly run

This is what the Tuesday scheduled task does. A person can do the same by hand.

1. **Set up** (fresh machine): `pip install --break-system-packages pandas jinja2 playwright`
   if missing. Chromium for Playwright must be available (it is in Claude's cloud sessions).
2. **Pull the data**: `python3 pipeline/fetch.py`
   Sleeper's "current week" flips on Wednesday, so on Tuesday it is still the week that just
   finished. If you run on another day, pass `--week N` for the week to cover.
3. **Check the week is final**: the Monday night game must be over and play-by-play present.
   `python3 pipeline/facts.py --week N` prints `pbp complete True` and `timelines match official: True`.
   If play-by-play is not complete yet (nflverse updates overnight), wait and retry later
   rather than publishing an edition with approximate timelines.
4. **Skip weeks with no games** (bye, season over): if `facts.json` has no matchups, stop.
5. **Write** `content/<season>-w<NN>/stories.json` following `newsroom/STYLE.md`. Read the whole
   facts file first, and read the previous weeks' stories so storylines continue and you do not
   repeat the same jokes.
6. **Fact-check**: `python3 pipeline/validate.py --week N` must report 0 errors. Fix every error
   by changing the copy. Resolve every warning (justify it in `external_facts` or remove it).
7. **Build**: `python3 pipeline/build.py`, then open the edition page and one story page to make
   sure they render.
8. **Publish**: commit `content/` and `site/` with the message `Week N edition` and push to `main`.
   The host deploys `site/` automatically.
9. **Report back** with the edition's headline and the link.
