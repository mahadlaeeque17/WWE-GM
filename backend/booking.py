"""Show production: match stipulations, arena/production logistics, and the
money loop. Spend on the card and the building to draw a bigger house; a strong
show grows your fanbase, which raises next week's budget.

No AI here and no copyrighted content — just numbers.
"""
from __future__ import annotations

import sqlite3

import game

# key -> label, cost, quality bonus, whether it is no-disqualification
STIPULATIONS = {
    "normal":       {"label": "Normal",              "cost": 0,      "quality": 0, "no_dq": False},
    "submission":   {"label": "Submission",          "cost": 3_000,  "quality": 3, "no_dq": False},
    "no_dq":        {"label": "No Disqualification",  "cost": 5_000,  "quality": 4, "no_dq": True},
    "tables":       {"label": "Tables",              "cost": 6_000,  "quality": 4, "no_dq": True},
    "hardcore":     {"label": "Hardcore",            "cost": 7_000,  "quality": 5, "no_dq": True},
    "steel_cage":   {"label": "Steel Cage",          "cost": 12_000, "quality": 6, "no_dq": True},
    "ladder":       {"label": "Ladder",              "cost": 11_000, "quality": 6, "no_dq": True},
    "last_standing":{"label": "Last Woman Standing", "cost": 10_000, "quality": 6, "no_dq": True},
    "extreme":      {"label": "Extreme Rules",       "cost": 9_000,  "quality": 6, "no_dq": True},
    "tlc":          {"label": "TLC",                 "cost": 16_000, "quality": 8, "no_dq": True},
    "iron_woman":   {"label": "Iron Woman",          "cost": 14_000, "quality": 7, "no_dq": False},
}

ARENAS = [
    {"key": "gym",     "label": "High School Gym", "cost": 0,      "capacity": 2_500,  "ticket": 25, "att_mult": 1.0},
    {"key": "local",   "label": "Local Arena",     "cost": 8_000,  "capacity": 8_000,  "ticket": 40, "att_mult": 1.25},
    {"key": "city",    "label": "City Arena",      "cost": 25_000, "capacity": 18_000, "ticket": 60, "att_mult": 1.6},
    {"key": "stadium", "label": "Stadium",         "cost": 60_000, "capacity": 55_000, "ticket": 90, "att_mult": 2.2},
]
PRODUCTION = [
    {"key": "none",  "label": "No Crew",         "cost": 0,      "quality": 0},
    {"key": "basic", "label": "Stage Crew",      "cost": 15_000, "quality": 3},
    {"key": "full",  "label": "Full Production",  "cost": 35_000, "quality": 6},
]
EFFECTS = [
    {"key": "none",  "label": "No Effects",             "cost": 0,      "quality": 0, "att_mult": 1.0},
    {"key": "basic", "label": "Lights, Effects & Pyro", "cost": 10_000, "quality": 3, "att_mult": 1.05},
    {"key": "full",  "label": "Full Pyro Spectacle",    "cost": 28_000, "quality": 6, "att_mult": 1.12},
]
ADVERTISING = [
    {"key": "none",     "label": "None",           "cost": 0,      "att_mult": 1.0,  "fan_growth": 0},
    {"key": "local",    "label": "Local Signs",    "cost": 8_000,  "att_mult": 1.12, "fan_growth": 8_000},
    {"key": "regional", "label": "Regional Ads",   "cost": 20_000, "att_mult": 1.3,  "fan_growth": 25_000},
    {"key": "national", "label": "National Push",  "cost": 45_000, "att_mult": 1.55, "fan_growth": 70_000},
]

CITIES = ["Raleigh, NC", "Chicago, IL", "Dallas, TX", "Boston, MA", "Denver, CO",
          "Atlanta, GA", "Seattle, WA", "Phoenix, AZ", "Nashville, TN", "Detroit, MI",
          "Miami, FL", "Minneapolis, MN", "Philadelphia, PA", "St. Louis, MO"]

FANBASE_DEFAULT = 800_000
STIPEND_RATE = 0.11        # weekly budget as a share of the fanbase


def _tier(options: list[dict], key: str | None) -> dict:
    return next((o for o in options if o["key"] == key), options[0])


def catalogue() -> dict:
    return {"stipulations": [{"key": k, **v} for k, v in STIPULATIONS.items()],
            "arenas": ARENAS, "production": PRODUCTION, "effects": EFFECTS, "advertising": ADVERTISING}


def logistics_summary(logistics: dict | None) -> dict:
    logistics = logistics or {}
    a = _tier(ARENAS, logistics.get("arena", "gym"))
    p = _tier(PRODUCTION, logistics.get("production", "none"))
    e = _tier(EFFECTS, logistics.get("effects", "none"))
    ad = _tier(ADVERTISING, logistics.get("advertising", "none"))
    return {
        "cost": a["cost"] + p["cost"] + e["cost"] + ad["cost"],
        "quality": p["quality"] + e["quality"],
        "att_mult": a["att_mult"] * e["att_mult"] * ad["att_mult"],
        "capacity": a["capacity"], "ticket": a["ticket"],
        "fan_growth": ad["fan_growth"],
        "tiers": {"arena": a, "production": p, "effects": e, "advertising": ad},
    }


def stip(key: str | None) -> dict:
    return STIPULATIONS.get(key or "normal", STIPULATIONS["normal"])


def match_cost(card: list[dict]) -> int:
    return sum(stip(m.get("stipulation"))["cost"] for m in card)


def show_cost(card: list[dict], logistics: dict | None) -> int:
    return match_cost(card) + logistics_summary(logistics)["cost"]


def fanbase(con: sqlite3.Connection, brand: str) -> int:
    return int(game.get_setting(con, f"fanbase:{brand}", str(FANBASE_DEFAULT)))


def set_fanbase(con: sqlite3.Connection, brand: str, value: int) -> None:
    game.set_setting(con, f"fanbase:{brand}", str(max(0, int(value))))


def stipend(con: sqlite3.Connection, brand: str) -> int:
    return int(fanbase(con, brand) * STIPEND_RATE)


def brand_cash(con: sqlite3.Connection, brand: str) -> int:
    r = con.execute("SELECT balance FROM brand_cash WHERE brand_id=?", (brand,)).fetchone()
    return r[0] if r else 0


def _proj_quality(con: sqlite3.Connection, card: list[dict], logistics: dict | None) -> float:
    if not card:
        return 0.0
    ls = logistics_summary(logistics)
    ach = game.achievement_inputs(con)
    total = 0.0
    for i, m in enumerate(card):
        wids = [w for t in m["teams"] for w in t]
        ovs = [game.effective_attributes(con, w, ach.get(w))["overall"]
               for w in wids] or [40]
        q = sum(ovs) / len(ovs) * 0.7 + stip(m.get("stipulation"))["quality"] + ls["quality"]
        if i == len(card) - 1:
            q += 4        # main event
        total += q
    return max(0.0, min(100.0, total / len(card)))


def _attendance(fb: int, quality: float, ls: dict) -> int:
    turnout = 0.012 * max(0.3, quality / 60.0) * ls["att_mult"]
    return int(min(ls["capacity"], fb * turnout))


def preview(con: sqlite3.Connection, brand: str, card: list[dict], logistics: dict | None) -> dict:
    ls = logistics_summary(logistics)
    fb = fanbase(con, brand)
    q = _proj_quality(con, card, logistics)
    att = _attendance(fb, q, ls)
    gate = att * ls["ticket"]
    cost = show_cost(card, logistics)
    budget = brand_cash(con, brand) + stipend(con, brand)
    return {"fans": fb, "attendance": att, "gate": gate, "cost": cost,
            "budget": budget, "stipend": stipend(con, brand),
            "proj_quality": round(q, 1), "affordable": cost <= budget,
            "capacity": ls["capacity"]}


def settle(con: sqlite3.Connection, brand: str, card: list[dict], logistics: dict | None,
           rating: float) -> dict:
    """After the sim runs: bank the week, grow the fanbase, return the ledger."""
    ls = logistics_summary(logistics)
    fb = fanbase(con, brand)
    att = _attendance(fb, rating, ls)
    gate = att * ls["ticket"]
    cost = show_cost(card, logistics)
    stip_income = stipend(con, brand)
    net = stip_income + gate - cost
    con.execute(
        "INSERT INTO brand_cash (brand_id, balance) VALUES (?,?) "
        "ON CONFLICT(brand_id) DO UPDATE SET balance = balance + ?",
        (brand, net, net))
    # Fanbase grows with a strong show and paid advertising; a stinker sheds fans.
    growth = int((rating - 55) * 1_500 + ls["fan_growth"])
    set_fanbase(con, brand, fb + growth)
    return {"attendance": att, "gate": gate, "cost": cost, "stipend": stip_income,
            "net": net, "fan_change": growth, "fanbase": fb + growth}
