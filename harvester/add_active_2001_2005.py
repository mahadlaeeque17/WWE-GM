"""Bulk-add women who were ACTIVE anywhere in 2001-2005 across WWE, WCW, ECW,
TNA, ROH, WOW, SHIMMER, the joshi promotions (AJW/GAEA/JWP/ARSION/NEO) and the
CMLL/AAA lucha scene. (NJPW had no women's division then; SHINE/Stardom did not
yet exist; AEW is 2019.)

Draft class here is just a starting bucket to balance the pools — you reassign
any wrestler's class/year in-app. The script skips anyone already on the roster
and anyone in banned_wrestler (recovered by name from the raw harvest), and uses
synthetic ids from 900101 up so nothing can collide with a real cagematch id.

Bios are original one-line summaries written by hand (not copied from anywhere)
plus real ring nicknames where one is well established.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "gm2000.db"
RAW = ROOT / "data" / "raw" / "roster_1980_2000.json"
NOW = datetime.now(timezone.utc).isoformat()
BASE_ID = 900_101

# (name, birth_year, class, role, cha, pop, looks, personality, style, weight, promo, year, nickname, bio)
W = [
    # ---- WOW: Women of Wrestling (2000-2001 TV) + last WCW/ECW women ----
    ("Beth Phoenix", 1980, 2001, "wrestler", 17, 15, 20, "ambitious", "Powerhouse", 68, "WWE", 2001, "The Glamazon", "Powerful, athletic wrestler who broke in on the northeast indies and became a multi-time WWE Women's Champion and Hall of Famer."),
    ("April Hunter", 1976, 2001, "both", 13, 12, 20, "prima_donna", "Powerhouse", 66, "ECW", 2001, None, "Statuesque, well-traveled wrestler and valet who worked ECW, the US indies and promotions around the world."),
    ("Elektra", 1975, 2001, "both", 12, 11, 20, "prima_donna", "Brawler", 57, "ECW", 2001, None, "Provocative valet and occasional wrestler of ECW's final years."),
    ("Chastity", 1977, 2001, "both", 11, 10, 17, "loyal", "Brawler", 60, "ECW", 2001, None, "ECW valet tied to Raven's Flock at the turn of the 2000s."),
    ("Jasmin St. Claire", 1972, 2001, "both", 12, 12, 18, "money_hungry", "Brawler", 55, "ECW", 2001, None, "Notorious personality and valet who managed and occasionally wrestled in ECW's dying days."),
    ("Midajah", 1975, 2001, "both", 12, 11, 18, "loyal", "Allrounder", 58, "WCW", 2001, None, "WCW valet best known as one of Scott Steiner's on-screen 'Freaks.'"),
    ("Terri Gold", 1974, 2001, "wrestler", 13, 12, 18, "prima_donna", "Allrounder", 60, "WOW", 2001, None, "Character-driven star and champion of the WOW: Women of Wrestling television promotion."),
    ("Jungle Grrrl", 1972, 2001, "wrestler", 13, 12, 17, "ambitious", "Powerhouse", 66, "WOW", 2001, None, "Athletic, jungle-themed headliner of WOW: Women of Wrestling."),
    ("Lana Star", 1968, 2001, "both", 12, 11, 18, "prima_donna", "Allrounder", 57, "WOW", 2001, None, "Glamorous, vain heel of WOW: Women of Wrestling."),
    ("Riot", 1978, 2001, "wrestler", 11, 10, 15, "money_hungry", "Brawler", 63, "WOW", 2001, None, "Punk-styled brawler on the WOW: Women of Wrestling roster."),
    ("Loca", 1979, 2001, "wrestler", 11, 10, 15, "loyal", "Brawler", 60, "WOW", 2001, None, "Street-tough character wrestler from WOW: Women of Wrestling."),
    ("Poison", 1980, 2001, "wrestler", 11, 10, 16, "prima_donna", "Allrounder", 58, "WOW", 2001, None, "Villainous member of the WOW: Women of Wrestling roster."),
    ("Caliente", 1981, 2001, "wrestler", 11, 11, 17, "ambitious", "High Flyer", 55, "WOW", 2001, None, "Energetic fan-favorite of WOW: Women of Wrestling."),
    ("Patti Pizzazz", 1970, 2001, "wrestler", 11, 10, 15, "loyal", "Brawler", 62, "WOW", 2001, None, "Veteran presence on the WOW: Women of Wrestling roster."),
    ("Bronco Billie", 1971, 2001, "wrestler", 11, 10, 14, "loyal", "Brawler", 68, "WOW", 2001, None, "Cowgirl-gimmick brawler from WOW: Women of Wrestling."),
    ("Delta Lotta Pain", 1976, 2001, "wrestler", 10, 10, 14, "money_hungry", "Powerhouse", 80, "WOW", 2001, None, "Imposing powerhouse character of WOW: Women of Wrestling."),

    # ---- TNA / ROH founding women + early-2000s US/Euro indie ----
    ("SoCal Val", 1983, 2002, "both", 13, 12, 19, "loyal", "Allrounder", 54, "TNA", 2002, None, "Valet, manager and on-screen personality across TNA through the 2000s."),
    ("Desire", 1980, 2002, "both", 12, 11, 19, "prima_donna", "Allrounder", 55, "TNA", 2002, None, "Early TNA valet of the promotion's weekly pay-per-view era."),
    ("Lollipop", 1981, 2002, "both", 12, 11, 20, "prima_donna", "Allrounder", 52, "TNA", 2002, None, "Dancer and valet featured in TNA's founding years."),
    ("Miss Joni", 1980, 2002, "both", 11, 10, 18, "loyal", "Allrounder", 55, "TNA", 2002, None, "On-screen woman from TNA's first national shows in 2002."),
    ("Teresa Tyler", 1979, 2002, "wrestler", 11, 10, 16, "ambitious", "Allrounder", 60, "TNA", 2002, None, "Wrestler featured on TNA's earliest 2002 cards."),
    ("Sumie Sakai", 1972, 2002, "wrestler", 15, 12, 15, "ambitious", "High Flyer", 57, "ROH", 2002, None, "Well-traveled joshi and US-indie veteran who wrestled in ROH's first women's match."),
    ("Simply Luscious", 1979, 2002, "both", 13, 11, 17, "prima_donna", "Allrounder", 60, "ROH", 2002, None, "Manager and wrestler central to early ROH women's storylines."),
    ("MsChif", 1979, 2002, "wrestler", 14, 12, 15, "prima_donna", "Brawler", 57, "ROH", 2002, "The Obsession", "Contortionist indie standout known for her green mist and blood-curdling scream."),
    ("Rain", 1982, 2002, "wrestler", 14, 12, 18, "money_hungry", "Brawler", 57, "SHIMMER", 2002, None, "Hard-edged indie wrestler and mainstay of the mid-2000s women's scene."),
    ("Ariel", 1981, 2002, "both", 13, 12, 18, "prima_donna", "Brawler", 57, "ROH", 2002, None, "Gothic valet and wrestler who worked ROH and the US indies as Shelly Martinez."),
    ("Rebecca Knox", 1987, 2002, "wrestler", 17, 13, 19, "ambitious", "Technician", 57, "ROH", 2002, None, "Irish technician who dazzled the European and US indies in the mid-2000s before global fame as Becky Lynch."),
    ("Talia Madison", 1981, 2002, "wrestler", 16, 14, 21, "prima_donna", "Allrounder", 54, "TNA", 2002, None, "Charismatic indie and TNA star who became a founding face of the Knockouts' most popular tag team."),
    ("Angel Williams", 1981, 2002, "wrestler", 15, 13, 21, "prima_donna", "Allrounder", 55, "TNA", 2002, None, "Canadian wrestler who worked the indies and TNA, later leader of The Beautiful People."),
    ("Bobcat", 1974, 2002, "both", 11, 10, 16, "money_hungry", "Brawler", 63, "TNA", 2002, None, "Tough valet and wrestler on the early US independents and TNA."),

    # ---- Joshi (AJW / GAEA / JWP / ARSION / NEO / OZ Academy) active 2001-2005 ----
    ("Nanae Takahashi", 1978, 2003, "wrestler", 16, 13, 16, "money_hungry", "Powerhouse", 65, "AJW", 2003, None, "Hard-hitting joshi ace who became a pillar of the 2000s Japanese women's scene and later co-founded a major promotion."),
    ("Ayumi Kurihara", 1985, 2003, "wrestler", 15, 12, 17, "ambitious", "Technician", 55, "NEO", 2003, None, "Crisp, athletic joshi technician admired across the mid-2000s Japanese scene."),
    ("Kana", 1981, 2003, "wrestler", 18, 15, 18, "money_hungry", "Technician", 60, "AJW", 2003, "The Empress", "Fierce striker who wrestled the Japanese indies as Kana before an undefeated WWE run as Asuka."),
    ("Yumiko Hotta", 1967, 2003, "wrestler", 14, 12, 14, "money_hungry", "Powerhouse", 66, "AJW", 2003, None, "Stiff-striking joshi veteran and multi-time champion of AJW's later years."),
    ("Takako Inoue", 1972, 2003, "wrestler", 14, 13, 18, "prima_donna", "Allrounder", 60, "AJW", 2003, None, "Glamorous, versatile AJW star of the 1990s-2000s."),
    ("Kaoru Ito", 1974, 2003, "wrestler", 13, 12, 14, "ambitious", "Powerhouse", 66, "AJW", 2003, None, "Rugged, dependable joshi wrestler of AJW's golden and twilight eras."),
    ("Momoe Nakanishi", 1979, 2003, "wrestler", 15, 12, 16, "ambitious", "High Flyer", 55, "AJW", 2003, None, "Small, spectacular high-flyer regarded as one of the best joshi of her generation."),
    ("Etsuko Mita", 1969, 2003, "wrestler", 13, 12, 14, "money_hungry", "Powerhouse", 66, "AJW", 2003, None, "Half of Las Cachorras Orientales, a punishing joshi tag specialist."),
    ("Mima Shimoda", 1970, 2003, "wrestler", 13, 12, 15, "money_hungry", "Brawler", 60, "AJW", 2003, None, "The other half of Las Cachorras Orientales, a cunning joshi veteran and brawler."),
    ("Toshiyo Yamada", 1969, 2003, "wrestler", 13, 12, 15, "loyal", "Technician", 61, "AJW", 2003, None, "Kick-heavy AJW standout of the early-1990s boom who wrestled into the 2000s."),
    ("Command Bolshoi", 1971, 2003, "wrestler", 13, 11, 14, "loyal", "High Flyer", 55, "JWP", 2003, None, "Masked JWP ace and trainer, a technically gifted joshi mainstay."),
    ("Carlos Amano", 1976, 2003, "wrestler", 12, 11, 15, "ambitious", "Technician", 55, "GAEA", 2003, None, "Reliable GAEA and indie joshi technician of the 2000s."),
    ("Ran Yu-Yu", 1978, 2003, "wrestler", 13, 11, 17, "prima_donna", "Allrounder", 57, "GAEA", 2003, None, "Athletic GAEA and Oz Academy joshi wrestler of the 2000s."),
    ("Chikayo Nagashima", 1975, 2003, "wrestler", 13, 11, 15, "loyal", "Technician", 55, "GAEA", 2003, None, "Long-serving GAEA joshi wrestler and one of Chigusa Nagayo's proteges."),
    ("KAORU", 1969, 2003, "wrestler", 13, 11, 15, "prima_donna", "High Flyer", 57, "GAEA", 2003, None, "Veteran high-flying joshi and hardcore competitor across AJW, GAEA and Oz Academy."),
    ("Azumi Hyuga", 1978, 2003, "wrestler", 13, 11, 16, "ambitious", "High Flyer", 55, "JWP", 2003, None, "JWP ace and champion, a durable joshi headliner of the early 2000s."),
    ("Tsubasa Kuragaki", 1978, 2003, "wrestler", 12, 10, 14, "loyal", "Powerhouse", 66, "JWP", 2003, None, "Powerful JWP joshi known for feats of strength."),
    ("Yoshiko Tamura", 1975, 2003, "wrestler", 13, 12, 16, "ambitious", "Allrounder", 58, "NEO", 2003, None, "Well-rounded NEO joshi star and champion of the 2000s."),
    ("Michiko Ohmukai", 1977, 2003, "both", 12, 11, 18, "prima_donna", "Brawler", 57, "ARSION", 2003, None, "Flashy ARSION joshi wrestler of the late-1990s and 2000s."),
    ("Ayako Sato", 1981, 2003, "wrestler", 12, 10, 15, "loyal", "Technician", 55, "NEO", 2003, None, "Technically sound joshi journeywoman of the 2000s Japanese scene."),
    ("Kayoko Haruyama", 1978, 2003, "wrestler", 12, 10, 15, "ambitious", "Powerhouse", 63, "JWP", 2003, None, "Sturdy JWP joshi wrestler and tag specialist."),
    ("Fuka", 1976, 2003, "both", 12, 11, 18, "prima_donna", "Allrounder", 55, "ARSION", 2003, None, "ARSION wrestler and manager who later ran her own joshi ventures."),
    ("GAMI", 1971, 2003, "both", 12, 11, 15, "money_hungry", "Brawler", 58, "ARSION", 2003, None, "Outspoken joshi veteran, promoter and wrestler across ARSION and the indies."),
    ("Fang Suzuki", 1970, 2003, "wrestler", 11, 10, 13, "money_hungry", "Powerhouse", 78, "LLPW", 2003, None, "Monster-styled joshi heavyweight of Japan's 1990s-2000s scene."),

    # ---- Lucha (CMLL / AAA) active 2001-2005 ----
    ("Lady Apache", 1972, 2004, "wrestler", 14, 12, 15, "money_hungry", "Brawler", 60, "AAA", 2004, None, "Rugged veteran luchadora and multi-time champion in CMLL and AAA."),
    ("Faby Apache", 1982, 2004, "wrestler", 15, 13, 18, "ambitious", "Technician", 58, "AAA", 2004, None, "Second-generation luchadora and one of the most decorated women in AAA history."),
    ("Mari Apache", 1980, 2004, "wrestler", 13, 11, 16, "loyal", "Brawler", 60, "AAA", 2004, None, "Hard-nosed member of the Apache wrestling family in AAA."),
    ("Marcela", 1978, 2004, "wrestler", 14, 12, 16, "loyal", "Technician", 57, "CMLL", 2004, None, "Technically sound CMLL mainstay and record-setting women's champion."),
    ("Martha Villalobos", 1968, 2004, "wrestler", 12, 11, 13, "money_hungry", "Powerhouse", 78, "AAA", 2004, None, "Imposing ruda (villain) and veteran of Mexican women's lucha libre."),
    ("Tiffany", 1974, 2004, "both", 12, 11, 18, "prima_donna", "Allrounder", 57, "AAA", 2004, None, "Glamorous exotica and valet of the AAA lucha scene."),
    ("Princesa Sujei", 1979, 2004, "wrestler", 12, 10, 15, "loyal", "High Flyer", 55, "IWRG", 2004, None, "Mexican luchadora and women's champion of the 2000s indies."),
    ("La Diabolica", 1975, 2004, "wrestler", 12, 10, 14, "money_hungry", "Brawler", 60, "AAA", 2004, None, "Fearsome ruda of Mexican women's lucha libre."),
    ("Xochitl Hamada", 1968, 2004, "wrestler", 13, 11, 15, "loyal", "High Flyer", 55, "AAA", 2004, None, "Japanese-Mexican luchadora of the Hamada wrestling dynasty."),
    ("Rossy Moreno", 1966, 2004, "wrestler", 12, 11, 15, "loyal", "Technician", 57, "CMLL", 2004, None, "Veteran luchadora, trainer and matriarch of the Moreno family."),
    ("Esther Moreno", 1967, 2004, "wrestler", 12, 11, 16, "loyal", "High Flyer", 55, "CMLL", 2004, None, "High-flying member of the Moreno lucha family."),
    ("La Amapola", 1979, 2004, "wrestler", 13, 11, 14, "money_hungry", "Brawler", 58, "CMLL", 2004, None, "Ruthless CMLL ruda and women's champion of the 2000s."),
    ("Hiroka", 1982, 2004, "wrestler", 12, 10, 15, "prima_donna", "Technician", 55, "AAA", 2004, None, "Japanese-trained luchadora who became an AAA women's standout."),

    # ---- WWE Diva Search era + more indies (spread) ----
    ("Amy Weber", 1970, 2004, "both", 11, 12, 20, "prima_donna", "Allrounder", 55, "WWE", 2004, None, "Model and 2004 Diva Search finalist who briefly valeted on SmackDown."),
    ("Carmella DeCesare", 1982, 2004, "both", 10, 12, 21, "prima_donna", "Allrounder", 54, "WWE", 2004, None, "Playboy cover model and 2004 Diva Search winner who made sporadic WWE appearances."),
    ("Jetta", 1983, 2004, "wrestler", 13, 11, 15, "money_hungry", "Brawler", 57, "SHIMMER", 2004, None, "Brash British wrestler and heel who worked the UK and US indies."),
    ("Saraya Knight", 1971, 2004, "wrestler", 15, 12, 14, "money_hungry", "Brawler", 60, "SHIMMER", 2004, None, "Ferocious British veteran and matriarch of the Knight wrestling family."),
    ("Wesna", 1980, 2004, "wrestler", 13, 11, 15, "ambitious", "Brawler", 60, "SHIMMER", 2004, None, "Hard-hitting European wrestler who competed across the international indies."),
    ("Christie Ricci", 1979, 2004, "wrestler", 12, 11, 17, "loyal", "Allrounder", 57, "NWA", 2004, None, "Southern-indie and NWA women's champion of the 2000s."),
    ("Portia Perez", 1988, 2004, "wrestler", 13, 11, 15, "money_hungry", "Technician", 52, "SHIMMER", 2004, None, "Cocky Canadian technician who became a SHIMMER regular."),

    # ---- SHIMMER 2005 inaugural remainder + WWE 2005 + misc ----
    ("Tiana Ringer", 1982, 2005, "wrestler", 12, 11, 17, "loyal", "Technician", 57, "SHIMMER", 2005, None, "Canadian wrestler who competed on SHIMMER's earliest volumes."),
    ("Shantelle Taylor", 1983, 2005, "wrestler", 12, 11, 17, "ambitious", "Allrounder", 58, "SHIMMER", 2005, None, "Athletic Canadian wrestler on the inaugural SHIMMER roster."),
    ("Amber O'Neal", 1979, 2005, "both", 12, 11, 19, "prima_donna", "Allrounder", 55, "SHIMMER", 2005, None, "Southern-belle valet and wrestler of the 2000s US indies."),
    ("Krissy Vaine", 1982, 2005, "both", 12, 11, 19, "prima_donna", "Allrounder", 55, "SHIMMER", 2005, None, "Blonde heel and valet who worked the indies and briefly WWE developmental."),
    ("Cindy Rogers", 1976, 2005, "wrestler", 12, 10, 15, "loyal", "Technician", 55, "SHIMMER", 2005, None, "Technically sound northeast-indie veteran and SHIMMER competitor."),
    ("Jillian Hall", 1980, 2005, "both", 15, 14, 20, "prima_donna", "Allrounder", 55, "WWE", 2005, None, "Southern-belle character with a tune-carrying gimmick who wrestled across WWE's brands."),
    ("Leyla Milani", 1982, 2005, "both", 10, 12, 21, "prima_donna", "Allrounder", 54, "WWE", 2005, None, "Model and 2005 Diva Search finalist."),
    ("Kristal Marshall", 1983, 2005, "both", 11, 12, 20, "ambitious", "Allrounder", 55, "WWE", 2005, None, "Diva Search entrant who became a SmackDown valet and interviewer."),
    ("Lauren Jones", 1984, 2005, "both", 10, 11, 20, "loyal", "Allrounder", 54, "WWE", 2005, None, "2005 Diva Search finalist and backstage personality."),
    ("Rochelle Loewen", 1982, 2005, "both", 10, 11, 20, "loyal", "Allrounder", 55, "WWE", 2005, None, "Model and 2005 Diva Search finalist who made brief WWE appearances."),
    ("Persephone", 1980, 2005, "wrestler", 11, 10, 15, "prima_donna", "Brawler", 57, "SHIMMER", 2005, None, "Gothic character wrestler of the mid-2000s US indies."),
    ("Nattie Neidhart", 1982, 2005, "wrestler", 15, 12, 18, "ambitious", "Technician", 57, "SHIMMER", 2005, None, "Third-generation Hart-family wrestler who came up through the Canadian and US indies before a long WWE run."),
    ("Serena Deeb", 1985, 2005, "wrestler", 14, 12, 17, "ambitious", "Technician", 57, "OVW", 2005, None, "Sharp technical wrestler who trained under the Harts and became a decorated indie and WWE competitor."),
    ("Melissa Coates", 1971, 2005, "wrestler", 12, 11, 16, "money_hungry", "Powerhouse", 68, "TNA", 2005, None, "Muscular Canadian 'Super Genie' who wrestled the North American indies and TNA."),
    ("Nikki (Roxxi Laveaux)", 1983, 2005, "wrestler", 12, 11, 16, "loyal", "Brawler", 60, "NWA", 2005, None, "Voodoo-themed indie wrestler of the mid-2000s women's scene."),
    ("Hiroyo Matsumoto", 1985, 2005, "wrestler", 13, 11, 15, "ambitious", "Powerhouse", 60, "Ice Ribbon", 2005, None, "Powerful Japanese joshi wrestler who emerged in the mid-2000s."),
    ("Jennifer Blake", 1985, 2005, "wrestler", 12, 11, 18, "prima_donna", "Allrounder", 55, "SHIMMER", 2005, None, "Canadian wrestler and valet who came up on the mid-2000s indies."),
    ("Nikki Matthews", 1984, 2005, "wrestler", 11, 10, 16, "loyal", "Allrounder", 55, "SHIMMER", 2005, None, "US-indie wrestler of the mid-2000s women's circuit."),
    ("Kaori Yoneyama", 1982, 2005, "wrestler", 13, 11, 15, "ambitious", "High Flyer", 52, "JWP", 2005, None, "Diminutive, high-energy joshi high-flyer who debuted in 2000 and became a JWP mainstay."),
    ("Kyoko Kimura", 1981, 2005, "wrestler", 13, 11, 15, "money_hungry", "Brawler", 60, "Ice Ribbon", 2005, None, "Tough, well-traveled joshi wrestler of the 2000s Japanese scene."),
    ("Natsuki Taiyo", 1982, 2005, "wrestler", 13, 11, 15, "prima_donna", "High Flyer", 55, "AJW", 2005, None, "Energetic joshi high-flyer who came up in the mid-2000s Japanese promotions."),
    ("Ray", 1982, 2005, "wrestler", 12, 11, 16, "loyal", "Allrounder", 57, "JWP", 2005, None, "Versatile joshi wrestler of the mid-2000s indie scene."),
    ("Hikaru", 1983, 2005, "wrestler", 12, 11, 16, "ambitious", "Technician", 55, "Ibuki", 2005, None, "Technically minded joshi wrestler who emerged in the mid-2000s."),
    ("Eden Black", 1982, 2005, "wrestler", 13, 11, 16, "ambitious", "Technician", 55, "SHIMMER", 2005, None, "British technician who wrestled across the UK and US indies in the 2000s."),
]


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""CREATE TABLE IF NOT EXISTS wrestler_bio (
        wrestler_id INTEGER PRIMARY KEY REFERENCES wrestler(id),
        nickname TEXT, bio TEXT, updated_at TEXT);""")

    existing = {r["name"].strip() for r in con.execute("SELECT name FROM wrestler")}
    banned_ids = {r[0] for r in con.execute("SELECT wrestler_id FROM banned_wrestler")}
    removed_names = set()
    if RAW.exists():
        raw = json.load(open(RAW, encoding="utf-8"))
        for w in raw.get("wrestlers", []):
            if int(w["id"]) in banned_ids:
                removed_names.add(w["name"].strip())
                for alt in (w.get("names") or []):
                    removed_names.add(str(alt).strip())

    # Re-run-safe: start above the highest synthetic id already in the DB so a
    # second run (with new entries added) never collides with existing rows.
    top = con.execute("SELECT COALESCE(MAX(id), ?) FROM wrestler WHERE id >= 900000",
                      (BASE_ID - 1,)).fetchone()[0]
    next_id = max(top + 1, BASE_ID)

    added = skipped = 0
    for name, by, dc, role, cha, pop, looks, pers, style, wt, promo, py, nick, bio in W:
        name = name.strip()
        if name in existing or name in removed_names:
            skipped += 1
            continue
        wid = next_id
        next_id += 1
        age = 2000 - by
        con.execute(
            """INSERT INTO wrestler (id, name, birthday, birth_year, age_at_reset, age_precision,
                 birthplace, height_cm, weight_kg, rating, votes, adj_rating,
                 career_start, career_end, style, harvested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (wid, name, None, by, age, "year_only", None, None, wt, None, None, None,
             str(py), "present", style, NOW))
        con.execute(
            """INSERT INTO attributes (wrestler_id, charisma, popularity, looks, availability,
                 role, role_source, personality, formula_ver) VALUES (?,?,?,?,?,?,?,?,?)""",
            (wid, cha, pop, looks, "active_2000", role, None, pers, 3))
        con.execute("INSERT OR IGNORE INTO ring_name (wrestler_id, name, is_primary) VALUES (?,?,1)", (wid, name))
        con.execute("INSERT OR IGNORE INTO promotion_year (wrestler_id, promotion, year, matches) VALUES (?,?,?,0)",
                    (wid, promo, py))
        con.execute("INSERT OR IGNORE INTO wrestler_state (wrestler_id) VALUES (?)", (wid,))
        con.execute("""INSERT INTO attribute_override (wrestler_id, draft_class, updated_at)
                       VALUES (?,?,?) ON CONFLICT(wrestler_id) DO UPDATE SET draft_class=excluded.draft_class""",
                    (wid, dc, NOW))
        con.execute("""INSERT INTO wrestler_bio (wrestler_id, nickname, bio, updated_at) VALUES (?,?,?,?)
                       ON CONFLICT(wrestler_id) DO UPDATE SET nickname=excluded.nickname, bio=excluded.bio""",
                    (wid, nick, bio, NOW))
        added += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0]
    classes = con.execute(
        """SELECT COALESCE(o.draft_class,2000) dc, COUNT(*) n FROM wrestler w
           LEFT JOIN attribute_override o ON o.wrestler_id=w.id GROUP BY dc ORDER BY dc""").fetchall()
    print(f"added {added}, skipped {skipped} (already present / removed)")
    print(f"roster now {total}")
    print("draft classes:", {r["dc"]: r["n"] for r in classes})
    con.close()


if __name__ == "__main__":
    main()
