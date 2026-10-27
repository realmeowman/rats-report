"""Download everything the newsroom needs into data/raw/.

Sleeper: every season in the league's history (follows previous_league_id), with users,
rosters, matchups, transactions, drafts and playoff brackets. Plus the Sleeper player
database. nflverse: this season's play-by-play and rosters (for Sleeper<->NFL player ids).

Usage: python3 pipeline/fetch.py [--week N]   (defaults to the week Sleeper says is current)
"""
import argparse, json, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
SLEEPER = "https://api.sleeper.app/v1"
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"


def get_json(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def download(url, path, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=300) as r, open(path, "wb") as f:
                f.write(r.read())
            return
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def dump(obj, *parts):
    p = os.path.join(RAW, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(obj, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    args = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    state = get_json(f"{SLEEPER}/state/nfl")
    dump(state, "state.json")
    week = args.week or int(state["week"])

    lid, chain = cfg["league_id"], []
    current_season = None
    while lid and lid != "0":
        lg = get_json(f"{SLEEPER}/league/{lid}")
        season = lg["season"]
        current_season = current_season or season
        chain.append({"season": season, "league_id": lid})
        dump(lg, season, "league.json")
        dump(get_json(f"{SLEEPER}/league/{lid}/users"), season, "users.json")
        dump(get_json(f"{SLEEPER}/league/{lid}/rosters"), season, "rosters.json")
        last = week if season == current_season else 18
        for w in range(1, last + 1):
            dump(get_json(f"{SLEEPER}/league/{lid}/matchups/{w}"), season, f"matchups_{w}.json")
            dump(get_json(f"{SLEEPER}/league/{lid}/transactions/{w}"), season, f"transactions_{w}.json")
        for b in ("winners_bracket", "losers_bracket"):
            try:
                dump(get_json(f"{SLEEPER}/league/{lid}/{b}"), season, f"{b}.json")
            except Exception:
                pass
        drafts = get_json(f"{SLEEPER}/league/{lid}/drafts")
        dump(drafts, season, "drafts.json")
        picks = []
        for d in drafts:
            picks += get_json(f"{SLEEPER}/draft/{d['draft_id']}/picks")
        dump(picks, season, "draft_picks.json")
        print("sleeper", season, "weeks 1 -", last, flush=True)
        lid = lg.get("previous_league_id")
    dump({"current_season": current_season, "week": week, "chain": chain}, "chain.json")

    dump(get_json(f"{SLEEPER}/players/nfl"), "players.json")
    print("sleeper players", flush=True)

    s = current_season
    download(f"{NFLVERSE}/pbp/play_by_play_{s}.csv.gz", os.path.join(RAW, f"pbp_{s}.csv.gz"))
    download(f"{NFLVERSE}/rosters/roster_{s}.csv", os.path.join(RAW, f"roster_{s}.csv"))
    print("nflverse", s, flush=True)


if __name__ == "__main__":
    sys.exit(main())
