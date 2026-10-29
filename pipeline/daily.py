"""The daily desk: pull what changed in the league since the last brief and what's coming up,
and write content/daily/<date>/facts.json for the day's writer.

Covers: new roster moves (with timestamps), Sleeper-wide trending adds and drops and who in
R.A.T.S. owns them, this week's matchups with the lineups owners have actually set (projections,
win probability, live points once games start), lineup alerts (starters on bye, out, doubtful,
empty slots, better options on the bench), injuries on rosters, and the latest playoff odds.

Usage: python3 pipeline/daily.py [--date YYYY-MM-DD]
Run pipeline/fetch.py first (it refreshes the completed weeks and player database).
"""
import argparse, datetime as dt, json, math, os, statistics, sys, urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
CFG = json.load(open(os.path.join(ROOT, "config.json")))
TZ = ZoneInfo(CFG["timezone"])
API = "https://api.sleeper.app/v1"
SKILL = ("QB", "RB", "WR", "TE")
EDITION_BY_DAY = {0: "monday", 1: "tuesday", 2: "waivers", 3: "preview", 4: "lineup_watch", 5: "weekend", 6: "gameday"}
BAD_STATUS = ("Out", "IR", "Suspended", "PUP", "NA")


def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.loads(r.read())


def r2(x):
    return round(float(x or 0), 2)


def pts(statline, sc):
    return sum((statline.get(k) or 0) * v for k, v in sc.items()) if statline else 0.0


def fmt(ms):
    return dt.datetime.fromtimestamp(ms / 1000, TZ).strftime("%a %-I:%M %p")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    now = dt.datetime.now(TZ)
    day = dt.date.fromisoformat(a.date) if a.date else now.date()
    state = get("/state/nfl")
    season, week = state["season"], int(state["week"])
    lid = CFG["league_id"]
    lg = get(f"/league/{lid}")
    sc = lg["scoring_settings"]
    users = {u["user_id"]: u for u in get(f"/league/{lid}/users")}
    rosters = get(f"/league/{lid}/rosters")
    players = json.load(open(os.path.join(RAW, "players.json")))
    slots = [x for x in lg["roster_positions"] if x not in ("BN", "IR", "TAXI")]

    teams = {}
    for r in rosters:
        u = users.get(r["owner_id"], {})
        name = (u.get("metadata") or {}).get("team_name") or u.get("display_name")
        st = r["settings"]
        teams[str(r["roster_id"])] = {"name": name, "record": f"{st['wins']}-{st['losses']}",
                                      "pf": r2(st["fpts"] + st.get("fpts_decimal", 0) / 100)}
    owner = {p: r["roster_id"] for r in rosters for p in (r.get("players") or [])}

    def pinfo(pid):
        p = players.get(str(pid)) or {}
        nm = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
        if p.get("position") == "DEF":
            nm += " D/ST"
        return {"id": str(pid), "name": nm or str(pid), "pos": p.get("position"),
                "nfl_team": p.get("team") if p.get("position") != "DEF" else str(pid),
                "injury": p.get("injury_status"), "injury_body": p.get("injury_body_part"),
                "news_updated": p.get("news_updated")}

    proj = get(f"/projections/nfl/regular/{season}/{week}")
    live = get(f"/stats/nfl/regular/{season}/{week}")
    playing = {pinfo(pid)["nfl_team"] for pid, s in proj.items() if pts(s, sc) > 0.5}
    projp = lambda pid: r2(pts(proj.get(str(pid)) or {}, sc))

    # ----- this week's matchups with the lineups owners have set -----
    ms = get(f"/league/{lid}/matchups/{week}")
    by = {}
    for m in ms:
        by.setdefault(m["matchup_id"], []).append(m)
    weekly_scores = []
    for w in range(1, week):
        p_ = os.path.join(RAW, season, f"matchups_{w}.json")
        if os.path.exists(p_):
            weekly_scores += [x["points"] or 0 for x in json.load(open(p_))]
    sd = statistics.pstdev(weekly_scores) if len(weekly_scores) > 2 else 25
    matchups, alerts = [], []
    for mid, pair in sorted(by.items()):
        if len(pair) != 2:
            continue
        sides = []
        for m in pair:
            rid = m["roster_id"]
            starters = m.get("starters") or []
            rows, bench_rows = [], []
            for i, pid in enumerate(starters):
                slot = slots[i] if i < len(slots) else "?"
                if not pid or pid == "0":
                    rows.append({"slot": slot, "empty": True})
                    alerts.append({"roster_id": rid, "kind": "empty_slot", "slot": slot})
                    continue
                info = pinfo(pid)
                row = dict(info, slot=slot, proj=projp(pid), live=r2((m.get("players_points") or {}).get(pid, 0)),
                           on_bye=info["nfl_team"] not in playing)
                rows.append(row)
                if row["on_bye"]:
                    alerts.append({"roster_id": rid, "kind": "starter_on_bye", "player": info["name"], "slot": slot})
                elif info["injury"] in BAD_STATUS:
                    alerts.append({"roster_id": rid, "kind": "starter_out", "player": info["name"], "status": info["injury"], "slot": slot})
                elif info["injury"] in ("Doubtful", "Questionable"):
                    alerts.append({"roster_id": rid, "kind": "starter_" + info["injury"].lower(), "player": info["name"], "status": info["injury"], "slot": slot})
            for pid in m.get("players") or []:
                if pid in starters:
                    continue
                info = pinfo(pid)
                bench_rows.append(dict(info, proj=projp(pid), live=r2((m.get("players_points") or {}).get(pid, 0)),
                                       on_bye=info["nfl_team"] not in playing))
            bench_rows.sort(key=lambda r: -r["proj"])
            # better option on the bench: same position, healthy, projected 5+ more than a starter
            for b in bench_rows:
                if b["on_bye"] or b["injury"] in BAD_STATUS:
                    continue
                worse = [r for r in rows if not r.get("empty") and r["pos"] == b["pos"] and b["proj"] - r["proj"] >= 5]
                if worse:
                    w_ = min(worse, key=lambda r: r["proj"])
                    alerts.append({"roster_id": rid, "kind": "better_on_bench", "bench": b["name"], "bench_proj": b["proj"],
                                   "starter": w_["name"], "starter_proj": w_["proj"]})
            proj_total = r2(sum(r.get("proj", 0) for r in rows if not r.get("empty")))
            sides.append({"roster_id": rid, "live_points": r2(m.get("points")), "projected_set_lineup": proj_total,
                          "starters": rows, "bench": bench_rows[:6]})
        A, B = sides
        z = (A["projected_set_lineup"] - B["projected_set_lineup"]) / (math.sqrt(2) * sd) if sd else 0
        wp = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        matchups.append({"key": f"w{week}-m{mid}", "matchup_id": mid, "teams": [A["roster_id"], B["roster_id"]],
                         "projected": [A["projected_set_lineup"], B["projected_set_lineup"]],
                         "live": [A["live_points"], B["live_points"]], "win_prob": [round(wp, 3), round(1 - wp, 3)],
                         "sides": sides, "games_started": any(s["live_points"] for s in sides)})

    # ----- moves since the last brief -----
    state_p = os.path.join(ROOT, "content", "daily", "state.json")
    last = json.load(open(state_p)) if os.path.exists(state_p) else {}
    since_ms = last.get("last_tx_ms") or int((now - dt.timedelta(hours=36)).timestamp() * 1000)
    tx = []
    for w in (week - 1, week):
        for t in get(f"/league/{lid}/transactions/{w}"):
            if t.get("status") != "complete" or t["status_updated"] <= since_ms:
                continue
            tx.append({"time": fmt(t["status_updated"]), "ts": t["status_updated"], "type": t["type"], "rosters": t["roster_ids"],
                       "adds": [dict(pinfo(p), to=r, proj_this_week=projp(p)) for p, r in (t.get("adds") or {}).items()],
                       "drops": [dict(pinfo(p), **{"from": r}, proj_this_week=projp(p)) for p, r in (t.get("drops") or {}).items()],
                       "waiver_bid": (t.get("settings") or {}).get("waiver_bid")})
    tx.sort(key=lambda x: x["ts"])
    for i, t in enumerate(tx):
        t["id"] = f"{day.isoformat()}-m{i + 1}"

    # ----- trending across Sleeper -----
    def trending(kind):
        out = []
        for x in get(f"/players/nfl/trending/{kind}?lookback_hours=24&limit=25"):
            info = pinfo(x["player_id"])
            if info["pos"] not in SKILL + ("K", "DEF"):
                continue
            out.append(dict(info, count=x["count"], rats_owner=owner.get(x["player_id"]), proj_this_week=projp(x["player_id"]),
                            on_bye=info["nfl_team"] not in playing))
        return out[:15]

    # ----- injuries on R.A.T.S. rosters that matter this week -----
    inj = []
    for pid, rid in owner.items():
        info = pinfo(pid)
        if info["injury"] and info["pos"] in SKILL:
            inj.append(dict(info, roster_id=rid, proj_this_week=projp(pid)))
    inj.sort(key=lambda x: -x["proj_this_week"])

    # ----- latest weekly analysis for context -----
    weekly = sorted(d for d in os.listdir(os.path.join(ROOT, "content")) if d[:4].isdigit())
    wf = json.load(open(os.path.join(ROOT, "content", weekly[-1], "facts.json"))) if weekly else {}
    ctx = {}
    if wf:
        for rid, t in (wf.get("analysis") or {}).get("teams", {}).items():
            ctx[rid] = {k: t[k] for k in ("playoff_odds", "all_play", "luck", "projected_final_wins")}

    facts = {"date": day.isoformat(), "weekday": day.strftime("%A"), "edition_type": EDITION_BY_DAY[day.weekday()],
             "generated_at": now.isoformat(timespec="minutes"), "season": season, "week": week,
             "teams": teams, "standings_context": ctx, "matchups": matchups, "lineup_alerts": alerts,
             "new_moves": tx, "trending_adds": trending("add"), "trending_drops": trending("drop"),
             "injuries": inj[:20], "nfl_teams_on_bye": sorted({p["team"] for p in players.values()
                                                              if p.get("team") and p.get("position") in SKILL} - playing),
             "latest_weekly_edition": weekly[-1] if weekly else None}
    out = os.path.join(ROOT, "content", "daily", day.isoformat())
    os.makedirs(out, exist_ok=True)
    json.dump(facts, open(os.path.join(out, "facts.json"), "w"), indent=1, default=str)
    if tx:
        last["last_tx_ms"] = tx[-1]["ts"]
    last["last_run"] = now.isoformat(timespec="minutes")
    json.dump(last, open(state_p, "w"), indent=1)
    print(f"wrote content/daily/{day}/facts.json | {facts['edition_type']} | week {week} | moves {len(tx)} | alerts {len(alerts)} | games started {any(m['games_started'] for m in matchups)}")


if __name__ == "__main__":
    sys.exit(main())
