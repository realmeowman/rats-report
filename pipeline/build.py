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
        for k, label in (("smart_move", "Smart Move"), ("dumb_move", "Dumb Move")):
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
        self.stories = [s["lead"]] + s["games"] + s["features"] + self.moves + s["beats"]

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
                    story_matchup=E.story_matchup, game_path=E.game_path, moves=E.moves, other=E.other, dash=dash, initials=initials,
                    ordinal=ordinal, race_json=E.race_json(), edition_path=E.base, site_url=site_url, path=path,
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
        if E is latest:
            write("/", env.get_template("edition.html").render(**dict(ctx, path="/")))
        for st in E.stories:
            og = f"/og/{f['season']}-w{f['week']:02d}-{st['slug']}.jpg"
            if st["kind"] == "beat":
                t = E.T(st["roster_id"])
                kicker, color = f"{t['name']} Insider · Week {f['week']}", t["color"]
            elif st["kind"] in ("smart_move", "dumb_move", "feature"):
                rid = st.get("roster_id") or (st.get("roster_ids") or [None])[0]
                kicker = f"Week {f['week']} · {st['kicker']}"
                color = {"smart_move": "#3DDC84", "dumb_move": "#FF5252"}.get(st["kind"]) or (E.T(rid)["color"] if rid else "#D8BB88")
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
    # misc
    open(os.path.join(SITE, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n" if CFG.get("noindex", True) else "User-agent: *\nAllow: /\n")
    shutil.copy(os.path.join(SITE, "index.html"), os.path.join(SITE, "404.html"))
    if not args.no_og:
        og_render(og_jobs)
    n = sum(len(fs) for _, _, fs in os.walk(SITE))
    print(f"built site/: {len(eds)} edition(s), {n} files, og cards {'skipped' if args.no_og else len(og_jobs)}")


if __name__ == "__main__":
    sys.exit(main())
