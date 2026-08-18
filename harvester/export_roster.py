"""Human-readable roster export.

    python export_roster.py ../data/gm2000.db ../data/roster.md

Produces the browsable list: ring names, promotions and tenures, win/loss,
cagematch rating, championships, and derived game attributes.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import attributes as A

GROUP_TITLE = {
    "active_2000": "Active at the reset (January 2000)",
    "legend": "Legends and free agents",
    "import": "International import pool",
}


def main(dbpath: Path, out: Path) -> None:
    con = sqlite3.connect(dbpath)
    con.row_factory = sqlite3.Row

    lines: list[str] = [
        "# Women's roster — WWF / WCW / ECW, 1980-2000",
        "",
        "Harvested from cagematch.net. Win/loss is a TV/PPV-weighted **sample**, not a",
        "complete career ledger — see `harvester/NOTES.md`. `adj` is the vote-count-",
        "shrunk rating; `STAR` counts only championships won before 2000.",
        "",
    ]

    for avail in ("active_2000", "legend", "import"):
        rows = con.execute(
            """SELECT w.*, a.workrate, a.charisma, a.popularity, a.durability,
                      a.star_power, a.availability
               FROM wrestler w JOIN attributes a ON a.wrestler_id = w.id
               WHERE a.availability = ?
               ORDER BY COALESCE(w.votes,0) DESC""",
            (avail,),
        ).fetchall()

        lines.append(f"\n## {GROUP_TITLE[avail]} ({len(rows)})\n")

        for w in rows:
            names = [
                r[0] for r in con.execute(
                    "SELECT name FROM ring_name WHERE wrestler_id=? ORDER BY is_primary DESC",
                    (w["id"],),
                )
            ]
            promos = con.execute(
                "SELECT promotion, year, matches, wins, losses, draws FROM promotion_year WHERE wrestler_id=?",
                (w["id"],),
            ).fetchall()
            reigns = con.execute(
                "SELECT title, won_on, days FROM title_reign WHERE wrestler_id=? ORDER BY won_on",
                (w["id"],),
            ).fetchall()

            wins = sum(p["wins"] for p in promos)
            losses = sum(p["losses"] for p in promos)
            draws = sum(p["draws"] for p in promos)
            matches = sum(p["matches"] for p in promos)

            lines.append(f"### {w['name']}")
            if len(names) > 1:
                lines.append(f"- **Ring names:** {', '.join(dict.fromkeys(names))}")
            if w["birthday"]:
                lines.append(f"- **Born:** {w['birthday']}" + (f" — {w['birthplace']}" if w["birthplace"] else ""))
            if w["career_start"]:
                span = w["career_start"] + (f" to {w['career_end']}" if w["career_end"] else " to present")
                lines.append(f"- **Career:** {span}" + (f" · {w['style']}" if w["style"] else ""))

            tenure = ", ".join(f"{p['promotion']} ({p['year']})" for p in promos)
            lines.append(f"- **Promotions:** {tenure}")
            lines.append(f"- **Record:** {wins}-{losses}-{draws} across {matches} recorded matches")

            if w["rating"]:
                lines.append(
                    f"- **Cagematch:** {w['rating']} from {w['votes']} votes "
                    f"(adjusted {w['adj_rating']:.2f})"
                )
            else:
                lines.append("- **Cagematch:** unrated")

            if reigns:
                lines.append("- **Championships:**")
                for r in reigns:
                    when = f" — won {r['won_on']}" if r["won_on"] else ""
                    days = f", {r['days']} days" if r["days"] else ""
                    lines.append(f"  - {r['title']}{when}{days}")

            lines.append(
                f"- **Attributes:** workrate {w['workrate']} · charisma {w['charisma']} · "
                f"popularity {w['popularity']} · durability {w['durability']} · star {w['star_power']}"
            )
            lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
