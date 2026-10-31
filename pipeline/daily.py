"""The daily desk: pull what changed in the league since the last brief and what's coming up,
and write content/daily/<date>/facts.json for the day's writer.

Covers: new roster moves (with timestamps), Sleeper-wide trending adds and drops and who in
R.A.T.S. owns them, this week's matchups with the lineups owners have actually set (projections,
win probability, live points once games start), busted lineups (starters
who never played: their team played without them, or a bye once the weekend is over), injuries on rosters, and the latest playoff odds.

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


def best_lineup(pool, slots):
    flex_ok = {"FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"}, "SUPER_FLEX": set(SKILL)}
    healthy = sorted([r for r in pool if not r.get("on_bye") and r.get("injury") not in BAD_STATUS and r.get("proj", 0) > 0],
                     key=lambda r: -r["proj"])
    used, out = set(), []
    for slot in sorted(slots, key=lambda x: x in flex_ok):
        ok = flex_ok.get(slot, {slot})
        pick = next((r for r in healthy if r["id"] not in used and r["pos"] in ok), None)
        if pick:
            used.add(pick["id"])
            out.append(pick)
    return out


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

    # Lineups are routinely set late in the week. Before Sunday, an unset bye or injury is a
    # reminder, not news; on Sunday morning (and after kickoff) it becomes a real alert.
    edition_type = EDITION_BY_DAY[day.weekday()]
    any_points = any((m.get("points") or 0) > 0 for m in get(f"/league/{lid}/matchups/{week}"))
    # Before games start we assume every owner will set a sensible lineup: previews use each team's
    # best available lineup and nothing about unset lineups is reported. Only after a starter's
    # chance to play is gone (his NFL team has played without him, or he's on bye once the
    # weekend's games are done) does it become a story: a busted lineup.
    played_teams = {pinfo(pid)["nfl_team"] for pid, s_ in live.items() if s_.get("gp")}
    lineups_matter = any_points
    bye_final = edition_type == "monday"

    # kickoff time per NFL team this week (for knowing which lineup decisions are still open)
    kickoff = {}
    gp_ = os.path.join(RAW, "games.csv")
    if os.path.exists(gp_):
        import csv
        for g in csv.DictReader(open(gp_)):
            if g["season"] == str(season) and g["week"] == str(week) and g["game_type"] == "REG":
                k = dt.datetime.fromisoformat(f"{g['gameday']}T{g['gametime']}").replace(tzinfo=ZoneInfo("America/New_York"))
                for tm in (g["away_team"], g["home_team"]):
                    kickoff[{"LA": "LAR"}.get(tm, tm)] = k
    def locked(info):
        k = kickoff.get(info.get("nfl_team"))
        return bool(k and k <= now)
    FLEX = {"FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"}, "SUPER_FLEX": set(SKILL)}
    decisions = []

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
                    if bye_final:
                        alerts.append({"roster_id": rid, "kind": "empty_slot", "slot": slot})
                    continue
                info = pinfo(pid)
                row = dict(info, slot=slot, proj=projp(pid), live=r2((m.get("players_points") or {}).get(pid, 0)),
                           on_bye=info["nfl_team"] not in playing)
                rows.append(row)
                played = bool((live.get(str(pid)) or {}).get("gp"))
                if row["on_bye"] and bye_final:
                    alerts.append({"roster_id": rid, "kind": "started_on_bye", "player": info["name"], "slot": slot})
                elif not played and info["pos"] != "DEF" and info["nfl_team"] in played_teams:
                    alerts.append({"roster_id": rid, "kind": "started_did_not_play", "player": info["name"], "slot": slot,
                                   "status_now": info["injury"]})
            for pid in m.get("players") or []:
                if pid in starters:
                    continue
                info = pinfo(pid)
                bench_rows.append(dict(info, proj=projp(pid), live=r2((m.get("players_points") or {}).get(pid, 0)),
                                       on_bye=info["nfl_team"] not in playing))
            bench_rows.sort(key=lambda r: -r["proj"])
            # Developing stories: lineup spots this front office still has to settle. Not news
            # (we assume it gets settled), but drama while it's open.
            used_opts = set()
            for i, r in enumerate(rows):
                slot = r["slot"]
                if not r.get("empty") and locked(r):
                    continue
                ok = FLEX.get(slot, {slot})
                opts = [b for b in bench_rows if b["pos"] in ok and not b["on_bye"] and b["injury"] not in BAD_STATUS
                        and not locked(b) and b["proj"] > 0]
                via_flex = False
                if not opts and slot not in FLEX:
                    # no direct backup: a flex starter could slide over and a bench player fill the flex
                    flex_rows = [x for x in rows if x["slot"] in FLEX and not x.get("empty") and x["pos"] in ok and not locked(x)]
                    if flex_rows:
                        fok = FLEX[flex_rows[0]["slot"]]
                        opts = [b for b in bench_rows if b["pos"] in fok and not b["on_bye"] and b["injury"] not in BAD_STATUS
                                and not locked(b) and b["proj"] > 0]
                        via_flex = bool(opts)
                if r.get("empty"):
                    why = "empty"
                elif r["on_bye"]:
                    why = "bye"
                elif r["injury"] in BAD_STATUS + ("Doubtful", "Questionable"):
                    why = "injury"
                elif opts and opts[0]["proj"] - r["proj"] >= 5:
                    why = "upgrade"
                else:
                    continue
                choices = [o for o in opts if o["id"] not in used_opts][:3]
                if why == "upgrade":
                    choices = [o for o in choices if o["proj"] > r["proj"]]
                for o in choices[:1]:
                    used_opts.add(o["id"])
                decisions.append({"id": f"w{week}-r{rid}-s{i}", "roster_id": rid, "slot": slot, "reason": why,
                                  "current": None if r.get("empty") else {k: r[k] for k in ("name", "pos", "proj", "injury")},
                                  "options": [{k: o[k] for k in ("name", "pos", "proj", "injury")} for o in choices], "via_flex_shuffle": via_flex,
                                  "needs_waiver_add": not choices and why != "upgrade",
                                  "deadline": min([kickoff[o["nfl_team"]] for o in choices if o["nfl_team"] in kickoff] or [None]) and
                                              fmt(int(min(kickoff[o["nfl_team"]] for o in choices if o["nfl_team"] in kickoff).timestamp() * 1000))})
            proj_total = r2(sum(r.get("proj", 0) for r in rows if not r.get("empty")))
            pool = [r for r in rows if not r.get("empty")] + bench_rows
            best_total = r2(sum(x["proj"] for x in best_lineup(pool, slots)))
            sides.append({"roster_id": rid, "live_points": r2(m.get("points")), "projected_set_lineup": proj_total,
                          "projected_best_lineup": best_total,
                          "starters": rows, "bench": bench_rows[:6]})
        A, B = sides
        basis = "projected_best_lineup"
        z = (A[basis] - B[basis]) / (math.sqrt(2) * sd) if sd else 0
        wp = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        matchups.append({"key": f"w{week}-m{mid}", "matchup_id": mid, "teams": [A["roster_id"], B["roster_id"]],
                         "projected": [A[basis], B[basis]], "projection_basis": "best available lineups",
                         "projected_as_set": [A["projected_set_lineup"], B["projected_set_lineup"]],
                         "projected_best": [A["projected_best_lineup"], B["projected_best_lineup"]],
                         "live": [A["live_points"], B["live_points"]], "win_prob": [round(wp, 3), round(1 - wp, 3)],
                         "sides": sides, "games_started": any(s["live_points"] for s in sides)})

    # ----- moves since the last brief -----
    state_p = os.path.join(ROOT, "content", "daily", "state.json")
    last = json.load(open(state_p)) if os.path.exists(state_p) else {}
    if last.get("date") == day.isoformat() and last.get("since_ms"):
        since_ms = last["since_ms"]  # re-running today's brief: same window as the first run
    else:
        since_ms = last.get("last_tx_ms") or int((now - dt.timedelta(hours=36)).timestamp() * 1000)
    last["date"], last["since_ms"] = day.isoformat(), since_ms
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

    facts = {"date": day.isoformat(), "weekday": day.strftime("%A"), "edition_type": edition_type,
             "lineups_matter": lineups_matter,
             "generated_at": now.isoformat(timespec="minutes"), "season": season, "week": week,
             "teams": teams, "standings_context": ctx, "matchups": matchups, "busted_lineups": alerts,
             "new_moves": tx, "trending_adds": trending("add"), "trending_drops": trending("drop"),
             "injuries": inj[:20], "nfl_teams_on_bye": sorted({p["team"] for p in players.values()
                                                              if p.get("team") and p.get("position") in SKILL} - playing),
             "latest_weekly_edition": weekly[-1] if weekly else None}
    out = os.path.join(ROOT, "content", "daily", day.isoformat())
    os.makedirs(out, exist_ok=True)
    json.dump(facts, open(os.path.join(out, "facts.json"), "w"), indent=1, default=str)
    if tx:
        last["last_tx_ms"] = tx[-1]["ts"]
    hist = last.setdefault("decisions_by_date", {})
    prev_dates = sorted(d for d in hist if d < day.isoformat())
    prev = hist[prev_dates[-1]] if prev_dates else {}
    now_ids = {d_["id"] for d_ in decisions}
    starters_now = {}
    for m_ in matchups:
        for sd_ in m_["sides"]:
            for i_, r_ in enumerate(sd_["starters"]):
                starters_now[f"w{week}-r{sd_['roster_id']}-s{i_}"] = r_
    resolved = []
    for did, old in prev.items():
        if did in now_ids or not did.startswith(f"w{week}-"):
            continue
        cur = starters_now.get(did) or {}
        resolved.append({"id": did, "roster_id": old["roster_id"], "slot": old["slot"], "reason": old["reason"],
                         "was": old.get("current"), "now": None if cur.get("empty") else {k: cur.get(k) for k in ("name", "pos", "proj")}})
    hist[day.isoformat()] = {d_["id"]: {k: d_[k] for k in ("roster_id", "slot", "reason", "current")} for d_ in decisions}
    for k_ in sorted(hist)[:-10]:
        hist.pop(k_)
    facts["open_decisions"] = decisions
    facts["resolved_decisions"] = resolved
    json.dump(facts, open(os.path.join(out, "facts.json"), "w"), indent=1, default=str)
    last["last_run"] = now.isoformat(timespec="minutes")
    json.dump(last, open(state_p, "w"), indent=1)
    print(f"wrote content/daily/{day}/facts.json | {facts['edition_type']} | week {week} | moves {len(tx)} | busted {len(alerts)} | open decisions {len(decisions)} | resolved {len(resolved)} | games started {any(m['games_started'] for m in matchups)}")


if __name__ == "__main__":
    sys.exit(main())
