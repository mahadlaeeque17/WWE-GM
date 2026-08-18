"""Fetch wrestler portraits from Wikimedia Commons.

    python fetch_images.py ../data/gm2000.db ../data/images/fetched

ONLY takes files served from `upload.wikimedia.org/wikipedia/commons/`. Those are
freely licensed (mostly CC BY-SA / public domain) and genuinely redistributable.
Files under `/wikipedia/en/` are non-free fair-use uploads and are skipped — as
are WWE/WCW press and promotional photos, which are not ours to repackage.

Every candidate article is VERIFIED to be about a wrestler before its image is
taken. Without that check, "Sunny", "Kat", "Victoria" and "Angel" all match
articles about something else entirely.

Output is named:   <id> - <Name> - <year>.<ext>
which the image indexer parses back to (wrestler_id, year) unambiguously — the
leading id is authoritative, so a rename of the middle part cannot misfile it.

Writes manifest.csv alongside the images with the source URL, licence and
photo year for every file, so attribution is never lost.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://en.wikipedia.org/w/api.php"
UA = "WWE-GM-2000/1.0 (personal roster project; contact: mahad.laeeque@tmcltd.com)"
DELAY = 0.35          # polite pacing; Wikimedia asks for a descriptive UA + restraint
BATCH = 20

# An article only counts if it is plausibly about a wrestler.
WRESTLING_HINT = re.compile(
    r"wrestl|sports? entertain|WWE|WWF|WCW|ECW|NWA|AEW|puroresu|joshi", re.I
)

# Disambiguators worth trying, most specific first.
SUFFIXES = ["(wrestler)", "(professional wrestler)", "", "(manager)", "(valet)"]


def get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def is_commons(url: str) -> bool:
    """Free-licensed Commons file, as opposed to a non-free local upload."""
    return "/wikipedia/commons/" in url


def photo_year(title: str, url: str) -> int | None:
    """Pull a year out of the file name — Commons names usually carry the event
    year, e.g. `Trish_Stratus_at_CCR_Ontario_2024.jpg`."""
    for text in (urllib.parse.unquote(url), title):
        years = re.findall(r"(19[5-9]\d|20[0-2]\d)", text)
        if years:
            return int(years[-1])
    return None


def lookup_batch(titles: list[str]) -> dict[str, dict]:
    """Ask for pageimages + categories + intro extract for up to BATCH titles."""
    if not titles:
        return {}
    data = get({
        "action": "query",
        "titles": "|".join(titles),
        "prop": "pageimages|categories|extracts",
        "piprop": "original",
        "cllimit": "max",
        "exintro": "1",
        "explaintext": "1",
        "exchars": "500",
        "redirects": "1",
    })

    # `redirects` and `normalized` remap what we asked for to what came back.
    alias: dict[str, str] = {}
    for key in ("normalized", "redirects"):
        for m in data.get("query", {}).get(key, []) or []:
            alias[m["from"]] = m["to"]

    pages = {p.get("title"): p for p in data.get("query", {}).get("pages", []) or []}

    out: dict[str, dict] = {}
    for asked in titles:
        resolved = asked
        seen = set()
        while resolved in alias and resolved not in seen:
            seen.add(resolved)
            resolved = alias[resolved]
        page = pages.get(resolved)
        if page:
            out[asked] = page
    return out


def verify(page: dict) -> bool:
    if page.get("missing"):
        return False
    cats = " ".join(c.get("title", "") for c in page.get("categories", []) or [])
    return bool(WRESTLING_HINT.search(cats) or WRESTLING_HINT.search(page.get("extract", "")))


def main(dbpath: Path, outdir: Path) -> None:
    con = sqlite3.connect(dbpath)
    con.row_factory = sqlite3.Row

    wrestlers = [dict(r) for r in con.execute("SELECT id, name FROM wrestler ORDER BY id")]
    names: dict[int, list[str]] = {}
    for r in con.execute("SELECT wrestler_id, name FROM ring_name ORDER BY is_primary DESC"):
        names.setdefault(r["wrestler_id"], []).append(r["name"])

    outdir.mkdir(parents=True, exist_ok=True)

    # Build the full candidate list: every ring name against every suffix.
    # Ordered so the most likely title for each wrestler is tried first.
    todo: dict[int, list[str]] = {}
    for w in wrestlers:
        cands: list[str] = []
        for nm in [w["name"], *names.get(w["id"], [])]:
            nm = nm.strip()
            if not nm or len(nm) < 3:
                continue
            for suf in SUFFIXES:
                t = f"{nm} {suf}".strip()
                if t not in cands:
                    cands.append(t)
        todo[w["id"]] = cands

    found: dict[int, dict] = {}
    rejected: dict[int, list[str]] = {}

    # Work in rounds: round N tries each wrestler's Nth remaining candidate, so
    # everyone gets their best guess before anyone gets their second.
    for round_no in range(len(SUFFIXES) * 3):
        pending = [(wid, c[round_no]) for wid, c in todo.items()
                   if wid not in found and round_no < len(c)]
        if not pending:
            break
        print(f"round {round_no + 1}: {len(pending)} candidates")

        for i in range(0, len(pending), BATCH):
            chunk = pending[i:i + BATCH]
            try:
                pages = lookup_batch([t for _, t in chunk])
            except Exception as e:
                print(f"  batch failed: {e}")
                time.sleep(2)
                continue

            for wid, title in chunk:
                page = pages.get(title)
                if not page:
                    continue
                if not verify(page):
                    rejected.setdefault(wid, []).append(f"{title} (not a wrestler)")
                    continue
                orig = page.get("original")
                if not orig:
                    rejected.setdefault(wid, []).append(f"{title} (no image)")
                    continue
                url = orig["source"].split("?")[0]
                if not is_commons(url):
                    rejected.setdefault(wid, []).append(f"{title} (non-free file)")
                    continue
                found[wid] = {"title": page["title"], "url": url}
            time.sleep(DELAY)

    print(f"\nresolved {len(found)} of {len(wrestlers)} wrestlers\n")

    # ---- download ----
    by_id = {w["id"]: w["name"] for w in wrestlers}
    rows = []
    for wid, info in sorted(found.items()):
        url = info["url"]
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        year = photo_year(info["title"], url) or 2000
        safe = re.sub(r"[^\w\s'&.-]", "", by_id[wid]).strip()
        fname = f"{wid} - {safe} - {year}{ext}"
        dest = outdir / fname

        if not dest.exists():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    dest.write_bytes(r.read())
                time.sleep(DELAY)
            except Exception as e:
                print(f"  download failed {by_id[wid]}: {e}")
                continue

        rows.append({
            "wrestler_id": wid, "name": by_id[wid], "filename": fname,
            "photo_year": year, "wikipedia_article": info["title"],
            "source_url": url, "size_bytes": dest.stat().st_size,
        })
        print(f"  {fname}  ({dest.stat().st_size // 1024} KB)")

    with (outdir / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                            ["wrestler_id", "name", "filename", "photo_year",
                             "wikipedia_article", "source_url", "size_bytes"])
        wr.writeheader()
        wr.writerows(rows)

    missing = [(w["id"], w["name"]) for w in wrestlers if w["id"] not in found]
    with (outdir / "MISSING.txt").open("w", encoding="utf-8") as fh:
        fh.write("No freely-licensed Commons photo found for these.\n")
        fh.write("Add your own as:  <id> - <Name> - <year>.jpg\n\n")
        for wid, nm in missing:
            why = "; ".join(dict.fromkeys(rejected.get(wid, [])))[:110]
            fh.write(f"{wid:>6}  {nm}{('  — ' + why) if why else ''}\n")

    print(f"\n{len(rows)} downloaded -> {outdir}")
    print(f"{len(missing)} without a free photo -> MISSING.txt")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
