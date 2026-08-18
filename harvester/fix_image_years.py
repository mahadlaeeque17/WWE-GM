"""Re-label fetched portraits with their TRUE capture year.

The fetcher guesses a year from the Commons filename and falls back to 2000.
That is wrong for most photos — a lot of these are convention shots from the
2010s. Commons stores the real capture date in `DateTimeOriginal`, so this
rewrites the filenames and the manifest to match reality.

Idempotent: it derives each target name from (id, name, year) rather than
patching the existing string, so a partial run can simply be re-run.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "WWE-GM-2000/1.0 (personal roster project; mahad.laeeque@tmcltd.com)"
API = "https://en.wikipedia.org/w/api.php"


def commons_title(url: str) -> str:
    return "File:" + urllib.parse.unquote(url.rsplit("/", 1)[-1])


def capture_year(title: str, tries: int = 3) -> int | None:
    q = urllib.parse.urlencode({
        "action": "query", "titles": title, "prop": "imageinfo",
        "iiprop": "extmetadata", "format": "json", "formatversion": "2",
    })
    for attempt in range(tries):
        try:
            req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
            data = json.loads(urllib.request.urlopen(req, timeout=40).read().decode())
            for p in data.get("query", {}).get("pages", []):
                info = p.get("imageinfo")
                if not info:
                    return None
                meta = info[0].get("extmetadata", {})
                for key in ("DateTimeOriginal", "DateTime"):
                    raw = re.sub(r"<[^>]+>", "", str(meta.get(key, {}).get("value", "")))
                    m = re.search(r"(1[89]\d\d|20[0-2]\d)", raw)
                    if m:
                        return int(m.group(1))
            return None
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


def target_name(wid: str, name: str, year: int, ext: str) -> str:
    safe = re.sub(r"[^\w\s'&.-]", "", name).strip()
    return f"{wid} - {safe} - {year}{ext}"


def main(folder: Path) -> None:
    rows = list(csv.DictReader((folder / "manifest.csv").open(encoding="utf-8")))
    on_disk = {p.name: p for p in folder.iterdir() if p.suffix.lower() in
               (".jpg", ".jpeg", ".png", ".webp")}

    renamed = 0
    for r in rows:
        year = capture_year(commons_title(r["source_url"]))
        if year:
            r["photo_year"] = str(year)
        ext = Path(r["filename"]).suffix
        want = target_name(r["wrestler_id"], r["name"], int(r["photo_year"]), ext)

        current = on_disk.get(r["filename"])
        if current is None:
            # a previous partial run may already have renamed it
            current = on_disk.get(want)
        if current and current.name != want:
            current.rename(folder / want)
            renamed += 1
        r["filename"] = want
        time.sleep(0.25)

    rows.sort(key=lambda r: int(r["wrestler_id"]))
    with (folder / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{renamed} renamed, {len(rows)} in manifest")
    era = sum(1 for r in rows if int(r["photo_year"]) <= 2002)
    print(f"{era} are era-accurate (<=2002); {len(rows) - era} are modern photos")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
