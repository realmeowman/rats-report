"""Fantasy analysis layered on top of the week's facts: all-play records and luck, playoff odds,
next week's projected matchups and bye holes, player usage trends, and waiver targets.

Everything here is computed from Sleeper data (stats, projections, rosters, schedule) under the
league's own scoring and lineup rules. Called by facts.py; results land in facts["analysis"].
"""
import collections, json, math, os, random, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
SKILL = ("QB", "RB", "WR", "TE")


def load(*p):
    path = os.path.join(RAW, *p)
    return json.load(open(path)) if os.path.exists(path) else None


def r2(x):
    return round(float(x or 0), 2)


def pts(statline, sc):
    return sum((statline.get(k) or 0) * v for k, v in sc.items()) if statline else 0.0


def pairs(ms):
    by = collections.defaultdict(list)
    for m in ms or []:
        if m.get("matchup_id") is not None:
            by[m["matchup_id"]].append(m)
    return [v for v in by.values() if len(v) == 2]


def all_play(season, week):
    """Record each team would have if it played every other team every week."""
    out = collections.defaultdict(lambda: {"w": 0, "l": 0, "t": 0})
    weekly = collections.defaultdict(list)
    for w in range(1, week + 1):
        ms = load(season, f"matchups_{w}.json") or []
        scores = {m["roster_id"]: m["points"] or 0 for m in ms}
        for rid, s in scores.items():
            weekly[rid].append(s)
            for oid, o in scores.items():
                if oid == rid:
                    continue
                k = "w" if s > o else "l" if s < o else "t"
                out[rid][k] += 1
    return out, weekly


def optimal_lineup(cands, slots):
    flex_ok = {"FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"}, "SUPER_FLEX": set(SKILL)}
    pool = sorted(cands, key=lambda r: -r["proj"])
    used, lineup = set(), []
    for slot in sorted(slots, key=lambda x: x in flex_ok):
        ok = flex_ok.get(slot, {slot})
        pick = next((r for r in pool if r["id"] not in used and r["pos"] in ok and r["proj"] > 0), None)
        if pick:
            used.add(pick["id"])
            lineup.append(dict(pick, slot=slot))
        else:
            lineup.append({"slot": slot, "empty": True})
    return lineup


def analyze(season, week, sc, players, rosters, teams_by_rid, roster_positions, playoff_teams, last_reg_week, tz_name):
    slots = [x for x in roster_positions if x not in ("BN", "IR", "TAXI")]
    name = lambda pid: (lambda p: f"{p.get('first_name','')} {p.get('last_name','')}".strip() if p.get("position") != "DEF"
                        else f"{p.get('first_name','')} {p.get('last_name','')} D/ST".strip())(players.get(str(pid)) or {})
    pos = lambda pid: (players.get(str(pid)) or {}).get("position")
    nflteam = lambda pid: (players.get(str(pid)) or {}).get("team") if pos(pid) != "DEF" else str(pid)
    owner = {p: r["roster_id"] for r in rosters for p in (r.get("players") or [])}

    # ---------- records, all-play, luck ----------
    ap, weekly = all_play(season, week)
    rec = collections.defaultdict(lambda: [0, 0])
    for w in range(1, week + 1):
        for a, b in pairs(load(season, f"matchups_{w}.json")):
            if (a["points"] or 0) != (b["points"] or 0):
                win, lose = (a, b) if a["points"] > b["points"] else (b, a)
                rec[win["roster_id"]][0] += 1
                rec[lose["roster_id"]][1] += 1
    team_rows = {}
    for rid in teams_by_rid:
        a = ap[rid]
        games = a["w"] + a["l"] + a["t"]
        pct = (a["w"] + 0.5 * a["t"]) / games if games else 0
        exp_w = pct * week
        sc_list = weekly[rid]
        team_rows[rid] = {"all_play": f"{a['w']}-{a['l']}" + (f"-{a['t']}" if a["t"] else ""),
                          "all_play_pct": round(pct, 3), "expected_wins": round(exp_w, 1),
                          "luck": round(rec[rid][0] - exp_w, 1),
                          "avg_points": r2(statistics.mean(sc_list)) if sc_list else 0,
                          "last3_avg": r2(statistics.mean(sc_list[-3:])) if sc_list else 0,
                          "high": r2(max(sc_list)) if sc_list else 0, "low": r2(min(sc_list)) if sc_list else 0}

    # ---------- next week: projected lineups, byes, win probability ----------
    nxt = week + 1
    proj = load(season, f"projections_{nxt}.json") or {}
    playing = {nflteam(pid) for pid, s in proj.items() if pts(s, sc) > 0.5}
    def proj_rows(rid):
        r = next(x for x in rosters if x["roster_id"] == rid)
        rows = []
        for pid in r.get("players") or []:
            p = pos(pid)
            if p not in SKILL + ("K", "DEF"):
                continue
            pr = pts(proj.get(pid) or {}, sc)
            inj = (players.get(str(pid)) or {}).get("injury_status")
            rows.append({"id": pid, "name": name(pid), "pos": p, "proj": r2(pr), "on_bye": nflteam(pid) not in playing,
                         "injury": inj})
        return rows
    next_week = []
    sched = load(season, f"schedule_{nxt}.json") or []
    team_proj = {}
    for rid in teams_by_rid:
        rows = proj_rows(rid)
        lineup = optimal_lineup([x for x in rows if not x["on_bye"] and x["injury"] not in ("Out", "IR", "Suspended")], slots)
        total = sum(x.get("proj", 0) for x in lineup)
        # who matters and is unavailable: players good enough to start who are on bye or out
        best_unavail = [x for x in sorted(rows, key=lambda r: -r["proj"]) if x["on_bye"] or x["injury"] in ("Out", "IR")]
        qbs_available = sum(1 for x in rows if x["pos"] == "QB" and not x["on_bye"] and x["injury"] not in ("Out", "IR", "Suspended") and x["proj"] > 0)
        team_proj[rid] = {"projected": r2(total), "lineup": [{k: v for k, v in x.items() if k in ("name", "pos", "proj", "slot", "empty")} for x in lineup],
                          "bye_players": [x["name"] for x in rows if x["on_bye"]],
                          "qbs_available": qbs_available, "qb_slots": slots.count("QB") + slots.count("SUPER_FLEX"),
                          "empty_slots": [x["slot"] for x in lineup if x.get("empty")]}
    sd_team = statistics.pstdev([s for v in weekly.values() for s in v]) if weekly else 25
    for a, b in pairs(sched):
        pa, pb = team_proj[a["roster_id"]]["projected"], team_proj[b["roster_id"]]["projected"]
        z = (pa - pb) / (math.sqrt(2) * sd_team) if sd_team else 0
        wp = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        fav, dog = (a, b) if pa >= pb else (b, a)
        next_week.append({"key": f"w{nxt}-m{a['matchup_id']}", "week": nxt, "teams": [a["roster_id"], b["roster_id"]],
                          "projected": [pa, pb], "win_prob": [round(wp, 3), round(1 - wp, 3)],
                          "favorite": fav["roster_id"], "spread": r2(abs(pa - pb))})

    # ---------- playoff odds (Monte Carlo over the remaining regular season) ----------
    rem = [pairs(load(season, f"schedule_{w}.json")) for w in range(nxt, last_reg_week + 1)]
    pf = {rid: sum(weekly[rid]) for rid in teams_by_rid}
    mu = {rid: 0.6 * team_rows[rid]["avg_points"] + 0.4 * (team_proj[rid]["projected"] or team_rows[rid]["avg_points"]) for rid in teams_by_rid}
    sims, made, top2, wins_total = 10000, collections.Counter(), collections.Counter(), collections.Counter()
    rng = random.Random(7)
    for _ in range(sims):
        w_ = {rid: rec[rid][0] for rid in teams_by_rid}
        p_ = dict(pf)
        for wk in rem:
            for a, b in wk:
                ra, rb = a["roster_id"], b["roster_id"]
                sa, sb = rng.gauss(mu[ra], sd_team), rng.gauss(mu[rb], sd_team)
                p_[ra] += sa; p_[rb] += sb
                w_[ra if sa > sb else rb] += 1
        order = sorted(teams_by_rid, key=lambda r: (-w_[r], -p_[r]))
        for i, r in enumerate(order):
            if i < playoff_teams:
                made[r] += 1
            if i < 2:
                top2[r] += 1
            wins_total[r] += w_[r]
    for rid in teams_by_rid:
        team_rows[rid].update({"playoff_odds": round(made[rid] / sims, 3), "top2_odds": round(top2[rid] / sims, 3),
                               "projected_final_wins": round(wins_total[rid] / sims, 1),
                               "games_left": len(rem), "next_week": team_proj[rid]})

    # ---------- player usage: opportunity share and trends ----------
    weeks_stats = {w: load(season, f"stats_{w}.json") or {} for w in range(1, week + 1)}
    team_tgt = {w: collections.Counter() for w in weeks_stats}
    for w, st in weeks_stats.items():
        for pid, s in st.items():
            t = nflteam(pid)
            if t and pos(pid) in SKILL:
                team_tgt[w][t] += s.get("rec_tgt", 0) or 0
    def usage(pid):
        rows = []
        for w in range(1, week + 1):
            s = weeks_stats[w].get(pid)
            if not s or not s.get("gp"):
                continue
            t = nflteam(pid)
            rows.append({"w": w, "pts": r2(pts(s, sc)), "opp": (s.get("rec_tgt") or 0) + (s.get("rush_att") or 0),
                         "tgt": s.get("rec_tgt") or 0, "att": s.get("rush_att") or 0,
                         "rz": (s.get("rec_rz_tgt") or 0) + (s.get("rush_rz_att") or 0),
                         "snap": (s.get("off_snp") or 0) / s["tm_off_snp"] if s.get("tm_off_snp") else None,
                         "tshare": (s.get("rec_tgt") or 0) / team_tgt[w][t] if team_tgt[w].get(t) else None,
                         "td_pts": 6 * ((s.get("rec_td") or 0) + (s.get("rush_td") or 0))})
        return rows
    trends = []
    for pid in set(owner) | {p for p, s in (proj or {}).items() if pts(s, sc) >= 8}:
        if pos(pid) not in ("RB", "WR", "TE"):
            continue
        u = usage(pid)
        if len(u) < 4:
            continue
        last, prior = u[-2:], u[:-2]
        opp_l, opp_p = statistics.mean(x["opp"] for x in last), statistics.mean(x["opp"] for x in prior)
        snap_l = [x["snap"] for x in last if x["snap"] is not None]
        snap_p = [x["snap"] for x in prior if x["snap"] is not None]
        tot_pts = sum(x["pts"] for x in u)
        trends.append({"player_id": pid, "name": name(pid), "pos": pos(pid), "nfl_team": nflteam(pid),
                       "roster_id": owner.get(pid), "games": len(u),
                       "opps_last2": round(opp_l, 1), "opps_before": round(opp_p, 1), "opps_change": round(opp_l - opp_p, 1),
                       "snap_last2": round(statistics.mean(snap_l), 2) if snap_l else None,
                       "snap_before": round(statistics.mean(snap_p), 2) if snap_p else None,
                       "target_share_last2": round(statistics.mean([x["tshare"] for x in last if x["tshare"] is not None] or [0]), 2),
                       "rz_opps_season": sum(x["rz"] for x in u),
                       "ppg": r2(tot_pts / len(u)), "ppg_last2": r2(statistics.mean(x["pts"] for x in last)),
                       "td_share_of_points": round(sum(x["td_pts"] for x in u) / tot_pts, 2) if tot_pts > 0 else 0,
                       "proj_next": r2(pts(proj.get(pid) or {}, sc))})
    rising = sorted([t for t in trends if t["opps_change"] >= 3], key=lambda t: -t["opps_change"])[:10]
    falling = sorted([t for t in trends if t["opps_change"] <= -3 and t["roster_id"]], key=lambda t: t["opps_change"])[:10]
    td_dependent = sorted([t for t in trends if t["roster_id"] and t["td_share_of_points"] >= 0.4 and t["ppg"] >= 10],
                          key=lambda t: -t["td_share_of_points"])[:6]

    # ---------- waiver targets: unrostered, projected or rising ----------
    waivers = []
    for pid, s in proj.items():
        if pid in owner or pos(pid) not in SKILL + ("K", "DEF"):
            continue
        pr = pts(s, sc)
        if pr < 6:
            continue
        t = next((x for x in trends if x["player_id"] == pid), None)
        season_pts = sum(pts(weeks_stats[w].get(pid) or {}, sc) for w in weeks_stats)
        waivers.append({"player_id": pid, "name": name(pid), "pos": pos(pid), "nfl_team": nflteam(pid), "proj_next": r2(pr),
                        "season_points": r2(season_pts), "last_week": r2(pts(weeks_stats[week].get(pid) or {}, sc)),
                        "opps_change": t["opps_change"] if t else None, "snap_last2": t["snap_last2"] if t else None})
    waivers.sort(key=lambda x: -(x["proj_next"] + (3 if x["pos"] == "QB" else 0)))
    rostered_qbs = collections.Counter(owner[p] for p in owner if pos(p) == "QB")

    return {"teams": team_rows, "next_week": next_week, "next_week_number": nxt,
            "usage_rising": rising, "usage_falling": falling, "td_dependent": td_dependent,
            "waiver_targets": waivers[:12], "qbs_rostered": dict(rostered_qbs),
            "model_notes": {"score_sd": r2(sd_team), "sims": sims,
                            "method": "Each remaining game simulated with team scores drawn from a normal distribution: mean = 60% season average + 40% next-week projection; tiebreak = points for."}}
