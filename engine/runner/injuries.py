"""Read the official EuroLeague injury report for a round and classify every rostered player.

Statuses:  OUT | GTD (questionable / game-time decision / doubtful / day-to-day) | AVAILABLE |
           NO_REPORT (club hasn't filed yet) | UNLISTED (not mentioned -> assumed available)
The report is prose written per club, e.g. "Larkin, Yilmaz and Dozier are ruled out for Thursday's
game"; names are matched to the team's EuroLeague roster by surname.
"""
import html as H
import json
import re
import unicodedata

import requests

BASE = "https://www.euroleaguebasketball.net"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# club's statement for THIS game -> OUT
OUT_PAT = [r"ruled out", r"\b(is|are) out\b", r"\bout for (the|thursday|friday|tuesday|wednesday|round|this)", r"will miss",
           r"not available", r"unavailable", r"won'?t play", r"will not play", r"did not travel", r"will not travel",
           r"not (be )?part of the (game ?day )?roster", r"out for the (rest|remainder)", r"season-ending",
           r"out (indefinitely|until)", r"out for (at least )?\w+ (weeks|months)", r"ruled out for"]
# background history (often stale) -> LIKELY_OUT: no bet, not removed if he has been playing
WEAK_PAT = [r"\bsidelined\b", r"\bsurgery\b", r"absences?\b", r"recovering", r"has been out", r"\bfracture",
            r"last played in", r"has not played since", r"yet to play", r"has not (yet )?played", r"\binjur(y|ed)\b"]
GTD_PAT = [r"\bmissed\b", r"game-?(time|day) decision", r"\bgtd\b", r"questionable", r"doubtful", r"\ba doubt\b",
           r"day[- ]to[- ]day", r"uncertain", r"will be (re-?)?evaluated", r"\bmonitored\b", r"\bunsure\b"]
AVAIL_PAT = [r"\bavailable\b", r"\breturn(s|ed)?\b", r"will play", r"\bcleared\b", r"full roster", r"\b(is|are|will be) back\b",
             r"made (his|their) (season |euroleague )?debut", r"\bdebut(ed)?\b"]
NOREP_PAT = [r"not yet (sent|submitted|issued)", r"no injury report has been (issued|sent|submitted)",
             r"has not (yet )?(sent|submitted)"]


ALIASES = {"PAN": "panathinaikos", "PRS": "paris", "BES": "besiktas", "PAM": "valencia", "RED": "zvezda",
           "ZAL": "zalgiris", "BAS": "baskonia", "OLY": "olympiacos", "ULK": "fenerbahce", "VIR": "virtus",
           "ASV": "asvel", "TEL": "maccabi", "PAR": "partizan", "MIL": "milan", "HTA": "hapoel", "MUN": "bayern",
           "BAR": "barcelona", "IST": "efes", "DUB": "dubai", "MAD": "real madrid", "MCO": "monaco"}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s)


def _tokens(s):
    return _norm(s).split()


def find_report_url(season, rnd):
    yy = f"el{str(season)[2:]}{str(season + 1)[2:]}"
    candidates = [f"/euroleague/news/injury-report-round-{rnd}-{yy}", f"/euroleague/news/injury-report-{yy}-round-{rnd}",
                  f"/en/euroleague/news/injury-report-round-{rnd}-{yy}/"]
    for c in candidates:
        try:
            r = requests.get(BASE + c, headers=UA, timeout=30)
            if r.status_code == 200 and "injur" in r.text.lower():
                return BASE + c, r.text
        except requests.RequestException:
            pass
    # fall back to the news listing and look for this round's injury report link
    for listing in ("/euroleague/news/", "/en/euroleague/news/"):
        try:
            h = requests.get(BASE + listing, headers=UA, timeout=30).text
        except requests.RequestException:
            continue
        for link in re.findall(r'href="([^"]*injury-report[^"]*)"', h):
            if re.search(rf"round-?{rnd}\b", link) and yy in link:
                url = link if link.startswith("http") else BASE + link
                return url, requests.get(url, headers=UA, timeout=30).text
    return None, None


def article_text(page_html):
    """Plain text of the article body (works for server-rendered and Next.js pages)."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, re.S)
    if m:
        blob = json.dumps(json.loads(m.group(1)))
        parts = re.findall(r'"(?:body|content|text|html)":\s*"((?:[^"\\]|\\.){80,})"', blob)
        if parts:
            txt = " \n".join(json.loads(f'"{p}"') for p in parts)
            return _strip(txt)
    return _strip(page_html)


def _strip(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S)
    h = re.sub(r"</(p|li|h\d|div|br)>|<br ?/?>", "\n", h)
    return re.sub(r"[ \t]+", " ", H.unescape(re.sub(r"<[^>]+>", " ", h)))


def _history_only(s, rnd):
    """True if the sentence talks about earlier rounds and not this one (e.g. 'returned in Round 9')."""
    if rnd is None:
        return False
    nums = [int(x) for x in re.findall(r"\b(\d+)\b", " ".join(re.findall(r"rounds? [\d ,and-]+", s)))]
    if not nums:
        return bool(re.search(r"\b(since|was|were|had been|last (week|season))\b", s)) and not re.search(
            r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)'?s? game|this round|tonight", s)
    return all(n < rnd for n in nums)


def classify(sentence, rnd=None):
    s = sentence.lower()
    hist = _history_only(s, rnd)
    st = _classify(s)
    if hist and st == "OUT":
        return "LIKELY_OUT"
    if hist and st in ("AVAILABLE", "MIXED"):
        return None
    return st


def _classify(s):
    if any(re.search(p, s) for p in NOREP_PAT):
        return "NO_REPORT"
    if any(re.search(p, s) for p in GTD_PAT):
        return "GTD"
    strong = any(re.search(p, s) for p in OUT_PAT)
    avail = any(re.search(p, s) for p in AVAIL_PAT) and not re.search(r"not (be )?available|unavailable", s)
    if strong and avail:
        return "MIXED"
    if strong:
        return "OUT"
    if avail:                       # 'returned to action after a two-game absence' -> available
        return "AVAILABLE"
    if any(re.search(p, s) for p in WEAK_PAT):
        return "LIKELY_OUT"
    return None


def parse(text, teams, rosters, rnd=None):
    """teams: {code: full team name}; rosters: {code: [(player_id, 'SURNAME, FIRST'), ...]}
    Returns list of dicts: team, player_id, player, status, evidence."""
    lines = [l.strip(" -•\t") for l in text.splitlines() if l.strip()]
    # locate team sections by their names (first 2 significant words is enough, e.g. 'Anadolu Efes')
    keys = {c: ALIASES.get(c) or max(_tokens(n), key=len) for c, n in teams.items()}
    current, sections = None, {}
    for l in lines:
        nl = " ".join(_tokens(l))
        hit = ([] if " vs" in l.lower() or len(l) >= 60 or re.search(r"[.!?]$", l)
               else [c for c, k in keys.items() if k and k in nl])
        if hit:
            current = hit[0]
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(l)
    out = []
    for code, sents in sections.items():
        roster = rosters.get(code, [])
        seen = {}
        team_norep = False
        for para in sents:
            for sent in re.split(r"(?<=[.!?])\s+", para):
                st = classify(sent, rnd)
                if st == "NO_REPORT":
                    team_norep = True
                    continue
                if not st:
                    continue
                toks = set(_tokens(sent))
                for pid, name in roster:
                    sur = _tokens(name.split(",")[0])
                    if sur and all(t in toks for t in sur) and pid not in seen:
                        parts = re.split(r";|,| while | but | whereas ", sent)
                        idx = [j for j, c in enumerate(parts) if sur[-1] in _tokens(c)]
                        status = None
                        for c in (parts[idx[0]:] if idx else []):
                            cst = classify(c, rnd)
                            if cst not in (None, "NO_REPORT"):
                                status = cst
                                break
                        status = status or st
                        if status is None:
                            continue
                        if status == "MIXED":
                            status = "GTD"
                        seen[pid] = {"team": code, "player_id": pid, "player": name, "status": status,
                                     "evidence": sent.strip()[:200]}
        for pid, name in roster:
            if pid not in seen:
                seen[pid] = {"team": code, "player_id": pid, "player": name,
                             "status": "NO_REPORT" if team_norep else "UNLISTED", "evidence": ""}
        out.extend(seen.values())
    # teams with no section at all
    for code in teams:
        if code not in sections:
            out.extend({"team": code, "player_id": pid, "player": name, "status": "NO_SECTION", "evidence": ""}
                       for pid, name in rosters.get(code, []))
    return out


EH_FEED = "https://www.eurohoops.net/en/feed/?s=injury+report"


def eurohoops_reports(season, rnd):
    """All Eurohoops articles republishing the official report for this round (one per game day), oldest first.
    Returns [(date, url, text)]."""
    from email.utils import parsedate_to_datetime
    tag = f"{season}\u2013{str(season + 1)[2:]}"
    found = {}
    feeds = [EH_FEED, "https://www.eurohoops.net/en/euroleague/feed/"] + [f"{EH_FEED}&paged={p}" for p in (2, 3, 4)]
    for u in feeds:
        try:
            x = requests.get(u, headers=UA, timeout=30).content.decode("utf-8", "ignore")
        except requests.RequestException:
            continue
        for item in re.findall(r"<item>(.*?)</item>", x, re.S):
            link = re.search(r"<link>(.*?)</link>", item).group(1).strip()
            title = H.unescape(re.search(r"<title>(.*?)</title>", item, re.S).group(1))
            head = (title + " " + link).lower().replace("-", " ")
            if "injury report" not in head and "injury update" not in head:
                continue
            if not re.search(rf"\bround {rnd}\b", head):
                continue
            found[link] = parsedate_to_datetime(re.search(r"<pubDate>(.*?)</pubDate>", item).group(1))
    out = []
    for link, d in sorted(found.items(), key=lambda kv: kv[1]):
        if not (d.year == season and d.month >= 8 or d.year == season + 1 and d.month <= 7):
            continue                                  # published outside this season
        page = requests.get(link, headers=UA, timeout=30).content.decode("utf-8", "ignore")
        out.append((d, link, _strip(page)))
    return out


def merge(parsed_lists):
    """Newer articles override older ones, but 'not mentioned' never overrides a real status."""
    weak = {"UNLISTED", "NO_SECTION"}
    best = {}
    for lst in parsed_lists:
        for r in lst:
            k = (r["team"], r["player_id"])
            if r["status"] == "NO_SECTION" and k in best:
                continue
            if k not in best or r["status"] not in weak or best[k]["status"] in weak:
                if k in best and r["status"] == "NO_REPORT" and best[k]["status"] not in weak | {"NO_REPORT"}:
                    continue
                best[k] = r
    return list(best.values())


def get_availability(season, rnd, teams, rosters):
    """Fetch + parse. Returns (DataFrame, url). Empty frame if the report can't be found."""
    import pandas as pd
    import os
    local = f"/home/claude/runner/injury_text_round{rnd}.txt"      # report text saved by hand / by Claude
    if os.path.exists(local):
        return pd.DataFrame(parse(open(local).read(), teams, rosters, rnd)), local
    arts = eurohoops_reports(season, rnd)                               # primary: Eurohoops (readable by scripts)
    if arts:
        return pd.DataFrame(merge([parse(t, teams, rosters, rnd) for _, _, t in arts])), " | ".join(u for _, u, _ in arts)
    url, page = find_report_url(season, rnd)                             # official site (often bot-checked)
    text = None if not page or "Security Checkpoint" in page else article_text(page)
    if not text:
        return pd.DataFrame(columns=["team", "player_id", "player", "status", "evidence"]), None
    return pd.DataFrame(parse(text, teams, rosters, rnd)), url
