"""Add the 2005-2010 women's class — everyone ACTIVE in that window, not just debutantes.

Run:  python add_2005_2010.py

Idempotent — safe to re-run. Matching is by name against every existing
`wrestler.name` AND every `ring_name`, so a wrestler already on the roster under
a different gimmick is skipped rather than duplicated. That check is the whole
point of this pass: batches 1-3 already carry 173 women, and a plain
insert-if-name-missing would have re-added Angelina Love (already here as Angel
Williams), Velvet Sky (Talia Madison), Taylor Wilde (Shantelle Taylor), Tara
(Victoria), Alissa Flash (Cheerleader Melissa) and Sarita (Sarah Stock).

New wrestlers get synthetic ids from 900201 up — batch 1 used 900001-900026 and
batches 2/3 used 900101-900197, so the ranges cannot collide, and a synthetic id
can never collide with a real cagematch id either.

DRAFT CLASS. `draft_class` is the season she enters the draft pool, and the game
resets to January 2000. Someone who debuted in 1997 but whose relevance here is
her 2005-2010 run cannot be given a 1997 class — those seasons are already gone.
So the rule is:

    draft_class = clamp(real arrival / prominence year, 2005, 2010)

which keeps this entire batch inside the window that was asked for and leaves the
already-populated 2000-2004 classes untouched.

Each of the four rating categories is out of 25; experience starts at 0 and is
earned in the sim, so a debut overall is charisma + popularity + looks.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "gm2000.db"
NOW = datetime.now(timezone.utc).isoformat()
BASE_ID = 900_201

# name, birth_year, draft_class, role, cha, pop, looks, personality, style, weight_kg,
# promo(label, year), nickname, bio
NEW = [
    # ---------------------------------------------------------- WWE / ECW 2005-2010
    ("Layla El", 1977, 2006, "both", 15, 15, 21, "ambitious", "Allrounder", 52,
     ("WWE", 2006), "The Queen of the Divas",
     "British dancer who won the 2006 Diva Search and grew into a genuinely capable heel worker and Divas Champion."),
    ("Kelly Kelly", 1987, 2006, "both", 13, 17, 22, "ambitious", "High Flyer", 52,
     ("WWE", 2006), "K2",
     "ECW's exhibitionist debutante, brought in at nineteen and matured into one of the most visible champions of the Divas era."),
    ("Maryse Ouellet", 1983, 2006, "both", 16, 16, 22, "prima_donna", "Allrounder", 57,
     ("WWE", 2006), "The Sexiest of the Sexy",
     "French-Canadian model whose sneering, French-muttering heel act carried her to two Divas Championships."),
    ("Eve Torres", 1984, 2007, "wrestler", 15, 14, 21, "ambitious", "Allrounder", 54,
     ("WWE", 2007), None,
     "Diva Search winner and trained dancer who worked her way to three championships and a heel turn with real bite."),
    ("Alicia Fox", 1986, 2006, "wrestler", 13, 12, 20, "ambitious", "Allrounder", 60,
     ("WWE", 2006), "Foxy",
     "Long-serving WWE athlete whose deliberately unpredictable style made her the first African-American Divas Champion."),
    ("Rosa Mendes", 1979, 2006, "both", 10, 10, 19, "loyal", "Brawler", 57,
     ("WWE", 2006), None,
     "Costa Rican-Canadian Diva Search finalist who spent the era largely as a valet and enhancement worker."),
    ("Katie Lea Burchill", 1979, 2005, "wrestler", 13, 11, 18, "ambitious", "Technician", 57,
     ("WWE", 2005), None,
     "English wrestler with a strong technical base, best known for a deliberately unsettling sibling act on Raw."),
    ("Brie Bella", 1983, 2007, "wrestler", 12, 14, 20, "loyal", "Allrounder", 54,
     ("WWE", 2007), None,
     "One half of the Bella Twins, whose under-the-ring switch spot defined WWE's late-2000s Divas comedy."),
    ("Nikki Bella", 1983, 2007, "wrestler", 13, 15, 20, "ambitious", "Allrounder", 54,
     ("WWE", 2007), "Fearless",
     "The louder, more aggressive Bella twin, who long outlasted the gimmick to become a record-setting champion."),
    ("Tamina Snuka", 1978, 2009, "wrestler", 10, 12, 15, "loyal", "Powerhouse", 68,
     ("WWE", 2009), None,
     "Second-generation powerhouse and daughter of Jimmy Snuka, used as an enforcer from her 2009 arrival onward."),
    ("Kaitlyn", 1986, 2010, "wrestler", 13, 12, 19, "ambitious", "Powerhouse", 61,
     ("WWE", 2010), "The Hybrid Diva",
     "Former bodybuilder who won the third season of NXT and turned unusual strength into a distinctive style."),
    ("AJ Lee", 1987, 2009, "wrestler", 18, 14, 19, "ambitious", "High Flyer", 52,
     ("WWE", 2009), "The Geek Goddess",
     "Undersized New Jersey wrestler out of Florida developmental whose unhinged character work made her the most compelling woman on the show."),
    ("Naomi", 1987, 2009, "wrestler", 13, 11, 19, "ambitious", "High Flyer", 57,
     ("WWE", 2009), None,
     "Former NBA dancer whose athleticism and speed made her one of the most explosive women of the following decade."),
    ("Aksana", 1982, 2010, "both", 10, 9, 19, "money_hungry", "Powerhouse", 61,
     ("WWE", 2010), None,
     "Lithuanian fitness competitor who arrived through NXT with a heavily accented, vampish character."),
    ("Taryn Terrell", 1985, 2008, "both", 13, 12, 20, "ambitious", "High Flyer", 54,
     ("WWE", 2008), None,
     "New Orleans athlete who fronted ECW as on-screen general manager Tiffany before a much harder-hitting TNA run."),
    ("Vickie Guerrero", 1968, 2006, "manager", 19, 16, 10, "prima_donna", "Brawler", 68,
     ("WWE", 2006), "The Cougar",
     "Widow of Eddie Guerrero who became the most genuinely hated authority figure in the company on the strength of one shriek."),
    ("Angela Fong", 1983, 2008, "both", 10, 9, 18, "loyal", "High Flyer", 52,
     ("WWE", 2008), "Savannah",
     "Canadian Diva Search finalist and gymnast who worked Florida developmental as ring announcer and wrestler Savannah."),
    ("Lena Yada", 1978, 2007, "manager", 9, 9, 18, "loyal", "Allrounder", 50,
     ("WWE", 2007), None,
     "Hawaiian surfer and Diva Search entrant used mainly as an ECW interviewer and valet."),
    ("Kara Drew", 1983, 2007, "both", 10, 10, 17, "loyal", "Allrounder", 55,
     ("WWE", 2007), "Cherry",
     "Roller-derby-styled valet of SmackDown's Deuce and Domino act, who kept working the indies long after the gimmick ended."),

    # ---------------------------------------------------------- TNA Knockouts 2005-2010
    ("Madison Rayne", 1986, 2009, "wrestler", 14, 12, 19, "ambitious", "Allrounder", 54,
     ("TNA", 2009), None,
     "Ohio-trained wrestler who became the sneering heart of The Beautiful People and a multi-time Knockouts Champion."),
    ("Lacey Von Erich", 1986, 2009, "both", 9, 12, 20, "prima_donna", "Allrounder", 61,
     ("TNA", 2009), None,
     "Third-generation Von Erich whose Knockouts run leaned on the surname and on Beautiful People glamour."),
    ("Sarah Stock", 1978, 2005, "wrestler", 15, 13, 18, "ambitious", "Technician", 57,
     ("CMLL", 2005), "Dark Angel",
     "Canadian technician who became a genuine main-event star in CMLL years before joining TNA as Sarita."),
    ("Brooke Adams", 1984, 2007, "both", 12, 12, 21, "ambitious", "Allrounder", 52,
     ("WWE", 2007), None,
     "Texan dancer and Diva Search finalist who found her niche in TNA as Miss Tessmacher."),
    ("Rhaka Khan", 1979, 2008, "both", 9, 9, 18, "money_hungry", "Powerhouse", 63,
     ("TNA", 2008), None,
     "Former Diva Search entrant used in TNA as an imposing enforcer and bodyguard."),
    ("Rosie Lottalove", 1985, 2010, "wrestler", 11, 9, 12, "loyal", "Powerhouse", 113,
     ("TNA", 2010), None,
     "Super-heavyweight out of Ohio Valley Wrestling who brought a body type the Knockouts division had never booked."),
    ("Karen Jarrett", 1971, 2010, "manager", 14, 12, 17, "prima_donna", "Allrounder", 55,
     ("TNA", 2010), None,
     "On-screen authority figure whose barbed socialite persona anchored TNA's 2010-11 power struggles."),

    # ---------------------------------------------------------- ROH / SHIMMER / US indies
    ("Jessicka Havok", 1987, 2005, "wrestler", 14, 11, 14, "money_hungry", "Brawler", 79,
     ("SHIMMER", 2005), "The Havok Death Machine",
     "Ohio brawler whose size and willingness to bleed made her a headline attraction on the hardcore indies."),
    ("LuFisto", 1980, 2005, "wrestler", 15, 11, 15, "ambitious", "Brawler", 61,
     ("SHIMMER", 2005), "The Super Hardcore Anime",
     "Quebec hardcore pioneer who fought and won a human-rights case for the right of women to wrestle men in Ontario."),
    ("Mickie Knuckles", 1984, 2005, "wrestler", 13, 10, 13, "money_hungry", "Brawler", 68,
     ("SHIMMER", 2005), None,
     "Midwest deathmatch regular known for taking, and handing out, punishment few of her peers would."),
    ("Hailey Hatred", 1985, 2005, "wrestler", 12, 9, 14, "ambitious", "Powerhouse", 68,
     ("SHIMMER", 2005), None,
     "American striker who spent years in Japan and brought a stiff, joshi-hardened style back to the US indies."),
    ("Cherry Bomb", 1988, 2007, "wrestler", 14, 11, 19, "ambitious", "Allrounder", 54,
     ("SHIMMER", 2007), None,
     "Canadian wrestler with bright, crowd-pleasing offence who later found a far wider audience as Allie."),
    ("Sweet Cherrie", 1980, 2005, "wrestler", 12, 9, 16, "loyal", "Allrounder", 57,
     ("SHIMMER", 2005), None,
     "Montreal veteran and SHIMMER original known for a compact, precise style."),
    ("Courtney Rush", 1985, 2007, "wrestler", 15, 11, 17, "ambitious", "Allrounder", 61,
     ("SHIMMER", 2007), None,
     "Canadian wrestler with an unusually committed character streak, later reinvented wholesale as Rosemary."),
    ("Athena", 1987, 2008, "wrestler", 16, 12, 18, "ambitious", "High Flyer", 52,
     ("SHIMMER", 2008), "The Wrestling Goddess",
     "Explosive Texan high-flyer whose athleticism made her one of the most exciting indie women of her generation."),
    ("Mia Yim", 1989, 2009, "wrestler", 14, 11, 18, "ambitious", "Allrounder", 57,
     ("SHIMMER", 2009), None,
     "Maryland-trained all-rounder equally at home in a technical match or a hardcore brawl."),
    ("Kimber Lee", 1990, 2010, "wrestler", 13, 10, 18, "ambitious", "Technician", 54,
     ("SHIMMER", 2010), None,
     "Pennsylvania wrestler who built her reputation on an intergender indie circuit that rarely booked women at all."),
    ("Heidi Lovelace", 1991, 2010, "wrestler", 13, 10, 17, "ambitious", "High Flyer", 50,
     ("SHIMMER", 2010), None,
     "Undersized, reckless flyer from the Midwest indies who would later wrestle as Ruby Riott."),
    ("Ivelisse Velez", 1987, 2008, "wrestler", 14, 11, 19, "prima_donna", "High Flyer", 54,
     ("WWE", 2008), None,
     "Puerto Rican competitor with a fiery temper and a fast, hard-hitting style."),
    ("Leva Bates", 1984, 2008, "wrestler", 13, 10, 17, "loyal", "Allrounder", 57,
     ("SHIMMER", 2008), None,
     "Florida wrestler whose cosplay-driven character work made her one of the most recognisable acts on the indies."),
    ("Su Yung", 1988, 2007, "wrestler", 12, 10, 17, "ambitious", "Allrounder", 57,
     ("SHIMMER", 2007), None,
     "Versatile American who worked years of straightforward indie matches long before her horror reinvention."),
    ("Christina Von Eerie", 1990, 2008, "wrestler", 13, 10, 17, "money_hungry", "Brawler", 57,
     ("SHIMMER", 2008), None,
     "Green-mohawked punk striker who worked a stiff, aggressive style across the American indies."),
    ("Sassy Stephie", 1986, 2007, "wrestler", 12, 9, 17, "prima_donna", "Allrounder", 57,
     ("SHIMMER", 2007), None,
     "Midwest heel with a loud cheerleader gimmick and a genuine mean streak underneath it."),
    ("Melanie Cruise", 1983, 2008, "wrestler", 11, 9, 15, "money_hungry", "Powerhouse", 82,
     ("SHIMMER", 2008), None,
     "Towering Chicago-area heel who built her whole offence around height and reach."),
    ("Annie Social", 1981, 2005, "wrestler", 11, 8, 15, "loyal", "Brawler", 61,
     ("SHIMMER", 2005), None,
     "Midwest indie veteran and SHIMMER original with a scrappy, unglamorous style."),
    ("Rachel Summerlyn", 1986, 2007, "wrestler", 12, 9, 16, "ambitious", "Brawler", 61,
     ("SHIMMER", 2007), None,
     "Texan wrestler known for brutal intergender and hardcore matches on the Anarchy Championship circuit."),
    ("Nevaeh", 1986, 2005, "wrestler", 12, 9, 16, "loyal", "Brawler", 61,
     ("SHIMMER", 2005), None,
     "Ohio wrestler who came up through the same rough Midwest scene that produced its hardest hitters."),
    ("Allysin Kay", 1989, 2009, "wrestler", 13, 10, 18, "money_hungry", "Powerhouse", 68,
     ("SHIMMER", 2009), None,
     "Detroit-trained heel with real power and an abrasive, confrontational promo style."),
    ("Marti Belle", 1987, 2009, "wrestler", 11, 9, 18, "loyal", "Allrounder", 57,
     ("SHIMMER", 2009), None,
     "Dominican-American wrestler off the New York indies who built a long career in tag wrestling."),
    ("Santana Garrett", 1988, 2010, "wrestler", 13, 11, 19, "ambitious", "Allrounder", 57,
     ("SHIMMER", 2010), None,
     "Second-generation Floridian with a bright babyface act and a well-schooled ground game."),
    ("Solo Darling", 1991, 2010, "wrestler", 12, 9, 16, "loyal", "High Flyer", 50,
     ("SHIMMER", 2010), None,
     "Small, quick New England flyer with an unmistakable candy-coloured presentation."),
    ("Veda Scott", 1988, 2010, "both", 13, 9, 17, "ambitious", "Technician", 54,
     ("ROH", 2010), None,
     "Lawyer-turned-wrestler who worked Ring of Honor as both a manager and a technically sound competitor."),

    # ---------------------------------------------------------- Europe / Australasia
    ("Alpha Female", 1983, 2005, "wrestler", 12, 10, 13, "money_hungry", "Powerhouse", 100,
     ("SHIMMER", 2005), "The Alpha Female",
     "Imposing German powerhouse who dominated European rings with stiff, believable monster matches."),
    ("Blue Nikita", 1984, 2005, "wrestler", 11, 8, 16, "loyal", "Brawler", 61,
     ("SHIMMER", 2005), None,
     "British wrestler and early mainstay of the UK's very small women's scene."),
    ("Britani Knight", 1992, 2010, "wrestler", 15, 12, 20, "ambitious", "Technician", 54,
     ("SHIMMER", 2010), None,
     "Third-generation Norwich wrestler who had already worked years of British shows as a teenager before becoming Paige."),
    ("Rhia O'Reilly", 1985, 2007, "wrestler", 12, 9, 16, "loyal", "Brawler", 61,
     ("SHIMMER", 2007), None,
     "Irish wrestler who became a fixture of the British scene as a grounded, no-nonsense heel."),
    ("Erin Angel", 1987, 2007, "wrestler", 11, 9, 18, "loyal", "High Flyer", 52,
     ("SHIMMER", 2007), None,
     "English flyer and one of the more visible women on the UK circuit of the late 2000s."),
    ("Shanna", 1986, 2006, "wrestler", 13, 10, 18, "ambitious", "Technician", 54,
     ("SHIMMER", 2006), None,
     "Portuguese wrestler who travelled constantly across Europe, Japan and the United States to find matches."),
    ("Klondyke Kate", 1964, 2005, "wrestler", 11, 9, 10, "money_hungry", "Powerhouse", 120,
     ("SHIMMER", 2005), None,
     "Long-serving British heavyweight and one of the few constants in British women's wrestling for decades."),
    ("Madison Eagles", 1985, 2005, "wrestler", 15, 12, 17, "ambitious", "Technician", 75,
     ("SHIMMER", 2005), None,
     "Tall, hard-hitting Australian widely regarded as one of the best women's wrestlers in the world at her peak."),
    ("Kellie Skater", 1986, 2007, "wrestler", 14, 10, 15, "loyal", "Technician", 63,
     ("SHIMMER", 2007), None,
     "Australian mat wrestler with a deadpan comic streak and a genuinely mean submission game."),
    ("Jessie McKay", 1989, 2009, "wrestler", 15, 11, 19, "loyal", "Allrounder", 57,
     ("SHIMMER", 2009), "The Aussie Arrow",
     "Sunny, technically sound Australian who would later reach WWE as Billie Kay."),
    ("Shazza McKenzie", 1989, 2009, "wrestler", 12, 9, 17, "loyal", "High Flyer", 52,
     ("SHIMMER", 2009), None,
     "Energetic Australian regular of the Sydney scene and a mainstay of its women's division."),
    ("Tenille Dashwood", 1989, 2008, "wrestler", 14, 11, 20, "ambitious", "Allrounder", 57,
     ("SHIMMER", 2008), None,
     "Australian trained by Lance Storm who broke out internationally as Emma."),
    ("Toni Storm", 1995, 2010, "wrestler", 15, 12, 20, "ambitious", "Allrounder", 61,
     ("SHIMMER", 2010), None,
     "Started wrestling in New Zealand and Australia as a child before becoming a global headliner."),
    ("Evie", 1988, 2010, "wrestler", 14, 10, 17, "ambitious", "Technician", 57,
     ("SHIMMER", 2010), None,
     "New Zealand technician whose crisp, strike-heavy work made her a standout of the Australasian scene."),

    # ---------------------------------------------------------- Joshi 2005-2010
    ("Io Shirai", 1990, 2007, "wrestler", 17, 14, 19, "ambitious", "High Flyer", 52,
     ("NEO", 2007), "The Genius of the Sky",
     "Spectacular Japanese flyer whose moonsault and fearless dives made her the ace of a generation."),
    ("Mio Shirai", 1986, 2007, "wrestler", 13, 10, 17, "loyal", "Technician", 52,
     ("NEO", 2007), None,
     "Io's elder sister, a sharp technician and character worker of the Japanese indie scene."),
    ("Hikaru Shida", 1988, 2008, "wrestler", 15, 12, 19, "ambitious", "Allrounder", 57,
     ("Ice Ribbon", 2008), None,
     "Kendo-stick-wielding Japanese wrestler whose hard strikes and pacing translate anywhere in the world."),
    ("Riho", 1997, 2006, "wrestler", 14, 11, 18, "loyal", "High Flyer", 40,
     ("Ice Ribbon", 2006), None,
     "Began wrestling at nine years old and grew into a tiny, fearless flyer who could hang with anyone."),
    ("Ryo Mizunami", 1988, 2006, "wrestler", 14, 11, 15, "loyal", "Powerhouse", 68,
     ("NEO", 2006), None,
     "Broad-shouldered Japanese brawler with an enormous lariat and a beloved underdog streak."),
    ("Syuri", 1989, 2008, "wrestler", 15, 11, 18, "ambitious", "Technician", 55,
     ("Ibuki", 2008), None,
     "Trained shoot fighter whose kicks and submissions give her matches a genuine combat-sport edge."),
    ("Arisa Nakajima", 1989, 2007, "wrestler", 15, 11, 16, "ambitious", "Allrounder", 55,
     ("JWP", 2007), None,
     "Ferocious Japanese wrestler who works at a punishing pace and became JWP's defining ace."),
    ("Tsukasa Fujimoto", 1987, 2007, "wrestler", 14, 10, 17, "loyal", "High Flyer", 50,
     ("Ice Ribbon", 2007), None,
     "Ice Ribbon's franchise player, quick and durable across an extraordinary number of matches."),
    ("Kagetsu", 1990, 2007, "wrestler", 14, 10, 16, "money_hungry", "Allrounder", 55,
     ("Ice Ribbon", 2007), None,
     "Japanese wrestler whose venomous heel work and stable leadership made her a main-event draw."),
    ("Hanako Nakamori", 1988, 2007, "wrestler", 13, 9, 16, "loyal", "Technician", 55,
     ("JWP", 2007), None,
     "JWP-trained technician known for a stiff kicking game and long, disciplined title matches."),
    ("Misaki Ohata", 1988, 2007, "wrestler", 13, 9, 17, "loyal", "Allrounder", 52,
     ("Ibuki", 2007), None,
     "Versatile Japanese wrestler who spent the era racking up matches across the country's smaller promotions."),
    ("Sendai Sachiko", 1989, 2008, "wrestler", 13, 10, 16, "loyal", "High Flyer", 50,
     ("Ibuki", 2008), None,
     "Half of the Sendai Sisters, a small, fast flyer trained by Meiko Satomura."),
    ("Dash Chisako", 1988, 2008, "wrestler", 13, 10, 16, "loyal", "High Flyer", 52,
     ("Ibuki", 2008), None,
     "The other Sendai Sister, a diving specialist with a reckless streak."),
    ("Nagisa Nozaki", 1985, 2007, "wrestler", 12, 9, 17, "loyal", "Technician", 55,
     ("Ice Ribbon", 2007), None,
     "Ice Ribbon regular known for a calm, methodical style and a long run as its senior hand."),
    ("Yumi Ohka", 1980, 2005, "wrestler", 13, 10, 18, "prima_donna", "Allrounder", 61,
     ("NEO", 2005), None,
     "Long-legged Japanese wrestler and Pro Wrestling WAVE cornerstone with a punishing kick game."),
    ("Mika Iida", 1986, 2007, "wrestler", 12, 9, 15, "loyal", "Powerhouse", 65,
     ("NEO", 2007), None,
     "Sturdy Japanese wrestler who spent the era grinding out matches in the smaller joshi promotions."),
    ("Toshie Uematsu", 1978, 2005, "wrestler", 13, 10, 17, "loyal", "High Flyer", 55,
     ("GAEA", 2005), None,
     "Gaea-trained veteran flyer who remained a reliable hand right across the joshi scene."),
    ("Sonoko Kato", 1977, 2005, "wrestler", 13, 10, 16, "loyal", "Allrounder", 60,
     ("GAEA", 2005), None,
     "Gaea Japan mainstay with a strong kicking style and a long, consistent career."),
    ("KAORU", 1969, 2005, "wrestler", 13, 11, 15, "money_hungry", "Brawler", 60,
     ("GAEA", 2005), None,
     "Veteran Japanese wrestler who moved from athletic junior work into weapon-heavy garbage brawls."),
    ("Devil Masami", 1961, 2005, "wrestler", 12, 12, 12, "loyal", "Powerhouse", 85,
     ("AJW", 2005), None,
     "One of the most decorated Japanese wrestlers of the 1980s, still working selectively decades later."),
    ("Mariko Yoshida", 1970, 2005, "wrestler", 14, 11, 15, "loyal", "Technician", 55,
     ("ARSION", 2005), None,
     "Submission specialist whose ARSION style influenced a whole generation of Japanese women's wrestling."),
    ("Cherry", 1981, 2005, "wrestler", 12, 9, 17, "loyal", "Allrounder", 52,
     ("Ibuki", 2005), None,
     "DDT's first prominent woman wrestler, a light, agile worker in an overwhelmingly male promotion."),
    ("Yuu Yamagata", 1983, 2005, "wrestler", 12, 9, 17, "loyal", "High Flyer", 52,
     ("NEO", 2005), None,
     "Japanese flyer and tag specialist who worked steadily through the joshi promotions of the era."),
    ("Sawako Shimono", 1986, 2006, "wrestler", 11, 8, 14, "loyal", "Powerhouse", 75,
     ("NEO", 2006), None,
     "Heavy-set Japanese wrestler used as the immovable object of the mid-2000s joshi undercard."),

    # ---------------------------------------------------------- Mexico 2005-2010
    ("Sexy Star", 1983, 2007, "wrestler", 12, 11, 18, "prima_donna", "Allrounder", 55,
     ("AAA", 2007), None,
     "Mexican wrestler who became AAA's most-pushed woman of the era and its first female headline act."),
    ("Princesa Sugehit", 1979, 2005, "wrestler", 13, 9, 16, "loyal", "Technician", 57,
     ("CMLL", 2005), None,
     "CMLL technician whose mat work anchored the promotion's women's division for two decades."),
    ("Princesa Blanca", 1976, 2005, "wrestler", 12, 9, 15, "money_hungry", "Brawler", 60,
     ("CMLL", 2005), None,
     "Reliable CMLL ruda whose hair matches were among the division's most heated."),
    ("Estrellita", 1979, 2005, "wrestler", 12, 10, 18, "loyal", "High Flyer", 54,
     ("CMLL", 2005), None,
     "Popular Mexican tecnica known for aerial work and a very long CMLL run."),
    ("Lluvia", 1987, 2006, "wrestler", 11, 9, 17, "loyal", "High Flyer", 54,
     ("CMLL", 2006), None,
     "Second-generation Mexican wrestler who came up through CMLL's women's division in the late 2000s."),
    ("Zeuxis", 1988, 2009, "wrestler", 12, 9, 16, "money_hungry", "High Flyer", 54,
     ("CMLL", 2009), None,
     "Hard-edged CMLL ruda with a fast, aggressive aerial style."),
    ("Rosa Negra", 1980, 2005, "wrestler", 10, 8, 15, "money_hungry", "Brawler", 60,
     ("CMLL", 2005), None,
     "CMLL ruda and dependable heel hand of the promotion's women's division."),
    ("Cinthia Moreno", 1979, 2005, "wrestler", 12, 9, 16, "loyal", "High Flyer", 52,
     ("CMLL", 2005), None,
     "Member of the Moreno wrestling family and a consistent CMLL tecnica of the period."),
]

# Extra ring names worth recording so a future batch matches on them instead of
# adding a duplicate under the other gimmick.
ALSO_KNOWN_AS = {
    "Sarah Stock": ["Sarita", "Dark Angel"],
    "Taryn Terrell": ["Tiffany Terrell"],
    "Britani Knight": ["Paige", "Saraya-Jade Bevis"],
    "Cherry Bomb": ["Allie"],
    "Courtney Rush": ["Rosemary"],
    "Heidi Lovelace": ["Ruby Riott"],
    "Tenille Dashwood": ["Emma"],
    "Jessie McKay": ["Billie Kay"],
    "Angela Fong": ["Savannah"],
    "Kara Drew": ["Cherry (WWE)"],
    "Brooke Adams": ["Miss Tessmacher"],
    "Alpha Female": ["Jazzy Gabert"],
    "Maryse Ouellet": ["Maryse"],
    "Layla El": ["Layla"],
    "Ivelisse Velez": ["Ivelisse"],
    "Karen Jarrett": ["Karen Angle"],
    "AJ Lee": ["April Mendez"],
    "Mia Yim": ["Jade"],
    "Athena": ["Ember Moon"],
    "Madison Rayne": ["Ashley Lane"],
    "Kelly Kelly": ["Barbie Blank"],
}


def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")

    # Match on BOTH wrestler.name and ring_name — a gimmick change is not a new
    # person, and this batch deliberately overlaps three earlier ones.
    known: dict[str, int] = {}
    for r in con.execute("SELECT id, name FROM wrestler"):
        known[r["name"].strip().casefold()] = r["id"]
    for r in con.execute("SELECT wrestler_id, name FROM ring_name"):
        known.setdefault(r["name"].strip().casefold(), r["wrestler_id"])
    banned = {r[0] for r in con.execute("SELECT wrestler_id FROM banned_wrestler")}

    added, refreshed, dupes = 0, 0, []
    for i, (name, by, dc, role, cha, pop, looks, pers, style, wt, promo, nick, bio) in enumerate(NEW):
        key = name.strip().casefold()
        if key in known:
            wid = known[key]
            _bio(con, wid, nick, bio)
            refreshed += 1
            dupes.append(name)
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
        con.execute("INSERT OR IGNORE INTO ring_name (wrestler_id, name, is_primary) VALUES (?,?,1)",
                    (wid, name))
        for alias in ALSO_KNOWN_AS.get(name, []):
            con.execute("INSERT OR IGNORE INTO ring_name (wrestler_id, name, is_primary) VALUES (?,?,0)",
                        (wid, alias))
        con.execute("INSERT OR IGNORE INTO promotion_year (wrestler_id, promotion, year, matches) "
                    "VALUES (?,?,?,0)", (wid, promo[0], promo[1]))
        con.execute("INSERT OR IGNORE INTO wrestler_state (wrestler_id) VALUES (?)", (wid,))
        con.execute(
            """INSERT INTO attribute_override (wrestler_id, draft_class, updated_at)
               VALUES (?,?,?)
               ON CONFLICT(wrestler_id) DO UPDATE SET draft_class=excluded.draft_class""",
            (wid, dc, NOW))
        _bio(con, wid, nick, bio)
        known[key] = wid
        added += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0]
    classes = con.execute(
        """SELECT COALESCE(o.draft_class, 2000) dc, COUNT(*) n
           FROM wrestler w LEFT JOIN attribute_override o ON o.wrestler_id=w.id
           GROUP BY dc ORDER BY dc""").fetchall()
    print(f"added {added}, already on roster {refreshed}")
    if dupes:
        print("  matched an existing wrestler, bio refreshed only:", ", ".join(dupes))
    print(f"roster now {total}")
    print("draft classes:", {r["dc"]: r["n"] for r in classes})
    con.close()
    return 0


def _bio(con, wid, nick, bio):
    con.execute(
        """INSERT INTO wrestler_bio (wrestler_id, nickname, bio, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(wrestler_id) DO UPDATE SET nickname=excluded.nickname,
             bio=excluded.bio, updated_at=excluded.updated_at""",
        (wid, nick, bio, NOW))


if __name__ == "__main__":
    sys.exit(main())
