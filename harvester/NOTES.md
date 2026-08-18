# Harvest notes — data quirks and known gaps

Running log of things discovered during the harvest that affect how the data can
be trusted. Read this before writing any formula that consumes the dataset.

## Confirmed working

- **In-page `fetch()` is the only viable transport.** Sucuri WAF returns a
  bodyless `307` to curl / server-side fetch. Browser-context fetch inherits the
  challenge cookie.
- **Promotion IDs:** WWE `1`, WCW `2`, ECW `3`.
- **Worker page tabs** (`?id=2&nr=<id>&page=N`):
  `3` Career highlights · `11` Titles · `4` Matches · `20` Career · `22` Match statistics
- **Promotion page tabs** (`?id=8&nr=<pid>&page=N`):
  `9` Titles · `16` Roster · `17` Win/Loss records (accepts `&year=YYYY`)

## Traps

### The `promotion=` search filter is not usable for history
Only covers *active* promotions — WCW and ECW return zero rows and are absent
from the dropdown entirely. Even for WWE it reflects **current association**, not
career history: it returned 82 women while omitting Lita, Chyna, Ivory, Moolah
and Wendi Richter. Roster construction uses the promotion-year W/L sweep instead.

### Win/loss is a sample, not a ledger
Pre-2000 coverage is TV/PPV weighted; house shows largely absent. Store
`matches` alongside every record and weight confidence by it. Use win% as a
booking-strength signal, never as literal career history.

Concretely: Trish Stratus shows 4-27 for 2000. That is *directionally* true —
she debuted that March and lost constantly — but the absolute counts are low.

### Ratings need shrinkage
Many wrestlers here have <20 votes. `adj = (v*R + 25*6.0) / (v + 25)`.
Without it, Mariko Yoshida (9.25, 50 votes, one WCW match) outranks Trish.

### Titles have no dates in the worker `page=11` view — RESOLVED
That view gives title name, reign count and reign length, but **not when**.
For a year-2000 reset this matters enormously: Trish's seven Women's titles are
all post-2000, and counting them put her star_power at 86 in January 2000 — for
a wrestler who debuted that March and had never held a belt.

Career highlights (`page=3`) turned out to be editorial notes, not title data.
The real source is the **title database itself**: `?id=5&nr=<title_id>` with no
page param returns the full dated reign history —
`#N | champion(link) | (reign) | dd.mm.yyyy - dd.mm.yyyy (N days) | city`.

Only four titles matter for this era, so it is a 4-request pass:

| id | title |
|---|---|
| 18 | WWF/WWE Women's Championship |
| 656 | WWF World Women's Tag Team Championship |
| 929 | WCW World Women's Championship |
| 1417 | WCW World Women's Cruiserweight Championship |

ECW had no women's title — correctly returns none.

69 reigns total, 35 of them pre-2001. `star_power` now counts only reigns won
before `RESET_YEAR`; the full career list is still stored for the record books.
Trish correctly drops 86 -> 46, retaining her fame but not phantom championships.

**Reigning champion at the reset:** The Kat held the WWF Women's Championship on
1 January 2000 (won at Armageddon, December 1999). Seed the game with that.

### Stripping tags without a separator silently merges list fields
The alter-egos block is a stack of `<div>` entries. Stripping tags with
`replace(/<[^>]+>/g, '')` concatenates them into one blob —
`Amy DumasAngelicaLitaMiss Congeniality`. It looks like a single odd name rather
than a parse failure, which is exactly why it survived the first pass.

Replace tags with a separator, then split, then also split on ` a.k.a. `:

    html.replace(/<[^>]+>/g, '|').split('|').map(s=>s.trim()).filter(Boolean)
        .flatMap(s => s.split(/\s+a\.k\.a\.\s+/i))

Do not try to recover a merged blob by splitting on lowercase-to-uppercase
transitions — it destroys `McCool`, `DeVito`, `LeRoux`.

### Character-encoding artifacts
Birthplaces containing non-ASCII come back mangled (`S�dkorea`, `D�nemark`) —
the pages are ISO-8859-1 but decoded as UTF-8. Cosmetic, affects birthplace only.
Fix on normalize by re-decoding those fields as Latin-1.

### Gender mislabels in the source
`id 3295 Shinichi Nakano` is carried as female in cagematch but is a male
wrestler. Flag for review rather than silently dropping — there may be others.
Any wrestler with a single match and no rating deserves a look before she is
seeded into the game as a real roster member.

### One wrestler-year appears ONCE PER GIMMICK — sum, never replace
The promotion win/loss tables key on the gimmick, not the person. Sherri's 1987
appears twice: "Sensational Sherri" (44 matches) and "Sherri Martel" (2).

`INSERT OR REPLACE` on `(wrestler_id, promotion, year)` therefore keeps only the
last row and silently discards the others — it cost Sherri 176 of her 232 WWE
matches, and the DB still looked perfectly well-formed. Merge and sum before
insert (`load_per_year` in normalize.py).

Guard against regressions with the reconciliation check: per-year sums in the DB
must equal the aggregate totals in the roster JSON for every wrestler. It is
currently 0 mismatches across all 127.

### Name collisions
`Dawn Marie` exists twice under different ids (`493` ECW/WWE-era, `8063` a
distinct 1986-87 worker). Key on cagematch id, never on name.

## Roster shape as harvested

127 women with at least one WWE/WCW/ECW promotion-year in 1980-2000.
Composition skews as expected: a dense 1980s WWF jobber pool, a small mid-90s
Japanese import contingent, and the 1999-2000 Attitude-era cohort.


## Traps found while building the rankings (batch 4 era)

### `current_date` is a SQLite keyword — never SELECT it by name

`game_state.current_date` holds the in-game date. But `CURRENT_DATE` is a SQLite
built-in, so:

    SELECT current_date FROM game_state WHERE id=1     -- returns TODAY. No error.

It does not fail, it does not warn, it just quietly hands back the wall-clock
date. The first Power 25 issue published on a save sitting in January 2000 was
dated **2026-08-18**. The same bug was already live in `game.ai_monthly`, where
it gated the AI's quarterly trade offer on the real-world month.

Always `SELECT * FROM game_state WHERE id=1` and read the column off the row —
which is what every older call site happens to do, which is why it went unnoticed.

### A stale uvicorn will serve old code and look perfectly healthy

Documented in PLAN.md, hit again here: `pkill -f uvicorn` from Git Bash does not
reliably kill the Windows python process. Blurb changes appeared to do nothing
across two restarts because the original server still held port 8010. Kill by
port, not by name:

    Get-NetTCPConnection -LocalPort 8010 -State Listen |
      Select -Expand OwningProcess | Sort -Unique | ForEach { Stop-Process -Id $_ -Force }

A 200 from `/api/health` is not evidence your build is the one answering.

### Ring names are the only safe dedup key across roster batches

Batch 4 overlaps batches 1-3 by design. Matching on `wrestler.name` alone would
have re-added six women already on the roster under a different gimmick
(Angelina Love / Angel Williams, Velvet Sky / Talia Madison, Taylor Wilde /
Shantelle Taylor, Tara / Victoria, Alissa Flash / Cheerleader Melissa, Sarita /
Sarah Stock). Match on `wrestler.name` **plus every row in `ring_name`**, and
record known future gimmicks when inserting so the next batch can match on them.

### Editorial copy needs the movement, not the biggest fact

The Power 25 blurb generator originally led with whatever was most notable. A
wrestler who won a belt and then dropped four places was congratulated on
"catapulting" up the board. Every word was true and the line was still wrong.
Direction of travel picks the sentence; the facts fill it in.

### One branch of a generator will read as copy-paste

On a week where nobody wrestled, all 25 entries fall into the same "did not
work" branch and the board reads as one sentence repeated. Variants are keyed on
rank, not randomised, so re-opening an old issue never changes what it says.


## Deploy trap: root requirements.txt is REQUIRED, and also changes detection

Two facts that pull in opposite directions, which cost several failed deploys:

1. **Vercel only enables its Python runtime when a dependency manifest sits at
   the REPO ROOT.** Without one, `api/*.py` is not a Serverless Function at all
   and the build dies in about a second:

       Error: The pattern "api/index.py" defined in `functions` doesn't match
       any Serverless Functions inside the `api` directory.

   Putting the manifest in `api/` instead does NOT satisfy this.

2. **That same root manifest makes Vercel classify the project as a "backend
   framework project"** — the phrase is in its own build log — after which it
   routes every request through a backend adapter and stops serving the static
   build. Static assets like `/favicon.svg` come back as
   FUNCTION_INVOCATION_FAILED, which looks nothing like a configuration problem.

The resolution is NOT to delete the manifest. It is to keep it at the root and
turn the classification off where it actually lives: the project's **Framework
Preset → Other** in the dashboard, plus `"framework": null` in `vercel.json`.
The preset is decided when the repo is first imported and is stored in project
settings, so no commit can change it — if the repo was imported while the
detection was wrong, that setting stays wrong until someone flips it by hand.

### Two debugging lessons, both learned the slow way

**A stdlib-only probe separates "my code is wrong" from "the host is running
something else."** `api/diag.py` imports nothing but the standard library. When
it failed exactly like the real app, that ruled out every application-level
cause in one step.

**Check WHICH commit is deployed before believing anything you test.** Three
consecutive fixes appeared to do nothing because every one of them had failed to
build, and Vercel keeps serving the last good deployment when a build fails. The
dashboard marks it "Ready Stale" — easy to miss. The deployment list, showing
Error against each commit, was the fastest route to the truth and should have
been the first thing consulted, not the last.
