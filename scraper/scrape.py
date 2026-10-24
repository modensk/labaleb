#!/usr/bin/env python3
"""Собирает составы 50 лиг с английской Википедии + данные с Викиданных.

Пишет:
  data/index.json            — список лиг и команд
  data/leagues/<id>.json     — составы команд лиги
  data/faces/<id>.json       — минифейсы (data: URI 96x96), только свободные фото
  data/report.json           — отчёт: что собралось, что нет
"""
import base64
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = "LabalebFootballDB/1.0 (https://github.com/modensk/labaleb; personal football game database)"
WP_API = "https://en.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip"})

REPORT = {"leagues": {}, "errors": []}


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- HTTP

def get_json(url, params, tries=5):
    params = dict(params)
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    params.setdefault("maxlag", "5")
    for i in range(tries):
        try:
            r = S.post(url, data=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            j = r.json()
            if "error" in j:
                if j["error"].get("code") == "maxlag":
                    time.sleep(5 + i * 5)
                    continue
                raise RuntimeError(j["error"])
            time.sleep(0.05)
            return j
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 + i * 3)
    return {}


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def norm_title(t):
    t = html.unescape(t or "").replace("_", " ").strip()
    t = t.split("#")[0].strip()
    if t:
        t = t[0].upper() + t[1:]
    return t


def resolve_map(q):
    """Карта исходный заголовок -> итоговый (после normalize и redirects)."""
    m = {}
    for n in q.get("normalized", []) or []:
        m[n["from"]] = n["to"]
    red = {r["from"]: r["to"] for r in q.get("redirects", []) or []}

    def res(t):
        t2 = m.get(t, t)
        seen = 0
        while t2 in red and seen < 5:
            t2 = red[t2]
            seen += 1
        return t2
    return res


def fetch_wikitexts(titles):
    """titles -> {orig_title: (final_title, wikitext)}"""
    out = {}
    for batch in chunks(titles, 10):
        j = get_json(WP_API, {
            "action": "query", "prop": "revisions|pageprops", "rvprop": "content",
            "rvslots": "main", "redirects": "1", "ppprop": "wikibase_item",
            "titles": "|".join(batch),
        })
        q = j.get("query", {})
        res = resolve_map(q)
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in batch:
            p = pages.get(res(t))
            if not p or p.get("missing"):
                continue
            revs = p.get("revisions") or []
            if not revs:
                continue
            text = revs[0]["slots"]["main"].get("content", "")
            out[t] = (p["title"], text, (p.get("pageprops") or {}).get("wikibase_item"))
    return out


def fetch_html(title):
    j = get_json(WP_API, {"action": "parse", "page": title, "prop": "text", "redirects": "1"})
    p = j.get("parse") or {}
    return p.get("title", title), p.get("text", "")


# ---------------------------------------------------------------- wikitext utils

def strip_noise(s):
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s, flags=re.S | re.I)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S | re.I)
    return s


def scan_templates(text):
    """Все шаблоны верхнего уровня: [(start, end, name, body)]."""
    res = []
    i, n = 0, len(text)
    while i < n:
        j = text.find("{{", i)
        if j < 0:
            break
        depth, k = 0, j
        while k < n:
            if text.startswith("{{", k):
                depth += 1
                k += 2
            elif text.startswith("}}", k):
                depth -= 1
                k += 2
                if depth == 0:
                    break
            else:
                k += 1
        body = text[j + 2:k - 2]
        name = re.split(r"[|\n]", body, 1)[0].strip()
        res.append((j, k, name, body))
        i = k
    return res


def split_params(body):
    parts, buf, d_sq, d_cu = [], [], 0, 0
    i = 0
    while i < len(body):
        c2 = body[i:i + 2]
        if c2 == "[[":
            d_sq += 1; buf.append(c2); i += 2; continue
        if c2 == "]]":
            d_sq = max(0, d_sq - 1); buf.append(c2); i += 2; continue
        if c2 == "{{":
            d_cu += 1; buf.append(c2); i += 2; continue
        if c2 == "}}":
            d_cu = max(0, d_cu - 1); buf.append(c2); i += 2; continue
        c = body[i]
        if c == "|" and d_sq == 0 and d_cu == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    named, pos = {}, []
    for p in parts[1:]:
        if "=" in p and not p.strip().startswith("[["):
            k, v = p.split("=", 1)
            named[k.strip().lower()] = v.strip()
        else:
            pos.append(p.strip())
    return named, pos


LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


def plain(s):
    s = strip_noise(s)
    s = LINK_RE.sub(lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def parse_name(v):
    v = strip_noise(v)
    m = re.search(r"\{\{\s*sortname\s*\|([^{}]*)\}\}", v, re.I)
    if m:
        named, pos = split_params("x|" + m.group(1))
        first = pos[0] if pos else ""
        last = pos[1] if len(pos) > 1 else ""
        disp = (first + " " + last).strip()
        nolink = "nolink" in named
        link = None if nolink else (pos[2] if len(pos) > 2 and pos[2] else disp)
        return disp, (norm_title(link) if link else None)
    m = LINK_RE.search(v)
    if m:
        target = norm_title(m.group(1))
        disp = plain(m.group(2) or m.group(1))
        if target.lower().startswith(("file:", "image:")):
            return plain(v), None
        return disp, target
    return plain(v), None


PLAYER_TPL = re.compile(r"^(fs2?|football squad)\s*player\s*\d?$", re.I)
SQUAD_START = re.compile(r"^(fs2?|football squad)\s*(start|begin)\d?$", re.I)
BAD_SECTION = re.compile(
    r"loan|youth|academy|reserve|\bii\b|\bb[ -]?team|\bu-?\d\d|under[- ]?\d\d|women|retired|former|notable|"
    r"records|staff|development|second team|out\b|other players|farm|futures|affiliate|\bteam b\b|famous|"
    r"captains|honours|historic|all-time|hall of fame|internationals|^in$|^out$|transfer|signing|departure|arrival|"
    r"incoming|outgoing|released|^in |^out ",
    re.I)
POS_MAP = {"GK": "GK", "DF": "DF", "MF": "MF", "FW": "FW", "G": "GK", "D": "DF", "M": "MF", "F": "FW",
           "FB": "DF", "CB": "DF", "DM": "MF", "AM": "MF", "ST": "FW", "CF": "FW", "WG": "FW"}


def parse_squad(wikitext):
    text = wikitext
    heads = [(m.start(), len(m.group(1)), plain(m.group(2)))
             for m in re.finditer(r"^(={2,6})\s*(.*?)\s*\1\s*$", text, re.M)]

    def heading_at(pos):
        h = None
        for hp, lvl, name in heads:
            if hp < pos:
                h = (hp, lvl, name)
            else:
                break
        return h

    blocks = []  # list of dicts {key, heading, players}
    starts_seen = 0
    for (a, b, name, body) in scan_templates(text):
        lname = name.lower().strip()
        if SQUAD_START.match(lname):
            starts_seen += 1
            continue
        if not PLAYER_TPL.match(lname):
            continue
        h = heading_at(a)
        key = (h[0] if h else -1, starts_seen)
        if not blocks or blocks[-1]["key"] != key:
            blocks.append({"key": key, "heading": h[2] if h else "", "pos": a, "players": []})
        named, _ = split_params(body)
        disp, link = parse_name(named.get("name", ""))
        if not disp:
            continue
        pos = POS_MAP.get(plain(named.get("pos", "")).upper().strip(), "")
        no = re.sub(r"\D", "", plain(named.get("no", "")))[:3]
        nat = plain(named.get("nat", "")).upper()[:12]
        other = plain(named.get("other", ""))
        cap = ""
        if re.search(r"captain", other, re.I):
            cap = "VC" if re.search(r"vice|deputy|third|3rd|second", other, re.I) else "C"
        loan = bool(re.search(r"on loan|loan from", other, re.I))
        blocks[-1]["players"].append({"n": disp, "w": link, "no": no, "pos": pos, "nat": nat,
                                       "cap": cap, "loan": loan})
    if not blocks:
        names = {}
        for (_, _, name, _) in scan_templates(text):
            k = name.lower().strip()[:40]
            names[k] = names.get(k, 0) + 1
        top = sorted(names.items(), key=lambda x: -x[1])[:8]
        hs = [h[2][:30] for h in heads][:25]
        return [], "no-player-templates " + json.dumps({"tpl": top, "heads": hs}, ensure_ascii=False)

    # Заголовок блока + текст перед ним (на случай "Out on loan" жирным без заголовка)
    def ok(bl, prev_end):
        if BAD_SECTION.search(bl["heading"] or ""):
            return False
        before = text[max(prev_end, bl["pos"] - 250):bl["pos"]]
        if bl["key"][1] > 1 and re.search(r"loan|reserve|youth|academy|under", plain(before), re.I):
            return False
        return True

    prev_end = 0
    for bl in blocks:
        if len(bl["players"]) >= 11 and ok(bl, prev_end):
            return bl["players"], "ok:" + (bl["heading"] or "-")
        prev_end = bl["pos"]
    big = max(blocks, key=lambda b: len(b["players"]))
    diag = [(b["heading"][:30], len(b["players"])) for b in blocks][:12]
    hs = [h[2][:30] for h in heads][:25]
    return big["players"], "fallback:" + (big["heading"] or "-") + " " + json.dumps({"blocks": diag, "heads": hs}, ensure_ascii=False)


def infobox_colors(wikitext):
    m = re.search(r"\|\s*body1\s*=\s*#?([0-9A-Fa-f]{6})", wikitext)
    m2 = re.search(r"\|\s*shorts1\s*=\s*#?([0-9A-Fa-f]{6})", wikitext)
    return ("#" + m.group(1).upper() if m else None, "#" + m2.group(1).upper() if m2 else None)


def find_current_season(wikitext):
    y = datetime.now(timezone.utc).year
    wikitext = re.sub(r"\{\{\s*CURRENTYEAR\s*\}\}", str(y), wikitext)
    m = re.search(r"\|\s*current\s*=\s*([^\n]*)", wikitext)
    if not m:
        return None
    lm = LINK_RE.search(m.group(1))
    return norm_title(lm.group(1)) if lm else None


# ---------------------------------------------------------------- teams from HTML tables

TEAM_COL = re.compile(r"^(club|clubs|team|teams|club name|team name|equipo|clube)$", re.I)
STADIUM_COL = re.compile(r"stadium|location|city|venue|ground|capacity|home|town|province|state|region", re.I)
TABLE_COL = re.compile(r"^(pld|pts|gp|p|mp)$", re.I)


def good_link(a):
    href = a.get("href", "")
    if not href.startswith("/wiki/"):
        return None
    t = a.get("title") or ""
    if not t or ":" in href[6:].split("#")[0]:
        return None
    if a.find_parent(class_=re.compile(r"flagicon|mw-file|reference")):
        return None
    if a.find_parent("sup"):
        return None
    if "(page does not exist)" in t:
        return None
    return norm_title(t), a.get_text(" ", strip=True)


def table_teams(table, mode):
    rows = table.find_all("tr")
    if not rows:
        return None
    header = None
    for r in rows[:3]:
        ths = r.find_all("th")
        if len(ths) >= 2 and not r.find("td"):
            header = [re.sub(r"\[.*?\]", "", th.get_text(" ", strip=True)).strip() for th in ths]
            break
    if not header:
        return None
    idx = next((i for i, h in enumerate(header) if TEAM_COL.match(h)), None)
    if idx is None:
        return None
    rest = " ".join(header)
    if mode == "stadium" and not STADIUM_COL.search(rest):
        return None
    if mode == "table" and not any(TABLE_COL.match(h) for h in header):
        return None
    teams = []
    for r in rows:
        cells = r.find_all(["td", "th"], recursive=False)
        if not cells or not r.find("td"):
            continue
        order = []
        if idx < len(cells):
            order.append(cells[idx])
        order += [c for c in cells if c not in order]
        cands = []
        for c in order:
            for a in c.find_all("a"):
                l = good_link(a)
                if l and l not in cands:
                    cands.append(l)
        if cands:
            teams.append(cands[:6])
    return teams


def teams_from_html(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    tables = soup.find_all("table", class_=re.compile("wikitable"))
    for mode in ("stadium", "table"):
        found = []
        for t in tables:
            tt = table_teams(t, mode)
            if not tt or len(tt) < 4:
                continue
            found += tt
        if len(found) >= 8:
            return found[:80], mode
    return [], None


# ---------------------------------------------------------------- per-player data

def player_meta(titles):
    """title -> {thumb, file, qid}"""
    out = {}
    for batch in chunks(sorted(set(titles)), 50):
        j = get_json(WP_API, {
            "action": "query", "prop": "pageimages|pageprops", "piprop": "thumbnail|name",
            "pithumbsize": "250", "pilicense": "free", "ppprop": "wikibase_item",
            "redirects": "1", "titles": "|".join(batch),
        })
        q = j.get("query", {})
        res = resolve_map(q)
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in batch:
            p = pages.get(res(t))
            if not p or p.get("missing"):
                continue
            out[t] = {
                "thumb": (p.get("thumbnail") or {}).get("source"),
                "file": p.get("pageimage"),
                "qid": (p.get("pageprops") or {}).get("wikibase_item"),
                "title": p["title"],
            }
    return out


def wikidata(qids):
    out = {}
    for batch in chunks(sorted(set(q for q in qids if q)), 50):
        j = get_json(WD_API, {"action": "wbgetentities", "ids": "|".join(batch),
                              "props": "labels|claims", "languages": "ru|en"})
        for qid, ent in (j.get("entities") or {}).items():
            cl = ent.get("claims") or {}
            d = {"ru": ((ent.get("labels") or {}).get("ru") or {}).get("value")}
            try:
                t = cl["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
                d["born"] = t[1:11]
            except Exception:  # noqa: BLE001
                pass
            try:
                v = cl["P2048"][0]["mainsnak"]["datavalue"]["value"]
                amt = float(v["amount"])
                unit = v.get("unit", "")
                if unit.endswith("Q11573"):
                    amt *= 100
                if 140 < amt < 230:
                    d["h"] = int(round(amt))
            except Exception:  # noqa: BLE001
                pass
            try:
                foot = cl["P552"][0]["mainsnak"]["datavalue"]["value"]["id"]
                d["foot"] = {"Q3029952": "R", "Q789447": "L", "Q3039938": "B"}.get(foot)
            except Exception:  # noqa: BLE001
                pass
            out[qid] = d
    return out


def file_licenses(files):
    out = {}
    for batch in chunks(sorted(set(f for f in files if f)), 50):
        j = get_json(WP_API, {"action": "query", "prop": "imageinfo", "iiprop": "extmetadata",
                              "iiextmetadatafilter": "Artist|LicenseShortName",
                              "titles": "|".join("File:" + f for f in batch)})
        q = j.get("query", {})
        res = resolve_map(q)
        pages = {p["title"]: p for p in q.get("pages", [])}
        for f in batch:
            p = pages.get(res("File:" + f)) or pages.get("File:" + f.replace("_", " "))
            if not p:
                continue
            ii = (p.get("imageinfo") or [{}])[0].get("extmetadata") or {}
            lic = plain(ii.get("LicenseShortName", {}).get("value", ""))
            art = BeautifulSoup(ii.get("Artist", {}).get("value", ""), "html.parser").get_text(" ", strip=True)
            out[f] = (lic + (" · " + art[:60] if art else "")).strip(" ·")
    return out


def make_face(url):
    for i in range(4):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 429:
                time.sleep(5 + i * 10)
                continue
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content))
            im = im.convert("RGB")
            w, h = im.size
            if h > w:
                side = w
                top = int(min(h * 0.04, h - side))
                box = (0, top, w, top + side)
            else:
                side = h
                left = (w - h) // 2
                box = (left, 0, left + side, h)
            im = im.crop(box).resize((96, 96), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=72, optimize=True, progressive=True)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:  # noqa: BLE001
            time.sleep(2 + i * 3)
    return None


# ---------------------------------------------------------------- main per league

def pid(league, team, p):
    key = p["w"] or f'{league}/{team}/{p["n"]}'
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def tid(title):
    return hashlib.sha1(title.encode()).hexdigest()[:8]


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def scrape_league(lg):
    rep = {"wiki": lg["wiki"]}
    REPORT["leagues"][lg["id"]] = rep
    log(f"\n=== {lg['id']} {lg['wiki']}")
    main = fetch_wikitexts([lg["wiki"]]).get(lg["wiki"])
    if not main:
        rep["error"] = "league page not found"
        return None
    season = find_current_season(main[1])
    y = datetime.now(timezone.utc).year
    guesses = ([season] if season else []) + [
        f"{y}–{str(y + 1)[2:]} {main[0]}", f"{y} {main[0]}", f"{y} {main[0]} season", f"{y - 1}–{str(y)[2:]} {main[0]}"]
    rows, mode = [], None
    for g in guesses:
        try:
            ft, h = fetch_html(g)
        except Exception:  # noqa: BLE001
            continue
        rows, mode = teams_from_html(h)
        if len(rows) >= 8:
            season = ft
            break
    if len(rows) < 8:
        _, h = fetch_html(main[0])
        rows, mode = teams_from_html(h)
        rep["teams_from"] = "league-page"
    rep["season"] = season
    rep["teams_mode"] = mode
    if not rows:
        rep["error"] = "no teams"
        return None

    # Каждая строка таблицы — несколько ссылок; клуб = первая, у которой есть «Infobox football club»
    cand_titles = sorted({t for row in rows for t, _ in row})
    texts = fetch_wikitexts(cand_titles)
    teams, seen_final = [], set()
    for row in rows:
        for title, label in row:
            got = texts.get(title)
            if got and re.search(r"\{\{\s*Infobox\s+(association\s+)?(football|soccer)\s+club", got[1], re.I):
                if got[0] not in seen_final:
                    seen_final.add(got[0])
                    teams.append((title, label, got))
                break
    teams = teams[:40]
    rep["teams_found"] = len(teams)
    log(f"  season={season} teams={len(teams)} mode={mode}")
    if not teams:
        rep["error"] = "no club pages"
        return None

    out_teams, all_players = [], []
    rep["teams"] = {}
    for title, label, got in teams:
        final, wt, qid = got
        players, how = parse_squad(wt)
        rep["teams"][final] = f"{how} n={len(players)}"
        c1, c2 = infobox_colors(wt)
        team = {"id": tid(final), "name": label or final, "wiki": final, "qid": qid,
                "c1": c1, "c2": c2, "players": []}
        seen = set()
        for p in players:
            k = p["w"] or p["n"]
            if k in seen:
                continue
            seen.add(k)
            p["id"] = pid(lg["id"], final, p)
            team["players"].append(p)
            all_players.append(p)
        out_teams.append(team)

    # Метаданные игроков
    titles = [p["w"] for p in all_players if p["w"]]
    meta = player_meta(titles)
    wd = wikidata([m["qid"] for m in meta.values()] + [t["qid"] for t in out_teams])
    for t in out_teams:
        ru = (wd.get(t["qid"]) or {}).get("ru")
        if ru:
            t["ru"] = ru
        t.pop("qid", None)

    old_faces = load_json(os.path.join(DATA, "faces", lg["id"] + ".json"), {})
    old_src = load_json(os.path.join(DATA, "faces", lg["id"] + ".src.json"), {})
    want = {}
    for p in all_players:
        m = meta.get(p["w"]) if p["w"] else None
        if m:
            d = wd.get(m["qid"]) or {}
            for k in ("born", "h", "foot", "ru"):
                if d.get(k):
                    p[k] = d[k]
            if m["thumb"] and m["file"]:
                want[p["id"]] = (m["thumb"], m["file"])
        if not p["w"]:
            p.pop("w")
        if not p["cap"]:
            p.pop("cap")
        if not p["loan"]:
            p.pop("loan")

    lic = file_licenses([f for _, f in want.values()])
    faces, src, todo = {}, {}, []
    for pid_, (url, f) in want.items():
        if old_src.get(pid_) == f and pid_ in old_faces:
            faces[pid_] = old_faces[pid_]
            src[pid_] = f
        else:
            todo.append((pid_, url, f))
    log(f"  players={len(all_players)} faces: reuse={len(faces)} download={len(todo)}")

    def job(x):
        pid_, url, f = x
        return pid_, f, make_face(url)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for pid_, f, data in ex.map(job, todo):
            if data:
                faces[pid_] = data
                src[pid_] = f
    for t in out_teams:
        for p in t["players"]:
            if p["id"] in faces:
                p["face"] = 1
                f = src[p["id"]]
                if lic.get(f):
                    p["lic"] = lic[f]

    rep.update({"teams_ok": sum(1 for t in out_teams if len(t["players"]) >= 11),
                "players": len(all_players), "faces": len(faces)})
    os.makedirs(os.path.join(DATA, "leagues"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "faces"), exist_ok=True)
    league_obj = {"id": lg["id"], "season": season, "teams": out_teams}
    with open(os.path.join(DATA, "leagues", lg["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(league_obj, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DATA, "faces", lg["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(faces, f, separators=(",", ":"))
    with open(os.path.join(DATA, "faces", lg["id"] + ".src.json"), "w", encoding="utf-8") as f:
        json.dump(src, f, ensure_ascii=False, separators=(",", ":"))
    return league_obj


def main():
    leagues = load_json(os.path.join(ROOT, "scraper", "leagues.json"), [])
    only = [x.strip() for x in os.environ.get("LEAGUES", "").split(",") if x.strip()]
    os.makedirs(DATA, exist_ok=True)
    index_path = os.path.join(DATA, "index.json")
    index = load_json(index_path, {"leagues": []})
    by_id = {l["id"]: l for l in index.get("leagues", [])}
    rep_old = load_json(os.path.join(DATA, "report.json"), {})
    if only:
        REPORT["leagues"].update({k: v for k, v in (rep_old.get("leagues") or {}).items() if k not in only})

    for lg in leagues:
        if only and lg["id"] not in only:
            continue
        try:
            obj = scrape_league(lg)
        except Exception as e:  # noqa: BLE001
            REPORT["errors"].append(f"{lg['id']}: {e!r}")
            REPORT["leagues"].setdefault(lg["id"], {})["error"] = repr(e)[:300]
            traceback.print_exc()
            obj = None
        if obj:
            by_id[lg["id"]] = {
                **{k: lg[k] for k in ("id", "name", "country", "flag", "region")},
                "season": obj["season"],
                "teams": [{"id": t["id"], "name": t["name"], "ru": t.get("ru"), "c1": t["c1"], "c2": t["c2"],
                           "n": len(t["players"])} for t in obj["teams"]],
            }

    search = []
    for l in leagues:
        lo = load_json(os.path.join(DATA, "leagues", l["id"] + ".json"), None)
        if not lo:
            continue
        for t in lo["teams"]:
            for p in t["players"]:
                search.append([p["id"], p["n"], p.get("ru") or "", l["id"], t["id"], p.get("pos", "")])
    with open(os.path.join(DATA, "search.json"), "w", encoding="utf-8") as f:
        json.dump(search, f, ensure_ascii=False, separators=(",", ":"))

    order = [l["id"] for l in leagues]
    index = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
             "source": "Wikipedia / Wikidata (CC BY-SA)",
             "leagues": [by_id[i] for i in order if i in by_id]}
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    REPORT["generated"] = index["generated"]
    REPORT["totals"] = {
        "leagues": len(index["leagues"]),
        "teams": sum(len(l["teams"]) for l in index["leagues"]),
        "players": sum(t["n"] for l in index["leagues"] for t in l["teams"]),
    }
    with open(os.path.join(DATA, "report.json"), "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1)
    log("\nTOTALS", REPORT["totals"])


if __name__ == "__main__":
    sys.exit(main())
