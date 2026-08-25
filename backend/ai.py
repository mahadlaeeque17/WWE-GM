"""Phase 5 — the Groq AI layer.

The creative partner. Groq writes everything that is *narrative*: match
commentary, promos, feud pitches, show recaps, and the rival GM's card. It
reads sim state but it **never decides a match outcome** — the deterministic
sim in sim.py owns that, so a failed or slow API call can never corrupt a save
or make results irreproducible. Every AI surface degrades gracefully: if the
key is missing or Groq is unreachable, the endpoint returns a clean 503 and the
game plays on exactly as before.

Talks to Groq's OpenAI-compatible REST API directly over httpx — no SDK
dependency, which also keeps the serverless (Vercel) build small. The model IDs
are NOT hardcoded from memory: we query /models once and pick a strong model for
reasoning and a fast one for bulk, per the project brief.
"""

from __future__ import annotations

import json
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # dotenv is optional; env vars may be set another way
    pass

GROQ_BASE = "https://api.groq.com/openai/v1"
TIMEOUT = 30.0


class AIUnavailable(RuntimeError):
    """Raised when Groq is not configured or not reachable. Callers turn this
    into a 503 — never a 500 — because the AI layer is always optional."""


def api_key() -> str | None:
    return os.environ.get("GROQ_API_KEY") or None


def available() -> tuple[bool, str]:
    if not api_key():
        return False, "GROQ_API_KEY is not set — add it to backend/.env"
    return True, "ready"


def _headers() -> dict:
    key = api_key()
    if not key:
        raise AIUnavailable("GROQ_API_KEY is not set — add it to backend/.env")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


# ---------------------------------------------------------------- model choice

# Only text chat models are useful here; skip audio/vision/moderation families.
_SKIP = ("whisper", "tts", "guard", "embed", "vision", "prompt-guard", "allam",
         "orpheus", "canopylabs")


@lru_cache(maxsize=1)
def _models() -> list[str]:
    """Live chat models on the account, best-effort. Cached for the process."""
    try:
        r = httpx.get(f"{GROQ_BASE}/models", headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
        return [m for m in ids if not any(s in m.lower() for s in _SKIP)]
    except Exception as e:  # noqa: BLE001
        raise AIUnavailable(f"could not list Groq models: {e}") from e


def _rank(model: str, strong: bool) -> tuple:
    """Heuristic ranking so we don't hardcode a model id that may be retired.

    Strong = reasoning (feud logic, rival booking): favour big/versatile models.
    Fast   = bulk (per-match commentary): favour small/instant models.
    """
    m = model.lower()
    big = any(t in m for t in ("70b", "120b", "versatile", "large", "maverick"))
    small = any(t in m for t in ("8b", "instant", "mini", "scout"))
    if strong:
        return (big, "llama" in m, model)
    return (small, "llama" in m, model)


def pick_model(strong: bool = False) -> str:
    models = _models()
    if not models:
        raise AIUnavailable("no chat models available on this Groq account")
    return sorted(models, key=lambda m: _rank(m, strong), reverse=True)[0]


def models_info() -> dict:
    ok, why = available()
    if not ok:
        return {"ready": False, "detail": why}
    try:
        return {"ready": True, "models": _models(),
                "strong": pick_model(True), "fast": pick_model(False)}
    except AIUnavailable as e:
        return {"ready": False, "detail": str(e)}


# ---------------------------------------------------------------- chat

def _chat(messages: list[dict], *, strong: bool = False, model: str | None = None,
          temperature: float = 0.85, max_tokens: int = 500,
          json_mode: bool = False) -> str:
    body: dict = {
        "model": model or pick_model(strong),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(f"{GROQ_BASE}/chat/completions", headers=_headers(),
                       json=body, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:300] if e.response is not None else str(e)
        raise AIUnavailable(f"Groq API error {e.response.status_code}: {detail}") from e
    except Exception as e:  # noqa: BLE001
        raise AIUnavailable(f"Groq request failed: {e}") from e


VOICE = (
    "You are the creative team for WWE GM 2000, an alternate-universe women's "
    "wrestling promotion that resets the world to January 2000. Two brands, Raw "
    "(red) and SmackDown (blue). Write in the confident, kayfabe voice of "
    "turn-of-the-millennium wrestling television — vivid but tight, never "
    "cheesy. Use only the wrestlers and facts you are given. Never invent match "
    "results; the booking is already decided."
)


# ---------------------------------------------------------------- DB context

def _name(con: sqlite3.Connection, wid: int) -> str:
    r = con.execute(
        """SELECT COALESCE(o.display_name, w.name) n FROM wrestler w
           LEFT JOIN attribute_override o ON o.wrestler_id=w.id WHERE w.id=?""",
        (wid,)).fetchone()
    return r["n"] if r else f"#{wid}"


def _match_line(con: sqlite3.Connection, m: sqlite3.Row) -> dict:
    parts = con.execute(
        """SELECT p.wrestler_id, p.team, p.is_winner, w.name
           FROM sim_match_participant p JOIN wrestler w ON w.id=p.wrestler_id
           WHERE p.match_id=? ORDER BY p.team""", (m["id"],)).fetchall()
    teams: dict[int, list[str]] = {}
    winners: list[str] = []
    for p in parts:
        teams.setdefault(p["team"], []).append(p["name"])
        if p["is_winner"]:
            winners.append(p["name"])
    title = None
    if m["title_id"]:
        t = con.execute("SELECT name FROM game_title WHERE id=?", (m["title_id"],)).fetchone()
        title = t["name"] if t else None
    return {
        "sides": [" & ".join(v) for v in teams.values()],
        "winners": winners, "finish": m["finish"],
        "quality": m["quality"], "title": title,
    }


# ---------------------------------------------------------------- surfaces

def match_commentary(con: sqlite3.Connection, match_id: int, persist: bool = True) -> dict:
    """Two or three lines of colour commentary calling the finish of one match."""
    m = con.execute("SELECT * FROM sim_match WHERE id=?", (match_id,)).fetchone()
    if not m:
        raise AIUnavailable("no such match")
    ml = _match_line(con, m)
    title = f" for the {ml['title']}" if ml["title"] else ""
    winners = ", ".join(ml["winners"]) or "nobody (a draw)"
    prompt = (
        f"Call this match{title}: {' vs '.join(ml['sides'])}. "
        f"Winner: {winners}, by {ml['finish']}. Match quality {ml['quality']}/100. "
        "Give 2–3 sentences of TV commentary that fit that result and quality "
        "(a low score is a scrappy or flat match, a high score a barnburner). "
        "Do not contradict the winner or finish. Output ONLY the commentary — "
        "no score line, no notes, no quotation marks."
    )
    text = _chat([{"role": "system", "content": VOICE},
                  {"role": "user", "content": prompt}],
                 strong=False, temperature=0.9, max_tokens=180)
    if persist:
        con.execute("UPDATE sim_match SET narrative=? WHERE id=?", (text, match_id))
        con.commit()
    return {"match_id": match_id, "narrative": text}


def show_recap(con: sqlite3.Connection, show_id: int) -> dict:
    """A short broadcast recap of a whole show."""
    show = con.execute("SELECT * FROM show WHERE id=?", (show_id,)).fetchone()
    if not show:
        raise AIUnavailable("no such show")
    matches = con.execute("SELECT * FROM sim_match WHERE show_id=? ORDER BY slot", (show_id,)).fetchall()
    lines = []
    for m in matches:
        ml = _match_line(con, m)
        w = ", ".join(ml["winners"]) or "draw"
        belt = f" ({ml['title']})" if ml["title"] else ""
        lines.append(f"- {' vs '.join(ml['sides'])}{belt} → {w} ({ml['finish']}, {ml['quality']}/100)")
    prompt = (
        f"Show: {show['name']} (rated {show['rating']}/100, {show['attendance']} in attendance).\n"
        f"Card, opener first, main event last:\n" + "\n".join(lines) +
        "\n\nWrite a punchy 4–6 sentence recap for the website: the story of the "
        "night, the main event, and one thing to watch next. Do not change any result."
    )
    text = _chat([{"role": "system", "content": VOICE},
                  {"role": "user", "content": prompt}],
                 strong=True, temperature=0.85, max_tokens=380)
    return {"show_id": show_id, "recap": text}


def promo(con: sqlite3.Connection, wrestler_id: int, target_id: int | None = None,
          topic: str | None = None) -> dict:
    """A promo cut by one wrestler, optionally aimed at a rival."""
    name = _name(con, wrestler_id)
    eff = con.execute(
        # Popularity, not charisma: promo skill is one of its three
        # components now, so it is where "can she talk" lives.
        """SELECT COALESCE(o.popularity,a.popularity) cha, w.style
           FROM wrestler w JOIN attributes a ON a.wrestler_id=w.id
           LEFT JOIN attribute_override o ON o.wrestler_id=w.id WHERE w.id=?""",
        (wrestler_id,)).fetchone()
    reign = con.execute(
        """SELECT t.name FROM game_title_reign r JOIN game_title t ON t.id=r.title_id
           WHERE r.wrestler_id=? AND r.lost_on IS NULL LIMIT 1""", (wrestler_id,)).fetchone()
    bits = [f"{name} is cutting a promo."]
    if reign:
        bits.append(f"She is the current {reign['name']}.")
    if eff and eff["style"]:
        bits.append(f"Her style is {eff['style']}.")
    if target_id:
        bits.append(f"It is aimed at {_name(con, target_id)}.")
    if topic:
        bits.append(f"Topic: {topic}.")
    prompt = " ".join(bits) + (
        " Write it in first person, 4–6 lines, in her voice — sharp, quotable, "
        "in kayfabe. No stage directions."
    )
    text = _chat([{"role": "system", "content": VOICE},
                  {"role": "user", "content": prompt}],
                 strong=False, temperature=1.0, max_tokens=300)
    return {"wrestler_id": wrestler_id, "promo": text}


def storyline(con: sqlite3.Connection, brand_id: str) -> dict:
    """A feud/storyline pitch built from the brand's actual roster and titles."""
    season = con.execute("SELECT season_year FROM game_state WHERE id=1").fetchone()
    season = season["season_year"] if season else 2000
    roster = con.execute(
        """SELECT w.name,
                  COALESCE(o.popularity,a.popularity)*2 heat,
                  COALESCE(s.momentum,50) momentum
           FROM contract c
           JOIN wrestler w ON w.id=c.wrestler_id
           JOIN attributes a ON a.wrestler_id=w.id
           LEFT JOIN attribute_override o ON o.wrestler_id=w.id
           LEFT JOIN wrestler_state s ON s.wrestler_id=w.id
           WHERE c.brand_id=? AND c.terminated_on IS NULL
             AND c.start_year<=? AND c.end_year>=?
           ORDER BY heat DESC LIMIT 12""", (brand_id, season, season)).fetchall()
    if len(roster) < 2:
        raise AIUnavailable(f"{brand_id} needs at least two wrestlers under contract")
    who = "; ".join(f"{r['name']} (heat {r['heat']}, momentum {r['momentum']})" for r in roster)
    title = con.execute("SELECT name FROM game_title WHERE brand_id=?", (brand_id,)).fetchone()
    belt = title["name"] if title else "the brand's top prize"
    prompt = (
        f"Brand: {brand_id}. Roster: {who}. Top prize: {belt}.\n"
        "Pitch ONE compelling feud for the next month of television: who, the "
        "hook, 3 beats building week to week, and the blow-off match. 6–9 lines. "
        "Use only these wrestlers."
    )
    text = _chat([{"role": "system", "content": VOICE},
                  {"role": "user", "content": prompt}],
                 strong=True, temperature=0.9, max_tokens=450)
    return {"brand_id": brand_id, "storyline": text}


def negotiation_line(name: str, verdict: str, mood: str, salary: int,
                     perks: list[str]) -> str:
    """One in-character line reacting to a contract offer. Falls back to a canned
    line if Groq is unavailable — negotiation never depends on the AI."""
    canned = {
        "thrilled": f"{name}: Now THAT'S how you treat a star. Where do I sign?",
        "satisfied": f"{name}: That works for me. Let's do business.",
        "negotiating": f"{name}: We're close. Sweeten it and I'm yours.",
        "unimpressed": f"{name}: That's it? I'm worth a lot more than that.",
        "insulted": f"{name}: You've got some nerve. That number is an insult.",
        "done": f"{name}: We're done here. Don't call again.",
    }
    fallback = canned.get(mood, canned["negotiating"])
    if not api_key():
        return fallback
    perk_txt = f" Perks on the table: {', '.join(perks)}." if perks else ""
    prompt = (
        f"{name} just received a contract offer of ${salary:,}/yr.{perk_txt} "
        f"Her reaction is '{mood}' ({verdict}). Write ONE short first-person line "
        "in her voice reacting to the offer — quotable, in kayfabe, no more than "
        "25 words. Output only the line."
    )
    try:
        return _chat([{"role": "system", "content": VOICE},
                      {"role": "user", "content": prompt}],
                     strong=False, temperature=1.0, max_tokens=70)
    except AIUnavailable:
        return fallback


def scouting_report(con: sqlite3.Connection, wid: int) -> dict:
    """A Groq nickname + short career blurb, grounded in the wrestler's real
    cagematch data (rating, votes, promotions, era, titles, alter-egos)."""
    w = con.execute(
        """SELECT COALESCE(o.display_name, w.name) name, w.name canonical,
                  w.rating, w.votes, w.style, w.career_start, w.career_end
           FROM wrestler w LEFT JOIN attribute_override o ON o.wrestler_id=w.id
           WHERE w.id=?""", (wid,)).fetchone()
    if not w:
        raise AIUnavailable("no such wrestler")
    promos = [r[0] for r in con.execute(
        "SELECT DISTINCT promotion FROM promotion_year WHERE wrestler_id=?", (wid,))]
    akas = [r[0] for r in con.execute(
        "SELECT name FROM ring_name WHERE wrestler_id=? ORDER BY is_primary DESC", (wid,))]
    titles = con.execute(
        "SELECT COUNT(*) FROM title_reign WHERE wrestler_id=?", (wid,)).fetchone()[0]

    facts = (
        f"Name: {w['name']}. Cagematch rating: {w['rating'] or 'unrated'} "
        f"from {w['votes'] or 0} fan votes. Style: {w['style'] or 'unlisted'}. "
        f"Worked: {', '.join(promos) or 'unknown'}. "
        f"Career: {w['career_start'] or '?'}–{w['career_end'] or 'present'}. "
        f"Recorded title reigns: {titles}. "
        f"Also known as: {', '.join(a for a in akas if a != w['name']) or 'n/a'}."
    )
    prompt = (
        "From these real facts, write a scouting blurb for this women's wrestler "
        "as she'd be pitched in early 2000. Reflect what her rating and fan votes "
        "say about how she was reviewed (high rating + many votes = beloved worker; "
        "low/few = unproven or niche). Then invent ONE fitting ring nickname.\n\n"
        f"{facts}\n\n"
        'Reply as JSON: {"nickname": "...", "report": "2-3 sentences"}.'
    )
    raw = _chat([{"role": "system", "content": VOICE},
                 {"role": "user", "content": prompt}],
                strong=True, temperature=0.9, max_tokens=260, json_mode=True)
    import json
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"nickname": None, "report": raw}
    return {"wrestler_id": wid, "nickname": data.get("nickname"),
            "report": data.get("report", ""), "also_known_as": [a for a in akas if a != w["name"]]}


def rival_booking(con: sqlite3.Connection, brand_id: str, matches: int = 4) -> dict:
    """The rival GM books a card — matchups only. Outcomes stay with the sim.

    Returns {card, reasoning}. `card` is in the exact shape /api/sim/show wants:
    [{"teams": [[id],[id]], "title_id": id|None}]. Every wrestler is validated
    against the healthy roster, and anyone the model omits or invents is dropped,
    so a hallucinated name can never reach the simulator.
    """
    season = con.execute("SELECT season_year, game_state.current_date FROM game_state WHERE id=1").fetchone()
    if not season:
        raise AIUnavailable("no active save")
    sy, today = season["season_year"], season["current_date"]
    roster = con.execute(
        """SELECT w.id, w.name, w.style,
                  COALESCE(o.wrestling,a.wrestling)+COALESCE(o.popularity,a.popularity)
                    +COALESCE(o.looks,a.looks)+COALESCE(o.personal,a.personal) ovr,
                  COALESCE(s.momentum,50) momentum, COALESCE(s.morale,50) morale
           FROM contract c
           JOIN wrestler w ON w.id=c.wrestler_id
           JOIN attributes a ON a.wrestler_id=w.id
           LEFT JOIN attribute_override o ON o.wrestler_id=w.id
           LEFT JOIN wrestler_state s ON s.wrestler_id=w.id
           WHERE c.brand_id=? AND c.terminated_on IS NULL
             AND c.start_year<=? AND c.end_year>=?
             AND (s.injured_until IS NULL OR s.injured_until <= ?)""",
        (brand_id, sy, sy, today)).fetchall()
    if len(roster) < 2:
        raise AIUnavailable(f"{brand_id} needs at least two healthy wrestlers")

    by_id = {r["id"]: dict(r) for r in roster}
    listing = "; ".join(f"[{r['id']}] {r['name']} (ovr {r['ovr']}, style {r['style'] or 'n/a'}, "
                        f"mom {r['momentum']}, mrl {r['morale']})" for r in roster)
    title = con.execute("SELECT id, name FROM game_title WHERE brand_id=?", (brand_id,)).fetchone()
    tinfo = f"Brand title: id {title['id']} = {title['name']}." if title else "No brand title."
    prompt = (
        f"You are the rival GM booking {matches} matches for {brand_id}.\n"
        f"Available wrestlers (id in brackets): {listing}\n{tinfo}\n"
        "Book a card that makes sense: competitive matchups, style pairings that "
        "click, hot wrestlers featured, the strongest match LAST as the main "
        "event and the brand title on it. Each wrestler appears at most once.\n"
        'Reply as JSON: {"reasoning": "one sentence", "card": [{"a": id, "b": id, '
        '"title": id or null}, ...]} — opener first, main event last. '
        "Do NOT decide winners."
    )
    raw = _chat([{"role": "system", "content": VOICE},
                 {"role": "user", "content": prompt}],
                strong=True, temperature=0.7, max_tokens=600, json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise AIUnavailable("rival GM returned unparseable JSON")

    card, used = [], set()
    for m in data.get("card", []):
        a, b = m.get("a"), m.get("b")
        if a in by_id and b in by_id and a != b and a not in used and b not in used:
            tid = m.get("title")
            tid = tid if (title and tid == title["id"]) else None
            card.append({"teams": [[a], [b]], "title_id": tid})
            used.update({a, b})
    if not card:
        raise AIUnavailable("rival GM did not produce a usable card")
    return {"brand_id": brand_id, "reasoning": data.get("reasoning", ""),
            "card": card,
            "card_readable": [f"{by_id[m['teams'][0][0]]['name']} vs "
                              f"{by_id[m['teams'][1][0]]['name']}"
                              f"{' (title)' if m['title_id'] else ''}" for m in card]}
