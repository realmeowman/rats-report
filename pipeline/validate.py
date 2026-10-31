"""Fact-check a week's stories.json against its facts.json.

Checks every number and clock time in the copy:
  ERROR  a decimal (e.g. 43.82) or clock time (e.g. 4:02 p.m.) that does not appear in the facts
  ERROR  a W-L record that does not appear in the facts
  WARN   a whole number above 12 that does not appear in the facts (could be fine, e.g. a
         derived count like "49 minutes"; the writer must be able to justify it)
Claims from outside the data (an NFL final score, a stat correction) belong in the
stories' "external_facts" list with a source; numbers listed there are allowed.
Also checks structure: every team has a beat, every matchup has a story, ids exist.

Usage: python3 pipeline/validate.py [--week N]   exit code 1 if any ERROR
"""
import argparse, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def walk(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)
    else:
        yield o


def numset(f):
    nums, times, recs, raw = set(), set(), set(), set()
    def addnum(x):
        raw.add(round(float(x), 4))
        nums.add(round(float(x), 2))
    for v in walk(f):
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            addnum(v)
        elif isinstance(v, str):
            for m in re.finditer(r"\b(\d{1,2}):(\d{2})\s*([AP]M)", v):
                times.add(f"{int(m.group(1))}:{m.group(2)} {m.group(3)}")
            for m in re.finditer(r"\b(\d{1,2})-(\d{1,2})\b", v):
                recs.add(f"{m.group(1)}-{m.group(2)}")
            for m in re.finditer(r"-?\d+(?:\.\d+)?", v):
                try:
                    addnum(m.group())
                except ValueError:
                    pass
    # margins at every moment of every race, and scores' differences
    for m in f.get("matchups", []):
        for h, a, b in m.get("race", []):
            nums.add(round(abs(a - b), 2))
        pts = [s["points"] for s in m["sides"]]
        nums.add(round(abs(pts[0] - pts[1]), 2))
        for s in m["sides"]:
            for p in s["starters"] + s["bench"]:
                nums.add(round(p["pts"], 2))
    for v in walk_dicts(f):
        if "wins" in v and "losses" in v:
            recs.add(f"{v['wins']}-{v['losses']}")
    # probabilities written as percentages ("78%", "17.3%")
    nums |= {float(round(x * 100)) for x in raw if 0 < x <= 1} | {round(x * 100, 1) for x in raw if 0 < x <= 1}
    # whole-number roundings of any decimal ("up 43", "down 58") are fine
    nums |= {float(int(x)) for x in list(nums)} | {float(round(x)) for x in list(nums)}
    return nums, times, recs


def walk_dicts(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk_dicts(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_dicts(v)


def text_items(s):
    def g(story, where):
        for k in ("kicker", "headline", "dek", "pull", "slam_caption", "blurb"):
            if story.get(k):
                yield where + "." + k, story[k]
        for i, p in enumerate(story.get("body", [])):
            yield f"{where}.body[{i}]", p
        for x in story.get("slam", []):
            yield where + ".slam", x["value"]
    yield from g(s["lead"], "lead")
    for k in ("smart_move", "dumb_move", "bench_beat"):
        if s.get(k):
            yield from g(s[k], k)
            yield k + ".stat", s[k].get("stat", "")
            yield k + ".stat_label", s[k].get("stat_label", "")
    for i, x in enumerate(s.get("features", [])):
        yield from g(x, f"features[{i}]")
        yield f"features[{i}].stat", x.get("stat", "")
        yield f"features[{i}].stat_label", x.get("stat_label", "")
    for i, x in enumerate(s.get("swing_plays", [])):
        yield from g(x, f"swing_plays[{i}]")
    for x in s.get("beats", []):
        if x.get("insight"):
            yield f"beat[{x['roster_id']}].insight", x["insight"]
    for k, x in (s.get("lookahead") or {}).items():
        yield from g(x, f"lookahead[{k}]")
    for i, x in enumerate(s.get("waiver_targets", []) + s.get("usage_watch", [])):
        yield f"film[{i}]", x.get("blurb", "")
    if s.get("playoff_note"):
        yield "playoff_note", s["playoff_note"]
    for k in ("headline", "blurb"):
        if (s.get("busted") or {}).get(k):
            yield "busted." + k, s["busted"][k]
    for i, x in enumerate(s.get("games", [])):
        yield from g(x, f"games[{i}]")
    for x in s.get("beats", []):
        yield from g(x, f"beat[{x['roster_id']}]")
    for x in s.get("rankings", []):
        yield from g(x, f"ranking[{x['roster_id']}]")


def check_text(items, nums, times, recs, ext, ext_nums, errors, warns):
    for where, txt in items:
        if not txt:
            continue
        t = txt.replace("–", "-").replace("−", "-").replace(",", "")
        for m in re.finditer(r"\b(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", t, re.I):
            key = f"{int(m.group(1))}:{m.group(2)} {m.group(3).upper()}M"
            if key not in times and key.replace(" ", "") not in ext.replace(" ", "").upper():
                errors.append(f"{where}: time '{m.group()}' not in facts")
        t2 = re.sub(r"\b\d{1,2}:\d{2}\s*[ap]\.?m\.?", " ", t, flags=re.I)
        for m in re.finditer(r"\b(\d{1,2})-(\d{1,2})\b", t2):
            if m.group() not in recs and not (int(m.group(1)) in ext_nums and int(m.group(2)) in ext_nums):
                errors.append(f"{where}: record/score '{m.group()}' not in facts")
        t3 = re.sub(r"\b\d{1,2}-\d{1,2}\b", " ", t2)
        for m in re.finditer(r"(?<![\w.])[-+]?\d+(?:\.\d+)?", t3):
            v = round(abs(float(m.group())), 2)
            if v in nums or v in ext_nums:
                continue
            if "." in m.group():
                errors.append(f"{where}: number {m.group()} not in facts")
            elif v > 12 and not (1990 <= v <= 2035):
                warns.append(f"{where}: whole number {m.group()} not in facts (justify or remove)")


def validate_daily(date):
    d = json.load(open(os.path.join(ROOT, "content", "daily", date, "facts.json")))
    s = json.load(open(os.path.join(ROOT, "content", "daily", date, "stories.json")))
    wk = sorted(x for x in os.listdir(os.path.join(ROOT, "content")) if x[:4].isdigit())
    w = json.load(open(os.path.join(ROOT, "content", wk[-1], "facts.json"))) if wk else {}
    nums, times, recs = numset({"daily": d, "weekly": w, "matchups": w.get("matchups", [])})
    for m in d["matchups"]:
        nums.add(round(abs(m["projected"][0] - m["projected"][1]), 2))
        for x in m["projected"] + m["live"]:
            nums.add(round(x, 1)); nums.add(float(round(x)))
    ext = " ".join(x.get("claim", "") for x in s.get("external_facts", []))
    ext_nums = {round(float(x), 2) for x in re.findall(r"\d+(?:\.\d+)?", ext)}
    errors, warns = [], []
    if not s.get("lead", {}).get("headline"):
        errors.append("daily needs a lead with a headline")
    keys = {m["key"] for m in d["matchups"]}
    if s["lead"].get("matchup_key") and s["lead"]["matchup_key"] not in keys:
        errors.append("lead.matchup_key not a current matchup")
    for k, pv in (s.get("previews") or {}).items():
        if k not in keys:
            errors.append(f"preview key {k} not a current matchup")
        if pv.get("pick") is not None and str(pv["pick"]) not in d["teams"]:
            errors.append(f"preview {k} pick is not a team")
    pids = {x["id"] for x in d["trending_adds"] + d["trending_drops"]}
    for k in (s.get("trending_notes") or {}):
        if k not in pids:
            errors.append(f"trending note for {k}, who is not in the trending lists")
    tss = {t["id"] for t in d["new_moves"]}
    for k, g in (s.get("move_grades") or {}).items():
        if k not in tss:
            errors.append(f"move grade for {k}, which is not a new move")
        if not re.fullmatch(r"[A-DF][+-]?", g.get("grade", "")):
            errors.append(f"move grade {g.get('grade')} must be A-F")
    dids = {x["id"] for x in d.get("open_decisions", []) + d.get("resolved_decisions", [])}
    for k in (s.get("decision_notes") or {}):
        if k not in dids:
            errors.append(f"decision note for {k}, which is not an open or resolved decision")
    items = []
    for k, n in (s.get("decision_notes") or {}).items():
        items += [(f"decision_notes[{k}].headline", n.get("headline")), (f"decision_notes[{k}].blurb", n.get("blurb"))]
    L = s["lead"]
    for k in ("kicker", "headline", "dek", "pull"):
        items.append(("lead." + k, L.get(k)))
    items += [(f"lead.body[{i}]", p) for i, p in enumerate(L.get("body", []))]
    for i, q in enumerate(s.get("quick_hits", [])):
        items += [(f"quick_hits[{i}].headline", q.get("headline")), (f"quick_hits[{i}].body", q.get("body"))]
    for k, pv in (s.get("previews") or {}).items():
        items += [(f"previews[{k}].headline", pv.get("headline")), (f"previews[{k}].blurb", pv.get("blurb"))]
    for grp in ("alert_notes", "trending_notes"):
        items += [(f"{grp}[{k}]", v) for k, v in (s.get(grp) or {}).items()]
    items += [(f"move_grades[{k}]", g.get("blurb")) for k, g in (s.get("move_grades") or {}).items()]
    check_text(items, nums, times, recs, ext, ext_nums, errors, warns)
    for x in warns:
        print("WARN ", x)
    for x in errors:
        print("ERROR", x)
    print(f"daily {date}: {len(errors)} errors, {len(warns)} warnings")
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    ap.add_argument("--daily")
    a = ap.parse_args()
    if a.daily:
        return validate_daily(a.daily)
    dirs = sorted(glob.glob(os.path.join(ROOT, "content", "*-w*")))
    d = next((x for x in dirs if x.endswith(f"-w{a.week:02d}")), None) if a.week else dirs[-1]
    f = json.load(open(os.path.join(d, "facts.json")))
    s = json.load(open(os.path.join(d, "stories.json")))
    nums, times, recs = numset(f)
    ext = " ".join(x.get("claim", "") for x in s.get("external_facts", []))
    ext_nums = {round(float(x), 2) for x in re.findall(r"\d+(?:\.\d+)?", ext)}
    errors, warns = [], []

    # structure
    tids = set(f["teams"].keys())
    beats = {str(b["roster_id"]) for b in s.get("beats", [])}
    if beats != tids:
        errors.append(f"beats must cover every team exactly once; missing {sorted(tids - beats)}, extra {sorted(beats - tids)}")
    mids = {m["matchup_id"] for m in f["matchups"]}
    covered = {s["lead"]["matchup_id"]} | {g["matchup_id"] for g in s.get("games", [])}
    if covered != mids:
        errors.append(f"lead + games must cover every matchup once; missing {sorted(mids - covered)}")
    if [str(r["roster_id"]) for r in s.get("rankings", [])].__len__() != len(tids):
        errors.append("rankings must list every team once")
    slugs = [s["lead"]["slug"]] + [g["slug"] for g in s.get("games", [])]
    if len(set(slugs)) != len(slugs) or any(not re.fullmatch(r"[a-z0-9-]+", x) for x in slugs):
        errors.append("story slugs must be unique, lowercase, letters/numbers/hyphens")

    play_ids = {p["id"] for m in f["matchups"] for p in m.get("big_plays", [])}
    for sp in s.get("swing_plays", []):
        if sp.get("play_id") not in play_ids:
            errors.append(f"swing play id {sp.get('play_id')} not in facts big_plays")
    for k in ("smart_move", "dumb_move", "bench_beat"):
        if s.get(k) and str(s[k].get("roster_id")) not in tids:
            errors.append(f"{k} roster_id not a team")
    fslugs = [x.get("slug", "") for x in s.get("features", [])]
    if len(set(fslugs + slugs)) != len(fslugs + slugs) or any(not re.fullmatch(r"[a-z0-9-]+", x) for x in fslugs):
        errors.append("feature slugs must be unique, lowercase, letters/numbers/hyphens")
    A = f.get("analysis") or {}
    keys = {m["key"] for m in A.get("next_week", [])}
    for k in (s.get("lookahead") or {}):
        if k not in keys:
            errors.append(f"lookahead key {k} not in analysis.next_week")
    wids = {x["player_id"] for x in A.get("waiver_targets", [])}
    uids = {x["player_id"] for x in A.get("usage_rising", []) + A.get("usage_falling", []) + A.get("td_dependent", [])}
    for x in s.get("waiver_targets", []):
        if x.get("player_id") not in wids:
            errors.append(f"waiver target {x.get('player_id')} not in analysis.waiver_targets")
    for x in s.get("usage_watch", []):
        if x.get("player_id") not in uids:
            errors.append(f"usage watch {x.get('player_id')} not in analysis usage lists")
    for where, txt in text_items(s):
        if not txt:
            continue
        t = txt.replace("–", "-").replace("−", "-").replace(",", "")
        for m in re.finditer(r"\b(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", t, re.I):
            key = f"{int(m.group(1))}:{m.group(2)} {m.group(3).upper()}M"
            if key not in times and key.replace(" ", "") not in ext.replace(" ", "").upper():
                errors.append(f"{where}: time '{m.group()}' not in facts")
        t2 = re.sub(r"\b\d{1,2}:\d{2}\s*[ap]\.?m\.?", " ", t, flags=re.I)
        for m in re.finditer(r"\b(\d{1,2})-(\d{1,2})\b", t2):
            if m.group() not in recs and not (int(m.group(1)) in ext_nums and int(m.group(2)) in ext_nums):
                errors.append(f"{where}: record/score '{m.group()}' not in facts")
        t3 = re.sub(r"\b\d{1,2}-\d{1,2}\b", " ", t2)
        for m in re.finditer(r"(?<![\w.])[-+]?\d+(?:\.\d+)?", t3):
            v = round(abs(float(m.group())), 2)
            if v in nums or v in ext_nums:
                continue
            if "." in m.group():
                errors.append(f"{where}: number {m.group()} not in facts")
            elif v > 12 and not (1990 <= v <= 2035):
                warns.append(f"{where}: whole number {m.group()} not in facts (justify or remove)")

    for w in warns:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print(f"{os.path.basename(d)}: {len(errors)} errors, {len(warns)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
