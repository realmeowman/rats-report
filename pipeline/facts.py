"""Turn data/raw into one facts file for a week: content/<season>-w<week>/facts.json.

Everything the reporters are allowed to say comes from this file. It covers the week
(scores, lineups, how each matchup's lead moved through the weekend, transactions with
timestamps) and the league's history (records, habits, playoff results).

Usage: python3 pipeline/facts.py [--week N]
"""
import argparse, collections, datetime as dt, json, os, re, sys
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
CFG = json.load(open(os.path.join(ROOT, "config.json")))
TZ = ZoneInfo(CFG["timezone"])
TEAM_FIX = {"LAR": "LA"}  # Sleeper -> nflverse team codes


def load(*p):
    return json.load(open(os.path.join(RAW, *p)))


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "team"


def r2(x):
    return round(float(x or 0), 2)


def local(ts):
    return ts.astimezone(TZ)


def fmt_time(ts):
    t = local(ts)
    return t.strftime("%a %-I:%M %p")


def fmt_ms(ms):
    return fmt_time(dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc))


class League:
    def __init__(self):
        self.chain = load("chain.json")
        self.players = load("players.json")
        self.season = self.chain["current_season"]

    def season_data(self, season):
        users = {u["user_id"]: u for u in load(season, "users.json")}
        rosters = load(season, "rosters.json")
        teams = {}
        for r in rosters:
            u = users.get(r["owner_id"], {})
            name = (u.get("metadata") or {}).get("team_name") or u.get("display_name") or f"Team {r['roster_id']}"
            md = u.get("metadata") or {}
            avatar = md.get("avatar") or (f"https://sleepercdn.com/avatars/{u['avatar']}" if u.get("avatar") else None)
            teams[r["roster_id"]] = {"owner": u.get("display_name", "?"), "name": name, "avatar": avatar}
        return teams, rosters

    def pname(self, pid):
        p = self.players.get(str(pid)) or {}
        if p.get("position") == "DEF":
            return f"{p.get('first_name','')} {p.get('last_name','')} D/ST".strip() if p.get("last_name") else f"{pid} D/ST"
        return f"{p.get('first_name','')} {p.get('last_name','')}".strip() or str(pid)

    def pinfo(self, pid):
        p = self.players.get(str(pid)) or {}
        team = p.get("team") if p.get("position") != "DEF" else str(pid)
        return {"id": str(pid), "name": self.pname(pid), "pos": p.get("position"), "nfl_team": team}


def matchups(season, week):
    try:
        return load(season, f"matchups_{week}.json")
    except FileNotFoundError:
        return []


def pairs(ms):
    by = collections.defaultdict(list)
    for m in ms:
        if m.get("matchup_id") is not None:
            by[m["matchup_id"]].append(m)
    return [v for v in by.values() if len(v) == 2]


def build_pbp(season, week):
    path = os.path.join(RAW, f"pbp_{season}.csv.gz")
    df = pd.read_csv(path, low_memory=False)
    df = df[df.week == week].copy()
    df["t"] = pd.to_datetime(df.time_of_day, utc=True, errors="coerce")
    df = df.dropna(subset=["t"]).sort_values("t")
    ro = pd.read_csv(os.path.join(RAW, f"roster_{season}.csv"), low_memory=False)[["gsis_id", "sleeper_id"]].dropna()
    g2s = {str(g).strip(): str(int(float(s))) for g, s in zip(ro.gsis_id, ro.sleeper_id)}
    return df, g2s


def score_events(df, g2s, sc):
    """Per-play fantasy points for offensive players and kickers under the league's scoring."""
    ev = collections.defaultdict(list)

    def add(t, gid, v, desc):
        if pd.isna(gid) or not v:
            return
        pid = g2s.get(str(gid).strip())
        if pid:
            ev[pid].append((t, float(v), desc))

    for r in df.itertuples(index=False):
        t, desc = r.t, str(r.desc)[:160]
        if getattr(r, "pass_attempt", 0) == 1 or getattr(r, "play_type", "") == "pass":
            if pd.notna(r.passing_yards):
                add(t, r.passer_player_id, r.passing_yards * sc.get("pass_yd", 0), desc)
            if r.pass_touchdown == 1:
                add(t, r.passer_player_id, sc.get("pass_td", 0), desc)
            if r.interception == 1:
                add(t, r.passer_player_id, sc.get("pass_int", 0), desc)
            if r.complete_pass == 1:
                add(t, r.receiver_player_id, sc.get("rec", 0) + (r.receiving_yards or 0) * sc.get("rec_yd", 0), desc)
                if r.pass_touchdown == 1:
                    add(t, r.receiver_player_id, sc.get("rec_td", 0), desc)
        if pd.notna(r.rusher_player_id) and pd.notna(r.rushing_yards):
            add(t, r.rusher_player_id, r.rushing_yards * sc.get("rush_yd", 0), desc)
            if r.rush_touchdown == 1:
                add(t, r.rusher_player_id, sc.get("rush_td", 0), desc)
        if r.fumble_lost == 1:
            add(t, r.fumbled_1_player_id, sc.get("fum_lost", 0), desc)
        if r.two_point_conv_result == "success":
            add(t, r.passer_player_id, sc.get("pass_2pt", 0), desc)
            add(t, r.receiver_player_id, sc.get("rec_2pt", 0), desc)
            add(t, r.rusher_player_id, sc.get("rush_2pt", 0), desc)
        if r.field_goal_attempt == 1:
            if r.field_goal_result == "made":
                k = r.kick_distance or 0
                key = "fgm_0_19" if k < 20 else "fgm_20_29" if k < 30 else "fgm_30_39" if k < 40 else "fgm_40_49" if k < 50 else "fgm_50_59" if k < 60 else "fgm_60p"
                add(t, r.kicker_player_id, sc.get(key, 0), desc)
            else:
                add(t, r.kicker_player_id, sc.get("fgmiss", 0), desc)
        if r.extra_point_attempt == 1:
            add(t, r.kicker_player_id, sc.get("xpm", 0) if r.extra_point_result == "good" else sc.get("xpmiss", 0), desc)
    return ev


def week_facts(L, week):
    season = L.season
    lg = load(season, "league.json")
    sc = lg["scoring_settings"]
    teams, rosters = L.season_data(season)
    ms = matchups(season, week)
    df, g2s = build_pbp(season, week)
    pbp_teams = set(df.posteam.dropna()) | set(df.defteam.dropna())
    game_start = df.groupby("game_id").t.min().to_dict()
    team_game = {}
    for gid, grp in df.groupby("game_id"):
        for tm in set(grp.posteam.dropna()) | set(grp.defteam.dropna()):
            team_game[tm] = gid
    game_end = df.groupby("game_id").t.max().to_dict()
    # The NFL schedule fills in games whose play-by-play isn't published yet (a Monday-night
    # edition runs before nflverse posts Monday's plays). Those players' points land at the
    # estimated final whistle instead of play by play; the Tuesday refresh replaces them.
    pbp_missing = []
    sched_path = os.path.join(RAW, "games.csv")
    if os.path.exists(sched_path):
        g = pd.read_csv(sched_path, low_memory=False)
        g = g[(g.season == int(season)) & (g.week == week) & (g.game_type == "REG")]
        now_utc = pd.Timestamp.now(tz="UTC")
        for r in g.itertuples(index=False):
            kick = pd.Timestamp(f"{r.gameday} {r.gametime}", tz="America/New_York").tz_convert("UTC")
            for tm in (r.away_team, r.home_team):
                team_game.setdefault(tm, r.game_id)
            if r.game_id not in game_start:
                if kick > now_utc:
                    pbp_missing.append({"game_id": r.game_id, "status": "not started"})
                    continue
                game_start[r.game_id] = kick
                game_end[r.game_id] = min(kick + pd.Timedelta(minutes=195), now_utc)
                pbp_missing.append({"game_id": r.game_id, "status": "no play-by-play yet",
                                    "kickoff_utc": kick.isoformat()})
        pbp_complete = not pbp_missing
    else:
        pbp_complete = len(pbp_teams) >= 26
    week_facts.pbp_missing = pbp_missing
    ev = score_events(df, g2s, sc)
    playmeta = {}
    for r in df.itertuples(index=False):
        playmeta.setdefault(r.t, (r.game_id, r.qtr))
    try:
        wstats = load(season, f"stats_{week}.json")
    except FileNotFoundError:
        wstats = {}

    def league_pts(pid):
        s_ = wstats.get(str(pid)) or {}
        return r2(sum((s_.get(k) or 0) * v for k, v in sc.items()))

    slots = [x for x in lg["roster_positions"] if x not in ("BN", "IR", "TAXI")]
    flex_ok = {"FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"}, "SUPER_FLEX": {"QB", "RB", "WR", "TE"}}

    def optimal(rows):
        pool = sorted(rows, key=lambda r: -r["pts"])
        used, total, lineup = set(), 0.0, []
        for slot in sorted(slots, key=lambda x: x in flex_ok):
            ok = flex_ok.get(slot, {slot})
            pick = next((r for r in pool if r["id"] not in used and r.get("pos") in ok), None)
            if pick:
                used.add(pick["id"]); total += pick["pts"]; lineup.append(pick)
        return r2(total), used

    days = sorted({local(t).date() for t in game_start.values()})
    first_kick = min(game_start.values())
    hours = lambda t: round((t - first_kick).total_seconds() / 3600, 3)
    segments = []
    for d in days:
        gids = [gid for gid, t in game_start.items() if local(t).date() == d]
        st_, en_ = min(game_start[x] for x in gids), max(game_end[x] for x in gids)
        segments.append({"label": local(st_).strftime("%a").upper(), "start_h": hours(st_), "end_h": hours(en_)})

    def nfl_code(pid):
        info = L.pinfo(pid)
        return TEAM_FIX.get(info["nfl_team"], info["nfl_team"])

    def player_row(pid, pts):
        info = L.pinfo(pid)
        code = nfl_code(pid)
        gid = team_game.get(code)
        row = dict(info, pts=r2(pts))
        if gid:
            row["game_day"] = local(game_start[gid]).strftime("%a")
        elif code and code not in team_game:
            row["on_bye"] = True
        return row

    out_m = []
    for a, b in pairs(ms):
        if (a["points"] or 0) < (b["points"] or 0):
            a, b = b, a
        sides = []
        for m in (a, b):
            pp = m.get("players_points") or {}
            starters = [p for p in (m.get("starters") or []) if p and p != "0"]
            bench = [p for p in (m.get("players") or []) if p not in starters]
            srows = [player_row(p, pp.get(p, 0)) for p in starters]
            brows = sorted([player_row(p, pp.get(p, 0)) for p in bench], key=lambda r: -r["pts"])
            # rebuilt timeline
            tl = []
            for pid in starters:
                evs = ev.get(pid, [])
                tl += [(t, v, pid, d) for t, v, d in evs]
                resid = (pp.get(pid, 0) or 0) - sum(v for _, v, _ in evs)
                if abs(resid) > 0.01:
                    gid = team_game.get(nfl_code(pid))
                    end = game_end[gid] if gid else df.t.max()
                    missing_ids = {x["game_id"] for x in pbp_missing}
                    label = ("end-of-game scoring (no play-by-play yet; time estimated)" if gid in missing_ids
                             else "end-of-game scoring (defense, kicker or other)")
                    tl.append((end, resid, pid, label))
            sides.append({"roster_id": m["roster_id"], "points": r2(m["points"]), "starters": srows, "bench": brows, "tl": tl})
        A, B = sides
        merged = sorted([(t, 0, v, pid, d) for t, v, pid, d in A["tl"]] + [(t, 1, v, pid, d) for t, v, pid, d in B["tl"]], key=lambda x: x[0])
        sa = sb = 0.0
        lead, race, changes = None, [[0.0, 0.0, 0.0]], []
        best = {A["roster_id"]: (0, None), B["roster_id"]: (0, None)}
        for t, side, v, pid, d in merged:
            if side == 0:
                sa += v
            else:
                sb += v
            diff = sa - sb
            if diff > best[A["roster_id"]][0]:
                best[A["roster_id"]] = (round(diff, 2), t)
            if -diff > best[B["roster_id"]][0]:
                best[B["roster_id"]] = (round(-diff, 2), t)
            nl = A["roster_id"] if sa > sb else B["roster_id"] if sb > sa else lead
            if lead is not None and nl != lead:
                changes.append({"time": fmt_time(t), "new_leader": nl, "score": [r2(sa), r2(sb)],
                                "player": L.pname(pid), "play": d, "time_estimated": "time estimated" in d})
            lead = nl
            h = hours(t)
            if race and race[-1][0] == h:
                race[-1] = [h, r2(sa), r2(sb)]
            else:
                race.append([h, r2(sa), r2(sb)])
        # margin entering the final game day
        last_day = days[-1] if days else None
        final_day = None
        if last_day:
            cutoff = min(t for t in game_start.values() if local(t).date() == last_day)
            ea = sum(v for t, v, _, _ in A["tl"] if t < cutoff)
            eb = sum(v for t, v, _, _ in B["tl"] if t < cutoff)
            day = local(cutoff).strftime("%A")
            final_day = {"day": day, "score": [r2(ea), r2(eb)],
                         "remaining": {s["roster_id"]: [r["name"] for r in s["starters"] if r.get("game_day") == local(cutoff).strftime("%a")] for s in sides}}
        pre_best = {A["roster_id"]: (0, None), B["roster_id"]: (0, None)}
        if last_day:
            xa = xb = 0.0
            for t, side, v, pid, d in merged:
                if t >= cutoff:
                    break
                if side == 0:
                    xa += v
                else:
                    xb += v
                if xa - xb > pre_best[A["roster_id"]][0]:
                    pre_best[A["roster_id"]] = (round(xa - xb, 2), t)
                if xb - xa > pre_best[B["roster_id"]][0]:
                    pre_best[B["roster_id"]] = (round(xb - xa, 2), t)
        # biggest single plays: net swing within this matchup, grouped by play; running score includes everything
        grouped = collections.OrderedDict()
        run_a = run_b = 0.0
        for t, side, v, pid, d in merged:
            if not d.startswith("end-of-game"):
                g = grouped.setdefault((t, d), {"net": 0.0, "players": {A["roster_id"]: [], B["roster_id"]: []},
                                                "before": [r2(run_a), r2(run_b)]})
                g["net"] += v if side == 0 else -v
                g["players"][sides[side]["roster_id"]].append({"name": L.pname(pid), "pts": r2(v)})
            if side == 0:
                run_a += v
            else:
                run_b += v
            if not d.startswith("end-of-game"):
                grouped[(t, d)]["after"] = [r2(run_a), r2(run_b)]
        plays = []
        for (t, d), g in grouped.items():
            gid, q = playmeta.get(t, (None, None))
            desc = re.sub(r"\((Shotgun|No Huddle, Shotgun|No Huddle|Run formation)\)\s*", "", d)
            desc = re.sub(r"\b\d{1,2}-(?=[A-Z][a-z]?\.)", "", desc).strip()
            plays.append({"time": fmt_time(t), "game": gid.replace(f"{season}_{week:02d}_", "").replace("_", " @ ") if gid else None,
                          "quarter": int(q) if q == q and q else None, "desc": desc, "net_for_winner": r2(g["net"]),
                          "players": g["players"], "score_before": g["before"], "score_after": g["after"]})
        for p_ in plays:
            sb_, sa_ = p_["score_before"], p_["score_after"]
            p_["changed_lead"] = (sb_[0] - sb_[1]) * (sa_[0] - sa_[1]) < 0 or ((sb_[0] == sb_[1]) != (sa_[0] == sa_[1]) and sa_[0] != sa_[1])
        top = sorted(plays, key=lambda p_: -abs(p_["net_for_winner"]))[:6]
        keep = top + [p_ for p_ in plays if p_["changed_lead"] and p_ not in top]
        keep.sort(key=lambda p_: plays.index(p_))
        for i, p_ in enumerate(keep):
            p_["id"] = f"m{a['matchup_id']}-p{i + 1}"
        big_plays = keep
        for s in sides:
            s.pop("tl")
            opt, opt_ids = optimal(s["starters"] + s["bench"])
            st_ids = {r["id"] for r in s["starters"]}
            s["optimal_points"] = opt
            s["points_left_on_bench"] = r2(opt - s["points"])
            s["should_have_started"] = [{"name": r["name"], "pos": r["pos"], "pts": r["pts"]} for r in s["bench"] if r["id"] in opt_ids]
            s["should_have_sat"] = [{"name": r["name"], "pos": r["pos"], "pts": r["pts"]} for r in s["starters"] if r["id"] not in opt_ids]
            # pair each bench player who belonged in the lineup with the starter he should have replaced
            import itertools
            ins_, outs_ = s["should_have_started"], s["should_have_sat"]
            def fits(a_, b_):
                return a_["pos"] == b_["pos"] or {a_["pos"], b_["pos"]} <= {"RB", "WR", "TE"}
            best_pairs, best_key = [], None
            for perm in itertools.permutations(outs_, len(ins_)) if len(outs_) >= len(ins_) else []:
                if all(fits(a_, b_) for a_, b_ in zip(ins_, perm)):
                    key = (sum(a_["pos"] == b_["pos"] for a_, b_ in zip(ins_, perm)), -max([abs(a_["pts"] - b_["pts"]) for a_, b_ in zip(ins_, perm)] or [0]))
                    if best_key is None or key > best_key:
                        best_key, best_pairs = key, list(zip(ins_, perm))
            swaps = sorted([{"start": a_, "instead_of": b_, "gain": r2(a_["pts"] - b_["pts"])} for a_, b_ in best_pairs], key=lambda x: -x["gain"])
            s["bench_swaps"] = swaps
            pb = pre_best[s["roster_id"]]
            s["max_lead_before_final_day"] = {"margin": pb[0], "time": fmt_time(pb[1]) if pb[1] is not None else None}
            stack = collections.defaultdict(lambda: {"players": [], "pts": 0.0})
            for r in s["starters"]:
                if r.get("pos") != "DEF" and r.get("nfl_team"):
                    stack[r["nfl_team"]]["players"].append(r["name"]); stack[r["nfl_team"]]["pts"] += r["pts"]
            s["starter_stacks"] = {k: {"players": v["players"], "pts": r2(v["pts"])} for k, v in stack.items() if len(v["players"]) >= 2}
            s["zero_starters"] = [r["name"] for r in s["starters"] if r["pts"] == 0]
            # busted lineup: a starter who never took the field (bye, inactive, out) or an empty slot
            played_teams = {(L.players.get(str(p_)) or {}).get("team") for p_, st_ in wstats.items() if st_.get("gp")}
            busted = []
            for r in s["starters"]:
                if (wstats.get(r["id"]) or {}).get("gp") or r.get("pos") == "DEF":
                    continue
                reason = "bye week" if r.get("on_bye") or (r.get("nfl_team") and r["nfl_team"] not in played_teams) else "did not play"
                inj = (L.players.get(r["id"]) or {}).get("injury_status")
                swap = next((x for x in s.get("bench_swaps", []) if x["instead_of"]["name"] == r["name"]), None)
                busted.append({"name": r["name"], "pos": r.get("pos"), "reason": reason, "injury_status_now": inj,
                               "best_replacement": swap["start"] if swap else None, "points_lost": swap["gain"] if swap else 0})
            empty = sum(1 for r in s["starters"] if r.get("empty"))
            s["busted_starters"] = busted
            s["bye_starters"] = [r["name"] for r in s["starters"] if r.get("on_bye")]
            s["best_bench"] = s["bench"][0] if s["bench"] else None
            s["max_lead"] = {"margin": best[s["roster_id"]][0], "time": fmt_time(best[s["roster_id"]][1]) if best[s["roster_id"]][1] is not None else None}
        A["optimal_would_have_won"] = None
        B["optimal_would_have_won"] = B["optimal_points"] > A["points"]
        out_m.append({"matchup_id": a["matchup_id"], "winner": A["roster_id"], "loser": B["roster_id"],
                      "margin": r2(A["points"] - B["points"]), "sides": sides, "lead_changes": changes, "big_plays": big_plays,
                      "entering_final_day": final_day, "race": race,
                      "rebuilt_matches_official": abs(sa - A["points"]) < 0.5 and abs(sb - B["points"]) < 0.5})

    # transactions in the week's window: Tuesday before first kickoff -> Tuesday after
    k = local(first_kick)
    w_start = (k - dt.timedelta(days=(k.weekday() - 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)
    w_end = w_start + dt.timedelta(days=7)
    pts_this_week = {}
    started = set()
    for m in ms:
        for p, v in (m.get("players_points") or {}).items():
            pts_this_week[p] = v
        started |= set(m.get("starters") or [])
    tx = []
    for w in (week - 1, week):
        if w < 1:
            continue
        for t in load(season, f"transactions_{w}.json"):
            if t.get("status") != "complete":
                continue
            ts = dt.datetime.fromtimestamp(t["status_updated"] / 1000, dt.timezone.utc)
            if not (w_start <= local(ts) < w_end):
                continue
            tx.append({"time": fmt_time(ts), "ts": t["status_updated"], "type": t["type"], "rosters": t["roster_ids"],
                       "adds": [{"name": L.pname(p), "to": rid, "pts": r2(pts_this_week.get(p, 0)), "started": p in started} for p, rid in (t.get("adds") or {}).items()],
                       "drops": [{"name": L.pname(p), "from": rid, "pts_this_week": league_pts(p)} for p, rid in (t.get("drops") or {}).items()],
                       "faab": (t.get("settings") or {}).get("waiver_bid")})
    tx.sort(key=lambda x: x["ts"])
    rostered = {p for r in rosters for p in (r.get("players") or [])}
    fa = []
    for pid in wstats:
        info = L.players.get(str(pid)) or {}
        if pid in rostered or info.get("position") not in ("QB", "RB", "WR", "TE", "K", "DEF"):
            continue
        v = league_pts(pid)
        if v >= 15:
            fa.append({"name": L.pname(pid), "pos": info.get("position"), "nfl_team": info.get("team"), "pts": v})
    fa.sort(key=lambda x: -x["pts"])
    week_facts.free_agents = fa[:10]
    return out_m, tx, segments, pbp_complete, first_kick.isoformat()


def records_through(season, week):
    rec = collections.defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0, "results": []})
    for w in range(1, week + 1):
        for a, b in pairs(matchups(season, w)):
            for x, y in ((a, b), (b, a)):
                r = rec[x["roster_id"]]
                r["pf"] += x["points"] or 0
                r["pa"] += y["points"] or 0
                if (x["points"] or 0) > (y["points"] or 0):
                    r["w"] += 1; r["results"].append("W")
                elif (x["points"] or 0) < (y["points"] or 0):
                    r["l"] += 1; r["results"].append("L")
                else:
                    r["t"] += 1; r["results"].append("T")
    return rec


def streak(results):
    if not results:
        return ""
    last, n = results[-1], 0
    for r in reversed(results):
        if r != last:
            break
        n += 1
    return f"{last}{n}"


def history(L, week):
    cur = L.season
    seasons = [c["season"] for c in L.chain["chain"]]
    owner_by_season = {}
    hist = {"seasons": {}, "trades_all_time": 0, "close_games": collections.defaultdict(lambda: [0, 0]),
            "repeat_adds": [], "late_night_moves_this_season": collections.Counter()}
    adds_count = collections.Counter()
    for s in seasons:
        teams, rosters = L.season_data(s)
        owner_of = {r["roster_id"]: r["owner_id"] for r in rosters}
        owner_by_season[s] = owner_of
        last_w = week if s == cur else 18
        rec = records_through(s, 14 if s != cur else week)  # regular season for past years
        moves = collections.Counter(); bench20 = collections.Counter(); bench_pts = collections.Counter()
        for w in range(1, last_w + 1):
            for t in load(s, f"transactions_{w}.json") if os.path.exists(os.path.join(RAW, s, f"transactions_{w}.json")) else []:
                if t.get("status") != "complete":
                    continue
                if t["type"] == "trade":
                    hist["trades_all_time"] += 1
                    continue
                for rid in t["roster_ids"]:
                    moves[rid] += 1
                for p, rid in (t.get("adds") or {}).items():
                    adds_count[(owner_of.get(rid), L.pname(p))] += 1
                if s == cur:
                    h = dt.datetime.fromtimestamp(t["status_updated"] / 1000, TZ).hour
                    if t["type"] == "free_agent" and (h >= 23 or h < 5):
                        for rid in t["roster_ids"]:
                            hist["late_night_moves_this_season"][rid] += 1
            for m in matchups(s, w):
                pp = m.get("players_points") or {}
                st = set(m.get("starters") or [])
                for p in m.get("players") or []:
                    if p not in st and (pp.get(p) or 0) >= 20:
                        bench20[m["roster_id"]] += 1
            for a, b in pairs(matchups(s, w)):
                if w <= (14 if s != cur else week) and abs((a["points"] or 0) - (b["points"] or 0)) < 10:
                    win, lose = (a, b) if a["points"] > b["points"] else (b, a)
                    hist["close_games"][owner_of.get(win["roster_id"])][0] += 1
                    hist["close_games"][owner_of.get(lose["roster_id"])][1] += 1
        try:
            wb = load(s, "winners_bracket.json")
        except FileNotFoundError:
            wb = []
        po = []
        start = load(s, "league.json")["settings"].get("playoff_week_start", 15)
        for g in wb:
            if not g.get("w"):
                continue
            wk = start + g["r"] - 1
            score = {}
            for m in matchups(s, wk) if s != cur or wk <= week else []:
                score[m["roster_id"]] = r2(m["points"])
            loser_bench = None
            for m in matchups(s, wk) if s != cur or wk <= week else []:
                if m["roster_id"] == g["l"]:
                    pp = m.get("players_points") or {}
                    bn = [(pp.get(p) or 0, p) for p in m.get("players") or [] if p not in (m.get("starters") or [])]
                    if bn:
                        v, p = max(bn)
                        loser_bench = {"name": L.pname(p), "pts": r2(v)}
            label = {1: "Championship", 3: "3rd place", 5: "5th place"}.get(g.get("p")) if g.get("p") else f"Round {g['r']}"
            po.append({"round": label, "week": wk, "winner": g["w"], "loser": g["l"],
                       "score": [score.get(g["w"]), score.get(g["l"])], "loser_best_bench": loser_bench})
        champ = next((p["winner"] for p in po if p["round"] == "Championship"), None)
        drafts = []
        for pk in load(s, "draft_picks.json"):
            md = pk.get("metadata") or {}
            pl = L.players.get(str(pk.get("player_id"))) or {}
            drafts.append({"round": pk["round"], "pick": pk["pick_no"], "roster_id": pk["roster_id"],
                           "player": f"{md.get('first_name','')} {md.get('last_name','')}".strip(), "pos": md.get("position"),
                           "nfl_team_now": pl.get("team"), "birth_year": (pl.get("birth_date") or "")[:4] or None})
        hist["seasons"][s] = {
            "teams": {rid: {"owner": t["owner"], "name": t["name"], "record": f"{rec[rid]['w']}-{rec[rid]['l']}",
                            "pf": r2(rec[rid]["pf"]), "moves": moves[rid], "bench_20plus_games": bench20[rid]}
                      for rid, t in teams.items()},
            "champion": champ, "playoffs": po,
            "notable_draft_picks": [d for d in drafts if d["round"] <= 2 or (d["pos"] in ("QB", "RB", "WR", "TE") and not d["nfl_team_now"])],
        }
    cur_rid = {o: rid for rid, o in owner_by_season[cur].items()}
    for s in seasons:
        for rid, t in hist["seasons"][s]["teams"].items():
            t["current_roster_id"] = cur_rid.get(owner_by_season[s].get(rid))
    hist["repeat_adds"] = [{"roster_id": cur_rid.get(o), "player": p, "times": n} for (o, p), n in adds_count.items() if n >= 3]
    hist["close_games"] = {cur_rid.get(o): {"wins": v[0], "losses": v[1]} for o, v in hist["close_games"].items()}
    hist["late_night_moves_this_season"] = dict(hist["late_night_moves_this_season"])
    return hist


def decisions(f):
    """Candidates for Smart Move / Dumb Move, scored by impact. Writers choose; these are facts."""
    out = []
    for m in f["matchups"]:
        for s in m["sides"]:
            rid, won = s["roster_id"], s["roster_id"] == m["winner"]
            opp = next(x for x in m["sides"] if x["roster_id"] != rid)["points"]
            if s["points_left_on_bench"] >= 5:
                out.append({"kind": "lineup_cost", "roster_id": rid, "impact": s["points_left_on_bench"],
                            "changed_result": (not won) and s["optimal_points"] > opp,
                            "detail": {"optimal_points": s["optimal_points"], "actual": s["points"], "opponent": opp,
                                       "should_have_started": s["should_have_started"], "should_have_sat": s["should_have_sat"]}})
            for name in s["bye_starters"]:
                out.append({"kind": "started_player_on_bye", "roster_id": rid, "impact": 0, "detail": {"player": name, "won_anyway": won}})
    for t in f["transactions"]:
        for a in t["adds"]:
            if a["started"] and a["pts"] >= 12:
                out.append({"kind": "pickup_paid_off", "roster_id": a["to"], "impact": a["pts"], "detail": dict(a, time=t["time"])})
        for d in t["drops"]:
            if d.get("pts_this_week", 0) >= 12:
                out.append({"kind": "drop_backfired", "roster_id": d["from"], "impact": d["pts_this_week"], "detail": dict(d, time=t["time"])})
    out.sort(key=lambda x: -x["impact"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    args = ap.parse_args()
    L = League()
    week = args.week or L.chain["week"]
    season = L.season
    teams, rosters = L.season_data(season)
    out_m, tx, segments, pbp_complete, first_kick = week_facts(L, week)
    rec_after = records_through(season, week)
    rec_before = records_through(season, week - 1)
    pf_rank = {rid: i + 1 for i, rid in enumerate(sorted(rec_after, key=lambda r: -rec_after[r]["pf"]))}
    standings = sorted(rec_after, key=lambda r: (-rec_after[r]["w"], -rec_after[r]["pf"]))
    T = {}
    for rid, t in teams.items():
        c = CFG["teams"].get(str(rid), {})
        ra, rb = rec_after[rid], rec_before[rid]
        T[rid] = {"roster_id": rid, "name": t["name"], "owner": t["owner"], "slug": slugify(t["name"]),
                  "color": c.get("color", "#888888"), "reporter": c.get("reporter") or f"{t['name']} Insider",
                  "avatar_url": t.get("avatar"),
                  "record_before": f"{rb['w']}-{rb['l']}", "record": f"{ra['w']}-{ra['l']}", "pf": r2(ra["pf"]), "pa": r2(ra["pa"]),
                  "pf_rank": pf_rank[rid], "standing": standings.index(rid) + 1, "streak": streak(ra["results"])}
    scores = [(s["points"], s["roster_id"]) for m in out_m for s in m["sides"]]
    best_add = max((a for t in tx for a in t["adds"] if a["started"]), key=lambda a: a["pts"], default=None)
    facts = {
        "publication": CFG["publication"], "season": season, "week": week,
        "generated_at": dt.datetime.now(TZ).isoformat(timespec="minutes"),
        "league": {"num_teams": len(teams), "format": "2-QB PPR" if load(season, "league.json")["roster_positions"].count("QB") == 2 else "PPR",
                   "playoff_teams": load(season, "league.json")["settings"].get("playoff_teams"),
                   "playoff_week_start": load(season, "league.json")["settings"].get("playoff_week_start"),
                   "trade_deadline_week": load(season, "league.json")["settings"].get("trade_deadline")},
        "teams": T, "standings": standings, "matchups": out_m, "transactions": tx,
        "timeline_segments": segments, "first_kick_utc": first_kick, "pbp_complete": pbp_complete,
        "pbp_missing_games": getattr(week_facts, "pbp_missing", []),
        "awards": {"high_score": max(scores) if scores else None, "low_score": min(scores) if scores else None,
                   "closest": min(out_m, key=lambda m: m["margin"])["matchup_id"] if out_m else None,
                   "biggest_blowout": max(out_m, key=lambda m: m["margin"])["matchup_id"] if out_m else None,
                   "best_pickup_started": best_add},
        "history": history(L, week),
        "unrostered_scorers": getattr(week_facts, "free_agents", []),
    }
    facts["decision_candidates"] = decisions(facts)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import analytics
    lgc = load(season, "league.json")
    facts["analysis"] = analytics.analyze(
        season, week, lgc["scoring_settings"], L.players, rosters, {r["roster_id"]: 1 for r in rosters},
        lgc["roster_positions"], lgc["settings"].get("playoff_teams", 6), lgc["settings"].get("playoff_week_start", 15) - 1,
        CFG["timezone"])
    bench = []
    for m in out_m:
        for sd in m["sides"]:
            opp = next(x for x in m["sides"] if x["roster_id"] != sd["roster_id"])["points"]
            lost = sd["roster_id"] == m["loser"]
            bench.append({"roster_id": sd["roster_id"], "points_left": sd["points_left_on_bench"],
                          "optimal_points": sd["optimal_points"], "actual": sd["points"], "opponent": opp,
                          "lost": lost, "cost_the_game": lost and sd["optimal_points"] > opp,
                          "margin": r2(abs(sd["points"] - opp)), "swaps": sd["bench_swaps"]})
    bench.sort(key=lambda x: (-x["cost_the_game"], -x["points_left"]))
    facts["bench_report"] = bench
    bl = []
    for m in out_m:
        for sd in m["sides"]:
            if sd.get("busted_starters"):
                opp = next(x for x in m["sides"] if x["roster_id"] != sd["roster_id"])["points"]
                lost_pts = r2(sum(x["points_lost"] for x in sd["busted_starters"]))
                bl.append({"roster_id": sd["roster_id"], "starters": sd["busted_starters"], "points_lost": lost_pts,
                           "won_anyway": sd["roster_id"] == m["winner"],
                           "cost_the_game": sd["roster_id"] == m["loser"] and sd["points"] + lost_pts > opp})
    bl.sort(key=lambda x: (-x["cost_the_game"], -len(x["starters"]), -x["points_lost"]))
    facts["busted_lineups"] = bl
    out = os.path.join(ROOT, "content", f"{season}-w{week:02d}")
    os.makedirs(out, exist_ok=True)
    json.dump(facts, open(os.path.join(out, "facts.json"), "w"), indent=1, default=str)
    print("wrote", os.path.relpath(os.path.join(out, "facts.json"), ROOT),
          "| matchups", len(out_m), "| transactions", len(tx), "| pbp complete", pbp_complete,
          "| timelines match official:", all(m["rebuilt_matches_official"] for m in out_m))


if __name__ == "__main__":
    sys.exit(main())
