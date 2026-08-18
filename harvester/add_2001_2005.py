"""Add the 2001-2005 women's class and write nicknames + short bios.

Run:  python add_2001_2005.py

Idempotent — safe to re-run. New wrestlers get synthetic ids from 900001 up, so
they can never collide with a real cagematch id (existing roster or a removed
`banned_wrestler`). Bios are original, factual one-liners written by hand — not
copied from any source — and real ring nicknames.

Each of the four rating categories is out of 25; experience starts at 0 and is
earned in the sim, so a debut overall is charisma + popularity + looks.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "gm2000.db"
NOW = datetime.now(timezone.utc).isoformat()
BASE_ID = 900_001

# name, birth_year, draft_class, role, cha, pop, looks, personality, style, weight_kg,
# promo(label,year), nickname, bio
NEW = [
    ("Victoria", 1971, 2001, "wrestler", 16, 17, 20, "prima_donna", "Powerhouse", 68,
     ("WWE", 2001), "The Black Widow",
     "Bodybuilder-turned-wrestler who became one of WWE's most athletic and unhinged women's champions of the early 2000s, later reinventing herself as TNA's Tara."),
    ("Gail Kim", 1977, 2002, "wrestler", 15, 16, 20, "ambitious", "High Flyer", 52,
     ("WWE", 2002), "The First Lady of the Knockouts",
     "Korean-Canadian high-flyer who won the WWE Women's Championship on her TV debut and went on to define TNA's Knockouts division."),
    ("Mickie James", 1979, 2002, "wrestler", 20, 18, 21, "ambitious", "Allrounder", 55,
     ("ROH", 2002), "Hardcore Country",
     "Virginia native who broke out in ROH and TNA as Alexis Laree before a celebrated WWE run, pairing crisp in-ring work with country-star charisma."),
    ("Nidia", 1979, 2002, "both", 12, 11, 15, "loyal", "Brawler", 57,
     ("WWE", 2002), None,
     "Tough Enough winner who worked WWE's early 2000s as a scrappy valet and wrestler."),
    ("Jackie Gayda", 1981, 2002, "both", 11, 12, 18, "loyal", "Allrounder", 55,
     ("WWE", 2002), "Miss Jackie",
     "Tough Enough II winner who wrestled and valeted across WWE's SmackDown brand in the early 2000s."),
    ("Shaniqua", 1979, 2002, "wrestler", 11, 10, 15, "prima_donna", "Powerhouse", 68,
     ("WWE", 2002), None,
     "Tough Enough II co-winner repackaged as the imposing enforcer Shaniqua on SmackDown."),
    ("Traci Brooks", 1980, 2002, "both", 13, 12, 20, "prima_donna", "Allrounder", 54,
     ("TNA", 2002), "TNA's First Lady",
     "One of TNA's original on-screen women, a valet and occasional wrestler through the promotion's founding years."),
    ("Trinity", 1974, 2002, "both", 12, 11, 17, "ambitious", "High Flyer", 55,
     ("TNA", 2002), None,
     "Stuntwoman and daredevil valet in early TNA and WWE, known for high-risk dives from the rafters."),
    ("Goldylocks", 1979, 2002, "both", 14, 11, 18, "loyal", "Allrounder", 57,
     ("TNA", 2002), None,
     "Fan-favorite backstage interviewer and on-screen personality of TNA's earliest weekly pay-per-view era."),
    ("Allison Danger", 1978, 2002, "wrestler", 14, 12, 16, "loyal", "Technician", 61,
     ("ROH", 2002), None,
     "Veteran of the US independents and a foundational figure in Ring of Honor's early women's wrestling."),
    ("Mercedes Martinez", 1980, 2002, "wrestler", 15, 13, 16, "money_hungry", "Technician", 68,
     ("ROH", 2002), "The Latina Sensation",
     "Hard-hitting, durable technician who became one of the most respected women on the US indies across two decades."),
    ("Cheerleader Melissa", 1982, 2002, "wrestler", 14, 12, 15, "prima_donna", "Brawler", 61,
     ("ROH", 2002), None,
     "Versatile, stiff-striking indie star who worked SHIMMER, ROH and TNA under several personas including Raisha Saeed."),
    ("Ayako Hamada", 1981, 2002, "wrestler", 15, 12, 15, "ambitious", "High Flyer", 60,
     ("TNA", 2002), None,
     "Daughter of lucha legend Gran Hamada, a hard-kicking standout who wrestled across Japan, Mexico and the US."),
    ("Sara Del Rey", 1980, 2003, "wrestler", 16, 13, 16, "money_hungry", "Technician", 66,
     ("ROH", 2003), "The American Angel",
     "Elite technician regarded as one of the best women's wrestlers of her era, later WWE's first full-time female coach."),
    ("Awesome Kong", 1977, 2003, "wrestler", 16, 15, 12, "prima_donna", "Powerhouse", 130,
     ("TNA", 2003), None,
     "Monster heel who dominated in Japan as Amazing Kong before terrorizing TNA's Knockouts division."),
    ("Nikki Roxx", 1978, 2003, "wrestler", 12, 11, 16, "loyal", "Brawler", 63,
     ("TNA", 2003), None,
     "New England indie mainstay who wrestled throughout SHIMMER and TNA in the 2000s."),
    ("Michelle McCool", 1980, 2004, "wrestler", 15, 16, 21, "prima_donna", "Allrounder", 61,
     ("WWE", 2004), "Flawless",
     "Former schoolteacher who became SmackDown's first Divas Champion and a two-time women's champion."),
    ("Candice Michelle", 1978, 2004, "both", 14, 15, 22, "prima_donna", "Allrounder", 55,
     ("WWE", 2004), "The GoDaddy Girl",
     "Model and commercial star who developed into a WWE Women's Champion in the mid-2000s."),
    ("Maria Kanellis", 1982, 2004, "both", 15, 15, 22, "ambitious", "Allrounder", 55,
     ("WWE", 2004), "The First Lady of Wrestling",
     "Diva Search entrant turned interviewer, valet and wrestler across WWE, TNA and ROH."),
    ("Christy Hemme", 1980, 2004, "both", 13, 13, 20, "loyal", "Allrounder", 55,
     ("WWE", 2004), None,
     "Diva Search winner who wrestled in WWE before a long run as a TNA valet and ring announcer."),
    ("Joy Giovanni", 1978, 2004, "both", 10, 10, 19, "loyal", "Allrounder", 57,
     ("WWE", 2004), None,
     "Diva Search finalist and massage-therapist character who briefly valeted and wrestled on SmackDown."),
    ("Lacey", 1981, 2004, "both", 13, 11, 18, "prima_donna", "Allrounder", 55,
     ("ROH", 2004), None,
     "Manager and wrestler central to Ring of Honor storylines as the leader of Lacey's Angels."),
    ("Melina", 1979, 2005, "both", 18, 17, 22, "prima_donna", "Allrounder", 54,
     ("WWE", 2005), "The Paparazzi Princess",
     "Flexible, flamboyant three-time WWE Women's/Divas Champion famous for her split-legged entrance."),
    ("Ashley Massaro", 1979, 2005, "both", 12, 14, 20, "ambitious", "Allrounder", 52,
     ("WWE", 2005), None,
     "Diva Search winner and cover model who wrestled on WWE's Raw brand in the mid-2000s."),
    ("ODB", 1978, 2005, "wrestler", 15, 12, 13, "money_hungry", "Brawler", 68,
     ("TNA", 2005), "The One and Only",
     "Rowdy, flask-swigging brawler who became a beloved multi-time TNA Knockouts Champion."),
    ("Daizee Haze", 1982, 2005, "wrestler", 13, 12, 16, "ambitious", "High Flyer", 55,
     ("ROH", 2005), "The Haze",
     "Technically gifted ROH and SHIMMER regular who later trained and mentored the next generation."),
]

# Existing roster: name -> (nickname, bio). Original one-liners, real nicknames.
EXISTING = {
    "Trish Stratus": ("Stratusfaction", "Fitness model who grew into a seven-time WWE Women's Champion, headlined Raw and entered the Hall of Fame on the first ballot."),
    "Lita": ("The Xtreme Diva", "Daredevil high-flyer whose moonsaults and punk-rock edge helped redefine women's wrestling alongside Trish Stratus."),
    "Stephanie McMahon": ("The Billion Dollar Princess", "On-screen authority figure and heir to the McMahon empire who became one of wrestling's premier villains."),
    "Torrie Wilson": (None, "WCW-bred glamour star who became a fixture of WWE's early-2000s women's division and a two-time Playboy cover model."),
    "Stacy Keibler": ("The Legs of WrestleMania", "Statuesque former NFL cheerleader famous in WCW and WWE and later a Dancing with the Stars finalist."),
    "Sensational Sherri": ("Sensational", "Fiery Hall of Fame manager and champion who guided some of the 1980s-90s biggest stars to the ring."),
    "Sable": (None, "Trailblazing late-1990s WWE sensation and record-setting cover star who drew huge attention to the women's division."),
    "Sunny": ("The Original Diva", "Manager and valet widely called WWE's first true Diva, an enormous draw in the mid-1990s."),
    "Alundra Blayze": (None, "Champion known as Madusa in WCW and Alundra Blayze in WWE, a groundbreaking wrestler and Hall of Famer."),
    "Jacqueline": (None, "Hard-nosed, athletic two-time WWE Women's Champion and Hall of Famer who could go with anyone."),
    "Molly Holly": (None, "Clean-living, technically superb WWE Women's Champion who also wrestled as Mona and Miss Madness."),
    "Jazz": (None, "Powerful, no-nonsense ECW and WWE women's champion with a shoot-style edge."),
    "Ivory": (None, "Three-time WWE Women's Champion who became a respected trainer and broadcaster."),
    "Chyna": ("The Ninth Wonder of the World", "Groundbreaking powerhouse and the only woman ever to hold the WWE Intercontinental Championship."),
    "Terri Runnels": (None, "Glamorous WWE manager and valet of the late 1990s known for her mic work and on-screen mischief."),
    "Francine": ("The Queen of Extreme", "ECW's signature valet whose fiery presence made her one of the promotion's most recognizable figures."),
    "Dawn Marie": (None, "ECW and WWE valet and manager prominent in early-2000s SmackDown storylines."),
    "Luna Vachon": (None, "Wild, face-painted second-generation star from the Vachon family who terrorized WWE and ECW rings."),
    "Bull Nakano": (None, "Towering, face-painted Japanese icon who held top titles in Japan and WWE, later a pro golfer."),
    "Aja Kong": (None, "Monstrous, hard-hitting joshi legend whose brutal strikes made her one of Japan's most feared champions."),
    "Manami Toyota": (None, "Widely regarded as one of the greatest wrestlers ever, an impossibly athletic joshi ace of the 1990s."),
    "Akira Hokuto": ("The Dangerous Queen", "Fearless joshi legend celebrated for wrestling through brutal injuries."),
    "Chigusa Nagayo": (None, "Half of the beloved Crush Gals whose 1980s feuds drew huge crowds and mainstream fame in Japan."),
    "Lioness Asuka": (None, "The other half of the Crush Gals, a charismatic superstar of Japan's 1980s joshi boom."),
    "Dynamite Kansai": (None, "Long-limbed, kick-heavy joshi standout and JWP ace known for her stiff strikes."),
    "Kyoko Inoue": (None, "Powerful, versatile joshi star of AJW's golden era who blended strength and agility."),
    "Meiko Satomura": ("The Final Boss", "Ground-fighting joshi ace who debuted as a teen and became a globally revered veteran."),
    "Wendi Richter": (None, "Rock 'n' Wrestling star whose MSG matches helped ignite the 1980s boom; a Hall of Famer."),
    "Leilani Kai": (None, "1980s WWE women's champion who headlined the first WrestleMania's women's title match."),
    "Velvet McIntyre": (None, "Agile Irish-Canadian 1980s women's champion known for her barefoot high-flying style."),
    "Sharmell": (None, "Former Miss Black America who valeted in WCW and WWE and later managed Booker T."),
    "Debra": (None, "Glamorous WCW and WWE valet and on-screen personality of the late 1990s."),
    "Kat": (None, "Late-1990s WWE personality and women's/hardcore titleholder known for her brash antics."),
    "Tori": (None, "Athletic late-1990s WWE performer who feuded with Sable and aligned with D-Generation X."),
    "Beulah": (None, "ECW valet at the center of some of the promotion's most memorable storylines."),
    "Kimberly": (None, "Leader of WCW's Nitro Girls and a valet known for the 'Kimberly' sign gimmick."),
    "Major Gunns": (None, "WCW valet of the Misfits in Action storyline around the turn of the 2000s."),
    "Asya": (None, "Powerhouse WCW wrestler positioned as the promotion's answer to Chyna."),
    "Nicole Bass": (None, "Imposing bodybuilder who worked ECW and WWE as an intimidating physical presence."),
    "Missy Hyatt": (None, "Pioneering valet and broadcaster who was one of wrestling's most visible women of the 1980s-90s."),
    "Woman": (None, "Elegant, influential manager in the NWA/WCW and ECW during the late 1980s and 1990s."),
    "Daffney": ("The Scream Queen", "Gothic, shrieking WCW valet who became a fearless hardcore wrestler in TNA."),
    "Emi Sakura": (None, "Veteran trainer and wrestler who mentored a generation of joshi and later joined AEW."),
    "Kimona Wanalaya": (None, "ECW valet of the late 1990s known for her provocative on-screen character."),
    "Mayumi Ozaki": (None, "Hardcore joshi legend and Oz Academy ace known for her violent garbage-wrestling brawls."),
    "Malia Hosaka": (None, "Well-traveled American joshi-style veteran and tag specialist of the 1990s indies."),
    "Lexie Fyfe": (None, "Durable US independent veteran and trainer who wrestled the women's scene for two decades."),
    "Angel Orsini": (None, "Powerful ECW-era wrestler and multi-time women's champion on the East Coast indies."),
    "Bertha Faye": (None, "Powerful Canadian wrestler who held titles in Japan and WWE in the 1990s."),
    "Dump Matsumoto": (None, "Monstrous, face-painted heel who was the ultimate villain of Japan's 1980s Crush Gals boom."),
}


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS wrestler_bio (
            wrestler_id INTEGER PRIMARY KEY REFERENCES wrestler(id),
            nickname TEXT, bio TEXT, updated_at TEXT);
    """)

    existing_names = {r["name"] for r in con.execute("SELECT name FROM wrestler")}
    banned = {r[0] for r in con.execute("SELECT wrestler_id FROM banned_wrestler")}

    added, skipped = 0, 0
    for i, (name, by, dc, role, cha, pop, looks, pers, style, wt, promo, nick, bio) in enumerate(NEW):
        if name in existing_names:
            # already added on a prior run — just refresh the bio
            wid = con.execute("SELECT id FROM wrestler WHERE name=?", (name,)).fetchone()["id"]
            _bio(con, wid, nick, bio)
            skipped += 1
            continue
        wid = BASE_ID + i
        if wid in banned:
            continue
        age = 2000 - by
        con.execute(
            """INSERT INTO wrestler (id, name, birthday, birth_year, age_at_reset, age_precision,
                 birthplace, height_cm, weight_kg, rating, votes, adj_rating,
                 career_start, career_end, style, harvested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (wid, name, None, by, age, "year_only", None, None, wt, None, None, None,
             str(promo[1]), "present", style, NOW))
        con.execute(
            """INSERT INTO attributes (wrestler_id, charisma, popularity, looks, availability,
                 role, role_source, personality, formula_ver)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (wid, cha, pop, looks, "active_2000", role, None, pers, 3))
        con.execute("INSERT OR IGNORE INTO ring_name (wrestler_id, name, is_primary) VALUES (?,?,1)", (wid, name))
        con.execute("INSERT OR IGNORE INTO promotion_year (wrestler_id, promotion, year, matches) VALUES (?,?,?,0)",
                    (wid, promo[0], promo[1]))
        con.execute("INSERT OR IGNORE INTO wrestler_state (wrestler_id) VALUES (?)", (wid,))
        con.execute(
            """INSERT INTO attribute_override (wrestler_id, draft_class, updated_at)
               VALUES (?,?,?)
               ON CONFLICT(wrestler_id) DO UPDATE SET draft_class=excluded.draft_class""",
            (wid, dc, NOW))
        _bio(con, wid, nick, bio)
        added += 1

    # Existing roster bios.
    bio_set = 0
    for name, (nick, bio) in EXISTING.items():
        row = con.execute("SELECT id FROM wrestler WHERE name=?", (name,)).fetchone()
        if row:
            _bio(con, row["id"], nick, bio)
            bio_set += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0]
    classes = con.execute(
        """SELECT COALESCE(o.draft_class, 2000) dc, COUNT(*) n
           FROM wrestler w LEFT JOIN attribute_override o ON o.wrestler_id=w.id
           GROUP BY dc ORDER BY dc""").fetchall()
    print(f"added {added} new wrestlers, refreshed {skipped}, bios set on {bio_set} existing")
    print(f"roster now {total}")
    print("draft classes:", {r["dc"]: r["n"] for r in classes})
    con.close()


def _bio(con, wid, nick, bio):
    con.execute(
        """INSERT INTO wrestler_bio (wrestler_id, nickname, bio, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(wrestler_id) DO UPDATE SET nickname=excluded.nickname,
             bio=excluded.bio, updated_at=excluded.updated_at""",
        (wid, nick, bio, NOW))


if __name__ == "__main__":
    main()
