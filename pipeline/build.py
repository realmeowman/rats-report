"""Render the whole site into site/ from content/*/facts.json + stories.json.

  site/index.html                         latest edition
  site/<season>/week-<n>/index.html       each edition
  site/<season>/week-<n>/<slug>/          each story (game stories and team beats)
  site/teams/, site/teams/<slug>/         team pages with every week's beat story
  site/archive/                           all editions
  site/og/*.jpg                           1200x630 preview cards for link unfurls

Usage: python3 pipeline/build.py [--no-og]
"""
import argparse, glob, json, os, re, shutil, sys, time
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
CFG = json.load(open(os.path.join(ROOT, "config.json")))


def dash(rec):
    return rec.replace("-", "–")


def initials(name):
    return "".join(w[0] for w in name.split()[:2]).upper()


def pct(x):
    v = x * 100
    if v >= 99.95:
        return ">99.9%"
    if v >= 99:
        return f"{v:.1f}%"
    if 0 < v < 1:
        return "<1%"
    return f"{v:.0f}%"


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def team_initials(name):
    words = re.findall(r"[A-Za-z0-9]+", name)
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:2]).upper()


AVATARS = {}


def fetch_avatars(latest_facts):
    """Self-host team avatars when Sleeper's image CDN is reachable; otherwise pages load them from Sleeper."""
    import urllib.request
    out = os.path.join(ROOT, "static", "teams")
    os.makedirs(out, exist_ok=True)
    for rid, t in latest_facts["teams"].items():
        url = t.get("avatar_url")
        if not url:
            continue
        dest = os.path.join(out, f"{t['slug']}.jpg")
        try:
            if not os.path.exists(dest):
                with urllib.request.urlopen(url, timeout=20) as r, open(dest, "wb") as fh:
                    fh.write(r.read())
            AVATARS[rid] = f"/static/teams/{t['slug']}.jpg"
        except Exception:
            pass


def dailies():
    out = []
    for d in sorted(glob.glob(os.path.join(ROOT, "content", "daily", "20*"))):
        fp, sp = os.path.join(d, "facts.json"), os.path.join(d, "stories.json")
        if os.path.exists(fp) and os.path.exists(sp):
            out.append((json.load(open(fp)), json.load(open(sp))))
    return out


def editions():
    out = []
    for d in sorted(glob.glob(os.path.join(ROOT, "content", "*-w*"))):
        fp, sp = os.path.join(d, "facts.json"), os.path.join(d, "stories.json")
        if os.path.exists(fp) and os.path.exists(sp):
            out.append((json.load(open(fp)), json.load(open(sp))))
    out.sort(key=lambda e: (e[0]["season"], e[0]["week"]))
    return out


class Edition:
    def __init__(self, f, s):
        self.f, self.s = f, s
        self.base = f"/{f['season']}/week-{f['week']}/"
        for rid, t in f["teams"].items():
            t["initials"] = team_initials(t["name"])
            t["avatar"] = AVATARS.get(rid) or t.get("avatar_url")
            t["reporter"] = f"{t['name']} Insider"
        for st in [s["lead"]] + s["games"]:
            st["kind"] = "game"
        for b in s["beats"]:
            b["kind"] = "beat"
            b["slug"] = f["teams"][str(b["roster_id"])]["slug"]
        # team beats run in standings order
        s["beats"].sort(key=lambda b: f["teams"][str(b["roster_id"])]["standing"])
        for k, label in (("smart_move", "Smart Move"), ("dumb_move", "Dumb Move"), ("bench_beat", "Bench Beat")):
            if s.get(k):
                s[k]["kind"] = k
                s[k]["slug"] = k.replace("_", "-")
                s[k].setdefault("kicker", label)
        s.setdefault("features", [])
        for x in s["features"]:
            x["kind"] = "feature"
        s.setdefault("swing_plays", [])
        plays = {p["id"]: dict(p, matchup_id=m["matchup_id"]) for m in f["matchups"] for p in m.get("big_plays", [])}
        for sp in s["swing_plays"]:
            sp["play"] = plays[sp["play_id"]]
        self.moves = [s[k] for k in ("smart_move", "dumb_move") if s.get(k)]
        self.bench = s.get("bench_beat")
        A = f.get("analysis") or {}
        self.A = A
        allu = {x["player_id"]: x for x in A.get("usage_rising", []) + A.get("usage_falling", []) + A.get("td_dependent", [])}
        wv = {x["player_id"]: x for x in A.get("waiver_targets", [])}
        for x in s.get("usage_watch", []):
            x["p"] = allu.get(x["player_id"])
            x["dir"] = "up" if x["p"] and x["p"]["opps_change"] > 0 else "down"
        for x in s.get("waiver_targets", []):
            x["p"] = wv.get(x["player_id"])
        nw = {m["key"]: m for m in A.get("next_week", [])}
        self.lookahead = []
        for k, m in nw.items():
            w = (s.get("lookahead") or {}).get(k, {})
            alerts = []
            for rid in m["teams"]:
                tp = A["teams"][str(rid)]["next_week"]
                if tp["qbs_available"] < tp["qb_slots"]:
                    alerts.append((rid, f"Only {tp['qbs_available']} healthy QB for {tp['qb_slots']} QB slots"))
                for sl in tp["empty_slots"]:
                    if sl != "QB":
                        alerts.append((rid, f"No {sl} available"))
            self.lookahead.append(dict(m, headline=w.get("headline"), blurb=w.get("blurb"), alerts=alerts))
        self.stories = [s["lead"]] + s["games"] + s["features"] + self.moves + ([self.bench] if self.bench else []) + s["beats"]

    def T(self, rid):
        return self.f["teams"][str(rid)]

    def M(self, mid):
        return next(m for m in self.f["matchups"] if m["matchup_id"] == mid)

    def team_matchup(self, rid):
        return next(m for m in self.f["matchups"] if rid in (m["winner"], m["loser"]))

    def result(self, rid):
        m = self.team_matchup(rid)
        me = next(x for x in m["sides"] if x["roster_id"] == rid)
        op = next(x for x in m["sides"] if x["roster_id"] != rid)
        return {"wl": "W" if m["winner"] == rid else "L", "pts": me["points"], "opp_pts": op["points"], "opp": op["roster_id"]}

    def story_path(self, st):
        return f"{self.base}{st['slug']}/"

    def story_matchup(self, st):
        if st.get("matchup_id") is not None:
            return self.M(st["matchup_id"])
        if st.get("roster_id") is not None:
            return self.team_matchup(st["roster_id"])
        return None

    def game_path(self, m):
        for st in [self.s["lead"]] + self.s["games"]:
            if st["matchup_id"] == m["matchup_id"]:
                return self.story_path(st)
        return self.base

    def other(self, m, rid):
        return m["loser"] if rid == m["winner"] else m["winner"]

    def race_json(self):
        races = {str(m["matchup_id"]): {"w": m["winner"], "l": m["loser"], "pts": m["race"]} for m in self.f["matchups"]}
        return json.dumps({"segments": self.f["timeline_segments"], "tz": CFG["timezone"], "kick_utc": self.f["first_kick_utc"],
                           "races": races}, separators=(",", ":")).replace("</", "<\\/")


def write(path, html):
    p = os.path.join(SITE, path.lstrip("/"), "index.html") if path.endswith("/") else os.path.join(SITE, path.lstrip("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(html)


def og_render(jobs):
    if not jobs:
        return
    from playwright.sync_api import sync_playwright
    env = Environment(loader=FileSystemLoader(os.path.join(ROOT, "templates")), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("og.html")
    font_dir = "file://" + os.path.join(ROOT, "static", "fonts")
    crest = "file://" + os.path.join(ROOT, "static", "crest.webp")
    tmp = os.path.join(ROOT, "data", "og_tmp")
    os.makedirs(tmp, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        for out, kicker, headline, color in jobs:
            n = len(headline)
            size, maxw = (112, 700) if n <= 34 else (96, 720) if n <= 52 else (80, 730) if n <= 72 else (66, 740)
            html = tpl.render(font_dir=font_dir, crest=crest, kicker=kicker, headline=headline, color=color,
                              size=size, maxw=maxw, brand=CFG["publication"])
            hp = os.path.join(tmp, "og.html")
            open(hp, "w").write(html)
            pg.goto("file://" + hp)
            pg.wait_for_timeout(150)
            pg.evaluate("document.fonts.ready")
            dest = os.path.join(SITE, out.lstrip("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            pg.screenshot(path=dest, type="jpeg", quality=86)
        b.close()
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-og", action="store_true")
    args = ap.parse_args()
    raw = editions()
    if raw:
        fetch_avatars(raw[-1][0])
    eds = [Edition(f, s) for f, s in raw]
    if not eds:
        print("no editions with stories.json yet")
        return 1
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(SITE, "static"))
    env = Environment(loader=FileSystemLoader(os.path.join(ROOT, "templates")), autoescape=select_autoescape(["html"]))
    env.filters["dash"] = dash
    site_url = CFG["site_url"].rstrip("/")
    build_id = str(int(time.time()))
    latest = eds[-1]
    og_jobs = []

    def common(E, path, title, desc, og, og_title=None, og_type="website"):
        import datetime as dt
        g = E.f["generated_at"]
        try:
            gl = dt.datetime.fromisoformat(g).strftime("%a %b %-d, %-I:%M %p")
        except Exception:
            gl = g
        return dict(cfg=CFG, f=E.f, s=E.s, T=E.T, M=E.M, result=E.result, story_path=E.story_path,
                    story_matchup=E.story_matchup, game_path=E.game_path, moves=E.moves, bench=E.bench, A=E.A, lookahead=E.lookahead, pct=pct, other=E.other, dash=dash, initials=initials,
                    ordinal=ordinal, masthead_line=None, race_json=E.race_json(), edition_path=E.base, site_url=site_url, path=path,
                    page_title=title, description=desc, og_image=og, og_title=og_title, og_type=og_type,
                    noindex=CFG.get("noindex", True), build_id=build_id, generated_label=gl, tzname="Pacific time"
                    if CFG["timezone"] == "America/Los_Angeles" else CFG["timezone"])

    for E in eds:
        f, s = E.f, E.s
        lead = s["lead"]
        ed_og = f"/og/{f['season']}-w{f['week']:02d}-edition.jpg"
        og_jobs.append((ed_og, f"Week {f['week']} · {lead['kicker']}", lead["headline"], E.T(lead.get("persp_roster_id") or E.M(lead["matchup_id"])["winner"])["color"]))
        ctx = common(E, E.base, f"{CFG['publication']} · Week {f['week']}", lead["dek"], ed_og, og_title=lead["headline"])
        html = env.get_template("edition.html").render(**ctx)
        write(E.base, html)
        if E is latest and not dailies():
            write("/", env.get_template("edition.html").render(**dict(ctx, path="/")))
        for st in E.stories:
            og = f"/og/{f['season']}-w{f['week']:02d}-{st['slug']}.jpg"
            if st["kind"] == "beat":
                t = E.T(st["roster_id"])
                kicker, color = f"{t['name']} Insider · Week {f['week']}", t["color"]
            elif st["kind"] in ("smart_move", "dumb_move", "feature", "bench_beat"):
                rid = st.get("roster_id") or (st.get("roster_ids") or [None])[0]
                kicker = f"Week {f['week']} · {st['kicker']}"
                color = {"smart_move": "#3DDC84", "dumb_move": "#FF5252", "bench_beat": "#D8BB88"}.get(st["kind"]) or (E.T(rid)["color"] if rid else "#D8BB88")
            else:
                m = E.M(st["matchup_id"])
                kicker, color = f"Week {f['week']} · {st['kicker']}", E.T(st.get("persp_roster_id") or m["winner"])["color"]
            og_jobs.append((og, kicker, st["headline"], color))
            desc = st.get("dek") or st["body"][0]
            desc = desc if len(desc) <= 200 else desc[:197].rsplit(" ", 1)[0] + "…"

            def others(cur, E=E):
                return [o for o in E.stories if o is not cur][:8]
            ctx = common(E, E.story_path(st), f"{st['headline']} · {CFG['short_name']}", desc, og, og_title=st["headline"], og_type="article")
            write(E.story_path(st), env.get_template("story.html").render(story=st, others=others, **ctx))

    # teams
    Lc = latest
    entries_by_team = {}
    for E in reversed(eds):
        for b in E.s["beats"]:
            entries_by_team.setdefault(str(b["roster_id"]), []).append(
                {"week": E.f["week"], "path": E.story_path(b), "headline": b["headline"], "excerpt": b["body"][0][:180].rsplit(" ", 1)[0] + "…"})
    team_cards = sorted(Lc.f["teams"].values(), key=lambda t: t["standing"])
    ctx = common(Lc, "/teams/", f"Teams · {CFG['short_name']}", "Every team in the league and its beat coverage.", f"/og/{Lc.f['season']}-w{Lc.f['week']:02d}-edition.jpg")
    write("/teams/", env.get_template("index_list.html").render(heading_html="The <em>Teams</em>", subheading=f"Standings after Week {Lc.f['week']}", team_cards=team_cards, entries=[], **ctx))
    for rid, t in Lc.f["teams"].items():
        og = f"/og/team-{t['slug']}.jpg"
        og_jobs.append((og, f"{t['record'].replace('-', '–')} · {t['reporter']}", t["name"], t["color"]))
        ctx = common(Lc, f"/teams/{t['slug']}/", f"{t['name']} · {CFG['short_name']}", f"{t['name']}: {dash(t['record'])}. Coverage from the {t['reporter']}.", og, og_title=t["name"])
        write(f"/teams/{t['slug']}/", env.get_template("team.html").render(team=t, entries=entries_by_team.get(rid, []), **ctx))
    # archive
    arch = [{"week": E.f["week"], "path": E.base, "headline": E.s["lead"]["headline"], "excerpt": f"{E.f['season']} season · {E.s['lead']['dek']}"} for E in reversed(eds)]
    ctx = common(Lc, "/archive/", f"Archive · {CFG['short_name']}", "Every edition of the Report.", f"/og/{Lc.f['season']}-w{Lc.f['week']:02d}-edition.jpg")
    write("/archive/", env.get_template("index_list.html").render(heading_html="The <em>Archive</em>", subheading="Every edition", team_cards=None, entries=arch, **ctx))
    # daily briefs: each gets /daily/<date>/, the newest is the front page
    ds_all = dailies()
    E = latest
    def DT(rid, d):
        t = dict(E.T(rid))
        dt_ = d["teams"].get(str(rid))
        if dt_:
            t["record"] = dt_["record"]
        return t
    def alert_text(a):
        k = a["kind"]
        if k == "empty_slot":
            return f"Empty {a['slot']} slot in the starting lineup"
        if k == "starter_on_bye":
            return f"{a['player']} is starting at {a['slot']} during his bye"
        if k == "starter_out":
            return f"{a['player']} is starting at {a['slot']} and is listed {a['status']}"
        if k in ("starter_doubtful", "starter_questionable"):
            return f"{a['player']} ({a['status']}) is starting at {a['slot']}"
        if k == "better_on_bench":
            return f"{a['bench']} (proj {a['bench_proj']:.1f}) is on the bench behind {a['starter']} (proj {a['starter_proj']:.1f})"
        return k
    import datetime as _dt
    for i, (d, dst) in enumerate(ds_all):
        is_latest = i == len(ds_all) - 1
        day_path = f"/daily/{d['date']}/"
        lead_m = next((m for m in d["matchups"] if m["key"] == dst["lead"].get("matchup_key")), None)
        groups = {}
        for a_ in d["lineup_alerts"]:
            groups.setdefault(a_["roster_id"], []).append(a_)
        alerts_by_team = sorted(groups.items(), key=lambda kv: -len(kv[1]))
        weekly_teasers = []
        if E.s:
            weekly_teasers.append({"path": E.story_path(E.s["lead"]), "kicker": E.s["lead"]["kicker"], "headline": E.s["lead"]["headline"], "dek": E.s["lead"]["dek"]})
            for k in ("smart_move", "dumb_move", "bench_beat"):
                if E.s.get(k):
                    x = E.s[k]
                    weekly_teasers.append({"path": E.story_path(x), "kicker": x["kicker"], "headline": x["headline"], "dek": x.get("dek", "")})
        earlier = [{"path": f"/daily/{x['date']}/", "day": _dt.date.fromisoformat(x["date"]).strftime("%a"),
                    "headline": y["lead"]["headline"], "kicker": f"{x['weekday']} · {y['lead']['kicker']}"}
                   for x, y in reversed(ds_all[:i])][:10]
        date_label = _dt.date.fromisoformat(d["date"]).strftime("%B %-d")
        og = f"/og/daily-{d['date']}.jpg"
        col = DT(lead_m["teams"][0], d)["color"] if lead_m else "#D8BB88"
        og_jobs.append((og, f"{d['weekday']} · {dst['lead']['kicker']}", dst["lead"]["headline"], col))
        base_ctx = dict(d=d, ds=dst, DT=lambda r, d=d: DT(r, d), lead_m=lead_m, alerts_by_team=alerts_by_team, alert_text=alert_text,
                        any_live=any(m["games_started"] for m in d["matchups"]), weekly=weekly_teasers, earlier=earlier,
                        date_label=date_label, day_path=day_path, masthead_line=f"{d['weekday']} · Week {d['week']}")
        ctx = common(E, day_path, f"{dst['lead']['headline']} · {CFG['short_name']}", dst["lead"]["dek"], og, og_title=dst["lead"]["headline"], og_type="article")
        write(day_path, env.get_template("daily.html").render(**{**ctx, **base_ctx, "is_page": True}))
        if is_latest:
            ctx = common(E, "/", f"{CFG['publication']} · {d['weekday']}", dst["lead"]["dek"], og, og_title=dst["lead"]["headline"])
            write("/", env.get_template("daily.html").render(**{**ctx, **base_ctx, "is_page": False}))
    if ds_all:
        arch_d = [{"week": _dt.date.fromisoformat(x["date"]).strftime("%-m/%-d"), "path": f"/daily/{x['date']}/", "headline": y["lead"]["headline"],
                   "excerpt": f"{x['weekday']} · {y['lead']['kicker']}"} for x, y in reversed(ds_all)]
        ctx = common(E, "/daily/", f"Daily briefs · {CFG['short_name']}", "Every daily brief.", f"/og/{E.f['season']}-w{E.f['week']:02d}-edition.jpg")
        write("/daily/", env.get_template("index_list.html").render(heading_html="Daily <em>Briefs</em>", subheading="Newest first", team_cards=None, entries=arch_d, **ctx))

    # misc
    open(os.path.join(SITE, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n" if CFG.get("noindex", True) else "User-agent: *\nAllow: /\n")
    shutil.copy(os.path.join(SITE, "index.html"), os.path.join(SITE, "404.html"))
    if not args.no_og:
        og_render(og_jobs)
    n = sum(len(fs) for _, _, fs in os.walk(SITE))
    print(f"built site/: {len(eds)} edition(s), {n} files, og cards {'skipped' if args.no_og else len(og_jobs)}")


if __name__ == "__main__":
    sys.exit(main())
