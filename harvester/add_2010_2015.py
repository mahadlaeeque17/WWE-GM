"""Add the 2010-2015 women's class — everyone ACTIVE in that window, not just debutantes.

Run:  python add_2010_2015.py [../data/gm2000.db] [--dry]

Idempotent. Matching is by name against every existing `wrestler.name` AND every
`ring_name`, so a wrestler already on the roster under a different gimmick is
skipped rather than duplicated. That check does real work here: the roster already
carries 270 women including a great many who WERE active 2010-2015 under earlier
names — Paige is here as Britani Knight, Asuka as Kana, Ruby Riott as Heidi
Lovelace, Rosemary as Courtney Rush, Emma as Tenille Dashwood, Billie Kay as
Jessie McKay, Ember Moon as Athena, Allie as Cherry Bomb. None of them is added
again; the alias is recorded instead.

New wrestlers get synthetic ids from 900301 up. Batch 1 used 900001-900026,
batches 2/3 used 900101-900197 and batch 4 used 900201-900297, so the ranges
cannot collide, and a synthetic id can never collide with a real cagematch id.

DRAFT CLASS. `draft_class` is the season she enters the draft pool, and the game
resets to January 2000. Someone whose relevance here is her 2012 run cannot be
given a 2003 class — those seasons are already gone. So:

    draft_class = clamp(real arrival / prominence year, 2010, 2015)

which keeps this batch inside the window asked for and leaves the already-
populated 2000-2010 classes alone.

PROMOTIONS ARE ERA-CORRECT. AEW did not exist until 2019 and NJPW had no women's
division in this window, so nobody is filed under either. Where a wrestler later
became an AEW or WWE name the BIO says so — that is the honest place for it,
because "Thunder Rosa, AEW" in 2013 is simply false, whereas "who she became" is
useful to a GM reading the panel.

RATINGS ARE ON THE FIVE-CATEGORY SCALE, each out of 20:

    wrestling   a hand read on in-ring ability. Supplied per wrestler rather
                than derived, because these women have no cagematch rows at all —
                the whole reason the migration had to curate 110 of the existing
                roster by hand. Doing it at insert time avoids adding 100 more
                names to that list.
    popularity  star power in the 2010-2015 window, NOT what she became later.
                Sasha Banks in 2013 was an NXT rookie, and rating her on 2016
                fame would drop a main-eventer into a game that starts in 2000.
    looks       a starting point, expected to be hand-edited. It always was.
    personal    left at the neutral default for every single one of them, because
                it is yours and nothing here has any business guessing it.
    achievements NOT SET, and not settable — it is computed from what she wins in
                your save. Everyone in this batch starts on zero like everyone else.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attributes as A  # noqa: E402

NOW = datetime.now(timezone.utc).isoformat()
BASE_ID = 900_301

# name, birth_year, draft_class, role, wrestling, popularity, looks, personality,
# style, weight_kg, (promotion, year), nickname, bio
NEW = [
    # ------------------------------------------------- WWE / NXT / FCW 2010-2015
    ("Charlotte Flair", 1986, 2013, "wrestler", 16, 15, 17, "prima_donna", "Allrounder", 65,
     ("WWE", 2013), "The Queen",
     "Ric Flair's daughter, a college volleyball player who arrived in NXT in 2013 and turned second-generation "
     "expectation into the most decorated women's career of the era."),
    ("Sasha Banks", 1992, 2012, "wrestler", 17, 15, 16, "ambitious", "Technician", 51,
     ("WWE", 2012), "The Boss",
     "Boston-raised Chikara indie graduate whose NXT run with Bayley and Charlotte redefined what a women's "
     "match could headline."),
    ("Becky Lynch", 1987, 2013, "wrestler", 16, 14, 16, "ambitious", "Technician", 61,
     ("WWE", 2013), "The Irish Lass Kicker",
     "Dublin wrestler who debuted in 2002, toured Europe and Japan, retired to become a stunt performer, then "
     "came back through NXT and outgrew everyone."),
    ("Bayley", 1989, 2012, "wrestler", 16, 14, 15, "loyal", "Allrounder", 57,
     ("WWE", 2012), "The Hugger",
     "San Jose indie worker whose earnest babyface act carried the most emotionally effective women's matches "
     "NXT ever ran."),
    ("Alexa Bliss", 1991, 2013, "both", 11, 13, 18, "prima_donna", "High Flyer", 45,
     ("WWE", 2013), "Five Feet of Fury",
     "Ohio bodybuilder and college athlete who arrived as a fairy-tale babyface and found herself as a "
     "genuinely nasty little heel."),
    ("Carmella", 1987, 2013, "both", 10, 12, 17, "money_hungry", "Allrounder", 54,
     ("WWE", 2013), "The Princess of Staten Island",
     "Former NBA dancer and daughter of wrestler Paul Van Dale, who leaned all the way into a Staten Island "
     "gimmick nobody else could have carried."),
    ("Dana Brooke", 1989, 2013, "wrestler", 8, 9, 16, "ambitious", "Powerhouse", 61,
     ("WWE", 2013), None,
     "IFBB figure competitor out of Cleveland brought in on physique, who spent the era visibly learning the "
     "job in public."),
    ("Nia Jax", 1984, 2014, "wrestler", 11, 11, 11, "prima_donna", "Powerhouse", 122,
     ("WWE", 2014), "The Irresistible Force",
     "Samoan-Australian of the Anoa'i family, signed in 2014 as a genuine super-heavyweight in a division that "
     "had never booked one."),
    ("Eva Marie", 1984, 2013, "manager", 4, 11, 17, "money_hungry", "Allrounder", 54,
     ("WWE", 2013), "All Red Everything",
     "Californian model signed straight onto television for Total Divas, whose in-ring inexperience became the "
     "gimmick itself."),
    ("Summer Rae", 1983, 2011, "both", 8, 11, 17, "prima_donna", "Allrounder", 61,
     ("WWE", 2011), None,
     "Former Lingerie Football League player and trained dancer, used mostly as a valet whose height and "
     "presence did the work."),
    ("Lana", 1985, 2013, "manager", 6, 13, 17, "money_hungry", "Allrounder", 54,
     ("WWE", 2013), "The Ravishing Russian",
     "Florida dancer and actress whose ice-cold fake-Soviet mouthpiece act got more heat than most of the "
     "wrestlers she managed."),
    ("Renee Young", 1985, 2012, "manager", 3, 11, 16, "loyal", "Allrounder", 54,
     ("WWE", 2012), None,
     "Toronto broadcaster who became the most capable interviewer and panel host the company had, and the "
     "first woman to call its play-by-play."),
    ("Ariane Andrew", 1987, 2011, "both", 5, 9, 15, "ambitious", "Allrounder", 52,
     ("WWE", 2011), "Cameron",
     "Los Angeles dancer who arrived through Tough Enough as half of the Funkadactyls and stayed on television "
     "for five years."),
    ("JoJo Offerman", 1993, 2013, "manager", 3, 7, 15, "ambitious", "Allrounder", 50,
     ("WWE", 2013), None,
     "Iowa-born singer signed at nineteen for Total Divas who found her real footing as a ring announcer."),
    ("Nikki Storm", 1994, 2012, "wrestler", 15, 10, 13, "ambitious", "Brawler", 54,
     ("ICW", 2012), "The Best in the Galaxy",
     "Glasgow wrestler out of the ICW boom whose unhinged intensity later made her Nikki Cross and Nikki A.S.H."),
    ("Cassie McIntosh", 1992, 2011, "wrestler", 13, 10, 16, "prima_donna", "Technician", 54,
     ("PWA", 2011), "KC Cassidy",
     "Sydney wrestler trained alongside Madison Eagles and Jessie McKay, later WWE's Peyton Royce."),
    ("Liv Morgan", 1994, 2014, "wrestler", 8, 9, 17, "ambitious", "High Flyer", 48,
     ("WWE", 2014), None,
     "New Jersey athlete signed in 2014 with almost no ring experience, who grew into the job entirely inside "
     "the company."),
    ("Mandy Rose", 1990, 2015, "both", 6, 10, 18, "money_hungry", "Powerhouse", 54,
     ("WWE", 2015), "God's Greatest Creation",
     "Connecticut fitness competitor who came second on Tough Enough in 2015 and was signed anyway."),
    ("Sonya Deville", 1993, 2015, "wrestler", 11, 9, 14, "ambitious", "Brawler", 61,
     ("WWE", 2015), None,
     "Florida MMA fighter and Tough Enough finalist whose amateur striking background gave her a shoot-style "
     "edge the division lacked."),
    ("Demi Bennett", 1996, 2013, "wrestler", 12, 8, 15, "ambitious", "Powerhouse", 62,
     ("RCW", 2013), None,
     "Adelaide teenager who debuted at seventeen on the South Australian circuit, later WWE's Rhea Ripley."),
    ("Karlee Perez", 1986, 2010, "both", 8, 8, 16, "prima_donna", "Allrounder", 57,
     ("WWE", 2010), "Maxine",
     "Miami-born model who ran Florida developmental as a scheming authority figure and later worked lucha "
     "as Catrina."),
    ("Shaul Guerrero", 1990, 2011, "both", 8, 9, 15, "loyal", "Technician", 54,
     ("WWE", 2011), "Raquel Diaz",
     "Daughter of Eddie Guerrero and Vickie, who worked Florida developmental carrying a surname heavier than "
     "most careers."),
    ("Audrey Marie", 1990, 2011, "wrestler", 7, 6, 15, "ambitious", "Allrounder", 54,
     ("WWE", 2011), None,
     "North Carolina model turned developmental wrestler, a fixture of the early NXT women's division."),
    ("Devin Taylor", 1988, 2013, "manager", 3, 5, 14, "loyal", "Allrounder", 52,
     ("WWE", 2013), None,
     "Backstage interviewer through the NXT boom years, on camera for most of the era's biggest angles."),
    ("Aliyah", 1997, 2015, "wrestler", 8, 5, 15, "ambitious", "High Flyer", 52,
     ("WWE", 2015), None,
     "Toronto wrestler signed at eighteen, one of the longest-serving members of the NXT women's roster."),
    ("Sara Lee", 1985, 2015, "wrestler", 5, 4, 14, "loyal", "Allrounder", 54,
     ("WWE", 2015), None,
     "Michigan athlete who won the 2015 revival of Tough Enough and trained at the Performance Center."),
    ("Deonna Purrazzo", 1994, 2014, "wrestler", 15, 9, 15, "ambitious", "Technician", 54,
     ("SHIMMER", 2014), "The Virtuosa",
     "New Jersey technician who came up through SHIMMER and the east-coast indies as one of the most "
     "fundamentally sound workers of her generation."),

    # -------------------------------------------------------- TNA Knockouts 2010-2015
    ("Thea Trinidad", 1990, 2010, "both", 12, 9, 16, "ambitious", "High Flyer", 52,
     ("TNA", 2010), "Rosita",
     "Queens-born wrestler who debuted in TNA at twenty as half of the Mexican America tag team, later AEW's "
     "Zelina Vega."),
    ("Lei'D Tapa", 1988, 2013, "wrestler", 9, 6, 12, "money_hungry", "Powerhouse", 84,
     ("TNA", 2013), None,
     "Tongan second-generation wrestler, daughter of King Tonga, used as an imposing enforcer in the Knockouts "
     "division."),
    ("Rebel", 1979, 2014, "both", 6, 6, 16, "prima_donna", "Allrounder", 54,
     ("TNA", 2014), None,
     "Texan dancer and fitness model who arrived as a valet and stayed in wrestling for over a decade."),
    ("Alisha Edwards", 1989, 2015, "both", 7, 5, 14, "loyal", "Allrounder", 54,
     ("TNA", 2015), None,
     "Massachusetts performer who came in alongside her husband Eddie and grew into a real utility hand."),

    # ----------------------------- ROH / SHIMMER / SHINE / US indies 2010-2015
    ("Candice LeRae", 1989, 2010, "wrestler", 17, 12, 15, "ambitious", "High Flyer", 50,
     ("PWG", 2010), "The Poison Pixie",
     "Riverside wrestler who spent the era working — and beating — men in PWG, and was one of the best pure "
     "workers on the American indies full stop."),
    ("Nicole Matthews", 1989, 2010, "wrestler", 16, 9, 13, "money_hungry", "Technician", 57,
     ("SHIMMER", 2010), None,
     "Vancouver technician and half of the Canadian NINJAs, a SHIMMER champion with a deserved reputation for "
     "hurting people."),
    ("Mandy Leon", 1991, 2011, "both", 8, 7, 17, "prima_donna", "Allrounder", 54,
     ("ROH", 2011), None,
     "New York model who became Ring of Honor's most-used woman in an era when the company barely booked any."),
    ("Tessa Blanchard", 1995, 2014, "wrestler", 15, 9, 16, "prima_donna", "Technician", 54,
     ("WSU", 2014), None,
     "Third-generation wrestler, daughter of Tully Blanchard, whose in-ring ability arrived far ahead of her "
     "years on the indies."),
    ("Thunder Rosa", 1986, 2014, "wrestler", 15, 9, 15, "ambitious", "Brawler", 57,
     ("WOW", 2014), "La Mera Mera",
     "Tijuana-born, California-based wrestler who came up through WOW and the lucha circuit, later an AEW "
     "world champion."),
    ("Britt Baker", 1991, 2015, "wrestler", 12, 8, 16, "prima_donna", "Allrounder", 54,
     ("SHIMMER", 2015), None,
     "Pittsburgh wrestler who trained while qualifying as a dentist, and became one of AEW's defining acts."),
    ("Jordynne Grace", 1996, 2013, "wrestler", 15, 8, 14, "ambitious", "Powerhouse", 68,
     ("SHIMMER", 2013), "Thicc Mama Pump",
     "Texan powerlifter who debuted at seventeen and combined genuine strength with a far better technical "
     "base than the physique suggested."),
    ("Priscilla Kelly", 1997, 2014, "wrestler", 11, 7, 16, "ambitious", "High Flyer", 52,
     ("SHINE", 2014), None,
     "Georgia wrestler who debuted at seventeen with a deliberately unsettling act built to get under an "
     "audience's skin."),
    ("Barbi Hayden", 1992, 2011, "wrestler", 12, 7, 15, "money_hungry", "Allrounder", 54,
     ("NWA", 2011), None,
     "Texan who held the NWA World Women's Championship and worked most of the southern independent circuit."),
    ("Reby Sky", 1986, 2010, "both", 8, 8, 17, "money_hungry", "Allrounder", 52,
     ("WSU", 2010), None,
     "New York model and musician who worked the north-east indies and TNA, mostly in valet roles."),
    ("Tomoka Nakagawa", 1983, 2010, "wrestler", 15, 8, 13, "loyal", "Brawler", 57,
     ("SHIMMER", 2010), None,
     "Japanese veteran of NEO and JWP who became a SHIMMER regular and one of its most reliable hands."),
    ("Vanessa Kraven", 1985, 2010, "wrestler", 12, 6, 11, "money_hungry", "Powerhouse", 91,
     ("SHIMMER", 2010), "The Mountain",
     "Montreal super-heavyweight who worked intergender matches across Quebec and the SHIMMER roster."),
    ("Xandra Bale", 1990, 2012, "wrestler", 10, 5, 15, "ambitious", "High Flyer", 52,
     ("SHINE", 2012), None,
     "Florida-based wrestler and SHINE regular through the promotion's opening years."),
    ("Kellyanne English", 1988, 2011, "wrestler", 12, 6, 14, "prima_donna", "Brawler", 57,
     ("PWA", 2011), None,
     "Melbourne wrestler and a mainstay of the Australian scene throughout the era."),
    ("Crazy Mary Dobson", 1994, 2012, "wrestler", 12, 6, 13, "ambitious", "Hardcore", 57,
     ("SHIMMER", 2012), None,
     "Minnesota wrestler with a deliberately deranged gimmick, later WWE's Sarah Logan."),
    ("Nicole Savoy", 1990, 2014, "wrestler", 15, 6, 14, "money_hungry", "Technician", 57,
     ("SHIMMER", 2014), "The Queen of Suplexes",
     "Bay Area technician trained in catch wrestling, whose entire offence was built on throwing people."),
    ("Chelsea Green", 1991, 2014, "both", 11, 8, 16, "prima_donna", "Allrounder", 54,
     ("SHIMMER", 2014), None,
     "Victoria, BC wrestler trained by Lance Storm, later TNA's Laurel Van Ness and a WWE champion."),
    ("Taya Valkyrie", 1983, 2010, "wrestler", 14, 10, 17, "money_hungry", "Powerhouse", 61,
     ("AAA", 2010), "La Wera Loca",
     "Victoria-born wrestler who became a genuine main-event star in AAA and the longest-reigning Reina de "
     "Reinas of the era."),
    ("Kylie Rae", 1993, 2015, "wrestler", 13, 7, 15, "loyal", "Technician", 54,
     ("AAW", 2015), None,
     "Chicago-area wrestler whose relentlessly sunny babyface act stood out on a very cynical indie scene."),
    ("Leah Von Dutch", 1990, 2013, "wrestler", 9, 5, 15, "prima_donna", "Allrounder", 54,
     ("SHINE", 2013), None,
     "Canadian wrestler who worked SHINE and the American indies through the middle of the decade."),
    ("Holidead", 1986, 2010, "wrestler", 12, 6, 13, "money_hungry", "Brawler", 61,
     ("SHINE", 2010), None,
     "Californian wrestler with a long-running occult gimmick, a fixture of SHINE and WOW."),
    ("Jessie Belle Smothers", 1988, 2010, "both", 10, 5, 15, "prima_donna", "Allrounder", 54,
     ("OVW", 2010), None,
     "Second-generation wrestler out of Tennessee who worked OVW and the southern circuit for the whole decade."),
    ("Aerial Monroe", 1990, 2013, "wrestler", 11, 5, 15, "ambitious", "High Flyer", 52,
     ("SHIMMER", 2013), None,
     "Michigan wrestler who worked SHIMMER and the midwest indies through the middle of the decade."),
    ("Kiera Hogan", 1995, 2015, "wrestler", 12, 7, 15, "ambitious", "High Flyer", 50,
     ("SHINE", 2015), "The Girl on Fire",
     "Atlanta wrestler who debuted in 2015 and moved quickly onto the national indie circuit."),
    ("Faye Jackson", 1990, 2013, "wrestler", 10, 5, 12, "loyal", "Powerhouse", 91,
     ("SHINE", 2013), None,
     "Virginia wrestler whose comic timing and body type both stood out in a division short of either."),
    ("Kalamity", 1989, 2010, "wrestler", 13, 6, 13, "money_hungry", "Brawler", 61,
     ("SHIMMER", 2010), None,
     "Quebec wrestler and ECCW regular who became a SHIMMER mainstay."),
    ("KC Spinelli", 1985, 2010, "wrestler", 12, 6, 14, "prima_donna", "Brawler", 57,
     ("SHIMMER", 2010), None,
     "Toronto wrestler who worked SHIMMER, SHINE and the Canadian circuit throughout the era."),
    ("Hania the Huntress", 1989, 2011, "wrestler", 11, 5, 14, "ambitious", "Brawler", 57,
     ("SHINE", 2011), None,
     "Indigenous-Canadian wrestler who worked the Ontario scene and SHINE with a warrior gimmick."),

    # ------------------------------------------------------- UK / Europe 2010-2015
    ("Kay Lee Ray", 1993, 2011, "wrestler", 16, 10, 14, "money_hungry", "High Flyer", 54,
     ("ICW", 2011), None,
     "Glasgow wrestler who worked a genuinely reckless high-flying style across ICW and Progress and became "
     "the defining NXT UK women's champion."),
    ("Nixon Newell", 1994, 2013, "wrestler", 14, 8, 15, "loyal", "High Flyer", 52,
     ("ATTACK!", 2013), "The Welsh Dragon",
     "Welsh wrestler who came up through the British boom and was one of its most popular babyfaces, later "
     "WWE's Tegan Nox."),
    ("Viper", 1990, 2011, "wrestler", 15, 9, 12, "money_hungry", "Powerhouse", 100,
     ("ICW", 2011), None,
     "Scottish super-heavyweight with startling agility for her size, later Piper Niven."),
    ("Pollyanna", 1994, 2012, "wrestler", 13, 7, 14, "ambitious", "High Flyer", 52,
     ("Pro-Wrestling: EVE", 2012), None,
     "English wrestler and Pro-Wrestling: EVE regular through the period the British women's scene took off."),
    ("Dahlia Black", 1989, 2011, "wrestler", 12, 5, 14, "prima_donna", "Allrounder", 54,
     ("Pro-Wrestling: EVE", 2011), None,
     "New Zealand-born wrestler based in Britain, a regular across the UK circuit."),
    ("Kasey Owens", 1994, 2012, "wrestler", 10, 5, 14, "loyal", "Allrounder", 54,
     ("ICW", 2012), None,
     "Scottish wrestler out of the ICW school, part of the generation that made the promotion a phenomenon."),
    ("Sammii Jayne", 1993, 2012, "wrestler", 12, 5, 13, "ambitious", "Brawler", 54,
     ("Pro-Wrestling: EVE", 2012), None,
     "English wrestler who worked EVE and the northern circuit throughout the era."),
    ("Alex Windsor", 1988, 2010, "wrestler", 13, 5, 14, "money_hungry", "Technician", 57,
     ("Pro-Wrestling: EVE", 2010), None,
     "London wrestler and one of the longest-serving hands on the British women's scene."),
    ("Nina Samuels", 1988, 2013, "both", 11, 5, 16, "prima_donna", "Allrounder", 54,
     ("Pro-Wrestling: EVE", 2013), None,
     "English wrestler and actress whose self-obsessed heel character ran for the better part of a decade."),

    # ------------------------------------------- Stardom / Japan 2010-2015
    ("Mayu Iwatani", 1993, 2011, "wrestler", 17, 11, 15, "loyal", "High Flyer", 50,
     ("Stardom", 2011), "The Icon of Stardom",
     "Shimane native who joined Stardom at its founding as its least likely prospect and became the single "
     "most important wrestler in its history."),
    ("Kairi Hojo", 1988, 2012, "wrestler", 17, 12, 16, "ambitious", "High Flyer", 54,
     ("Stardom", 2012), "The Pirate Princess",
     "Former competitive sailor from Hikari whose elbow strikes and diving elbow drop made her Stardom's "
     "breakout star, later WWE's Kairi Sane."),
    ("Yoshiko", 1993, 2011, "wrestler", 14, 8, 11, "money_hungry", "Powerhouse", 90,
     ("Stardom", 2011), None,
     "Stardom original and heavyweight ace of its early years, whose career there ended in 2015 after a "
     "notorious unprotected shoot incident."),
    ("Act Yasukawa", 1988, 2012, "wrestler", 13, 9, 15, "prima_donna", "Brawler", 54,
     ("Stardom", 2012), None,
     "Fiercely charismatic Stardom heel whose run was cut short by injury, remembered for her promos as much "
     "as her matches."),
    ("Takumi Iroha", 1996, 2013, "wrestler", 15, 7, 15, "ambitious", "Allrounder", 61,
     ("Stardom", 2013), None,
     "Stardom trainee who became one of the best pure athletes of her generation and later Marvelous' ace."),
    ("Momo Watanabe", 1999, 2015, "wrestler", 14, 7, 15, "ambitious", "Technician", 52,
     ("Stardom", 2015), "The Queen",
     "Debuted at fifteen and was carrying main events before she was twenty."),
    ("Kris Wolf", 1985, 2014, "wrestler", 11, 7, 13, "loyal", "Brawler", 54,
     ("Stardom", 2014), None,
     "American who moved to Japan to teach English, fell into Stardom, and became one of its most beloved "
     "comedy-brawler acts."),
    ("Konami", 1997, 2015, "wrestler", 13, 6, 14, "ambitious", "Technician", 52,
     ("Stardom", 2015), None,
     "Shoot-style-influenced wrestler who came out of the Reina and Stardom systems as a submission specialist."),
    ("Hiromi Mimura", 1993, 2015, "wrestler", 9, 5, 14, "loyal", "Allrounder", 50,
     ("Stardom", 2015), None,
     "Stardom rookie of the mid-decade, cast as the perennial plucky underdog."),
    ("Koguma", 1998, 2014, "wrestler", 11, 5, 13, "loyal", "High Flyer", 45,
     ("Stardom", 2014), None,
     "Debuted at sixteen in Stardom's junior division with a bear gimmick and a surprisingly stiff dropkick."),
    ("Natsuko Tora", 1996, 2015, "wrestler", 11, 5, 12, "money_hungry", "Powerhouse", 68,
     ("Stardom", 2015), None,
     "Stardom trainee who grew into the promotion's most convincing bully heel."),
    ("Yuzuki Aikawa", 1985, 2011, "wrestler", 12, 11, 17, "prima_donna", "Allrounder", 54,
     ("Stardom", 2011), None,
     "Established Japanese gravure idol who took up wrestling at twenty-six and was Stardom's biggest "
     "mainstream draw until she retired in 2015."),
    ("Hikari Minami", 1994, 2011, "wrestler", 11, 5, 14, "loyal", "High Flyer", 50,
     ("Stardom", 2011), None,
     "Stardom original from its first trainee class, a fixture of its opening four years."),
    ("Cassandra Miyagi", 1993, 2015, "wrestler", 12, 5, 12, "money_hungry", "Hardcore", 61,
     ("Stardom", 2015), None,
     "Deathmatch-influenced wrestler who brought a genuinely unpleasant streak to the Stardom undercard."),
    ("Rin Kadokura", 1997, 2015, "wrestler", 12, 5, 14, "ambitious", "Technician", 52,
     ("Marvelous", 2015), None,
     "Trained by Chigusa Nagayo at Marvelous, one of the most technically polished of the mid-decade rookies."),
    ("Miyako Matsumoto", 1985, 2010, "wrestler", 11, 7, 13, "prima_donna", "Allrounder", 52,
     ("Ice Ribbon", 2010), None,
     "Ice Ribbon's resident comedy heel and self-promoter, who ran her own shows and never stopped talking."),
    ("Risa Sera", 1993, 2012, "wrestler", 14, 7, 13, "money_hungry", "Hardcore", 57,
     ("Ice Ribbon", 2012), None,
     "Ice Ribbon regular who became one of the best deathmatch wrestlers in Japan."),
    ("Maki Narumiya", 1993, 2011, "wrestler", 13, 6, 15, "loyal", "High Flyer", 50,
     ("Ice Ribbon", 2011), None,
     "Ice Ribbon high flyer of the early 2010s, later known as Maki Ito's contemporary on the Tokyo scene."),
    ("Hamuko Hoshi", 1984, 2010, "wrestler", 12, 6, 12, "loyal", "Powerhouse", 75,
     ("Ice Ribbon", 2010), None,
     "Long-serving Ice Ribbon veteran whose comic timing anchored the promotion for years."),
    ("Tsukushi", 1997, 2011, "wrestler", 13, 6, 13, "ambitious", "High Flyer", 40,
     ("Ice Ribbon", 2011), None,
     "Debuted at thirteen and spent the decade as one of the smallest and most fearless workers in Japan."),
    ("AKINO", 1979, 2010, "wrestler", 15, 8, 13, "money_hungry", "Technician", 57,
     ("OZ Academy", 2010), None,
     "GAEA graduate and OZ Academy mainstay, a hard-hitting veteran throughout the window."),
    ("Kaho Kobayashi", 1993, 2011, "wrestler", 14, 6, 14, "loyal", "High Flyer", 48,
     ("OZ Academy", 2011), None,
     "Freelance Tokyo wrestler who worked nearly every Joshi promotion of the era."),
    ("Miyu Yamashita", 1996, 2013, "wrestler", 15, 8, 15, "ambitious", "Brawler", 52,
     ("TJPW", 2013), "The Ace",
     "Tokyo Joshi Pro's founding ace, whose kicks were the most credible offence in the promotion."),
    ("Yuka Sakazaki", 1994, 2013, "wrestler", 14, 8, 15, "ambitious", "High Flyer", 50,
     ("TJPW", 2013), "The Magical Girl",
     "Tokyo Joshi Pro original who combined an idol presentation with a genuinely quick, inventive style."),
    ("Shoko Nakajima", 1994, 2013, "wrestler", 14, 7, 13, "loyal", "High Flyer", 45,
     ("TJPW", 2013), "The Big Kaiju",
     "Tokyo Joshi Pro founder-generation wrestler, tiny and relentless, with a monster-movie gimmick."),
    ("Moeka Haruhi", 1988, 2010, "wrestler", 12, 6, 14, "loyal", "Allrounder", 54,
     ("WAVE", 2010), None,
     "Pro Wrestling WAVE regular through the first half of the decade."),
    ("Sareee", 1997, 2014, "wrestler", 15, 7, 14, "ambitious", "Technician", 52,
     ("Diana", 2014), None,
     "Trained at Diana by Kyoko Inoue, an old-school Joshi throwback who debuted at sixteen."),
    ("Rina Yamashita", 1994, 2014, "wrestler", 14, 6, 13, "money_hungry", "Hardcore", 61,
     ("OZ Academy", 2014), None,
     "Deathmatch specialist who spent the era working the hardest end of the Japanese independent scene."),

    # ---------------------------------------------------- CMLL / AAA 2010-2015
    ("Dalys la Caribena", 1986, 2010, "wrestler", 13, 7, 15, "money_hungry", "Powerhouse", 61,
     ("CMLL", 2010), None,
     "Cuban-born CMLL wrestler and one of the promotion's most consistently used rudas of the decade."),
    ("Goya Kong", 1989, 2011, "wrestler", 10, 6, 11, "loyal", "Powerhouse", 100,
     ("CMLL", 2011), None,
     "Third-generation luchadora of the Alvarado family, a CMLL super-heavyweight."),
    ("Silueta", 1990, 2012, "wrestler", 13, 6, 15, "ambitious", "High Flyer", 54,
     ("CMLL", 2012), None,
     "CMLL technica of the mid-decade, part of the promotion's push to rebuild its women's division."),
    ("Reyna Isis", 1993, 2013, "wrestler", 12, 5, 15, "ambitious", "High Flyer", 54,
     ("CMLL", 2013), None,
     "CMLL luchadora who came up through the promotion's own school in the early 2010s."),
    ("La Jarochita", 1993, 2012, "wrestler", 13, 6, 15, "loyal", "High Flyer", 52,
     ("CMLL", 2012), None,
     "Veracruz-born CMLL technica and a mainstay of its women's division for over a decade."),
]

# Extra ring names worth recording, so a later batch matches on them instead of
# adding a duplicate under the other gimmick. This is the mechanism that stopped
# this batch re-adding eight wrestlers already on the roster.
ALSO_KNOWN_AS = {
    "Charlotte Flair": ["Charlotte", "Ashley Fliehr"],
    "Sasha Banks": ["Mercedes Kaestner-Varnado", "Mercedes Mone"],
    # The one that matters: she is ALREADY on this roster as Rebecca Knox.
    "Becky Lynch": ["Rebecca Knox", "Rebecca Quin", "The Man"],
    "Bayley": ["Davina Rose", "Pamela Martinez"],
    "Alexa Bliss": ["Lexi Kaufman"],
    "Carmella": ["Leah Van Dale"],
    "Dana Brooke": ["Ashley Mae Sebera"],
    "Nia Jax": ["Lina Fanene", "Savelina Fanene"],
    "Eva Marie": ["Natalie Nelson"],
    "Summer Rae": ["Danielle Moinet"],
    "Lana": ["CJ Perry", "CJ Lana Perry"],
    "Ariane Andrew": ["Cameron", "Cameron Lynn"],
    "Nikki Storm": ["Nikki Cross", "Nikki A.S.H.", "Nicola Glencross"],
    "Cassie McIntosh": ["Peyton Royce", "KC Cassidy", "Cassie Lee"],
    "Liv Morgan": ["Gionna Daddio"],
    "Mandy Rose": ["Amanda Saccomanno"],
    "Sonya Deville": ["Daria Berenato"],
    "Demi Bennett": ["Rhea Ripley"],
    "Karlee Perez": ["Maxine", "Catrina", "Salina de la Renta"],
    "Shaul Guerrero": ["Raquel Diaz"],
    "Deonna Purrazzo": ["The Virtuosa"],
    "Thea Trinidad": ["Rosita", "Zelina Vega", "Divina Fly"],
    "Candice LeRae": ["Candice Wrestling", "Candice Gargano"],
    "Thunder Rosa": ["Melissa Cervantes", "Kobra Moon"],
    "Deonna Purrazzo": ["Deonna"],
    "Jordynne Grace": ["Jordynne"],
    "Tessa Blanchard": ["Tessa"],
    "Priscilla Kelly": ["Gigi Dolin", "Priscilla"],
    "Kylie Rae": ["Kylie"],
    "Nicole Savoy": ["Savoy"],
    "Holidead": ["Holi Dead"],
    "AKINO": ["Akino"],
    "Sareee": ["Saree"],
    "Yoshiko": ["Yoshiko Hasegawa", "Act Yasukawa opponent"],
    "Act Yasukawa": ["Act"],
    "Takumi Iroha": ["Iroha"],
    "Momo Watanabe": ["Momo"],
    "Konami": ["Konami (wrestler)"],
    "Risa Sera": ["Sera"],
    "Maki Narumiya": ["Maki"],
    "Tsukushi": ["Tsukushi Haruka"],
    "Miyu Yamashita": ["Yamashita"],
    "Yuka Sakazaki": ["Sakazaki"],
    "Shoko Nakajima": ["Nakajima"],
    "Silueta": ["La Silueta"],
    "La Jarochita": ["Jarochita"],
    "Goya Kong": ["Goya"],
    "Reyna Isis": ["Isis"],
    "Britt Baker": ["Dr. Britt Baker"],
    "Chelsea Green": ["Laurel Van Ness"],
    "Taya Valkyrie": ["Kira", "Franky Monet", "Taya", "Kira Valkyrie"],
    "Crazy Mary Dobson": ["Sarah Logan", "Sarah Rowe", "Valhalla"],
    "Kay Lee Ray": ["Alba Fyre"],
    "Nixon Newell": ["Tegan Nox"],
    "Viper": ["Piper Niven", "Doudrop"],
    "Kairi Hojo": ["Kairi Sane", "Kaori Housako"],
    "Mayu Iwatani": ["The Icon"],
    "Reby Sky": ["Reby Hardy"],
    "Kiera Hogan": ["The Girl on Fire"],
    "Dalys la Caribena": ["Dalys", "Dalys la Caribeña"],
    "Miyu Yamashita": ["Yamashita"],
    "Nicole Matthews": ["Canadian NINJA"],
}

# Everyone in this batch who was ALREADY on the roster under an earlier name. Kept
# as an explicit list rather than discovered silently, because "did it skip her or
# did it never look?" is the question you actually want answered after a run.
EXPECTED_ALREADY_HERE = (
    "Paige (Britani Knight)", "Asuka (Kana)", "Emma (Tenille Dashwood)",
    "Ruby Riott (Heidi Lovelace)", "Rosemary (Courtney Rush)",
    "Allie (Cherry Bomb)", "Billie Kay (Jessie McKay)", "Ember Moon (Athena)",
    "Natalya (Nattie Neidhart)", "Angelina Love (Angel Williams)",
    "Velvet Sky (Talia Madison)", "Tara (Victoria)", "Sarita (Sarah Stock)",
    "Io Shirai", "Toni Storm", "Evie", "Mia Yim (Jade)", "Santana Garrett",
)


def main(dbpath: Path, dry: bool = False) -> int:
    if not dbpath.exists():
        print(f"no database at {dbpath}")
        return 2
    con = sqlite3.connect(dbpath)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")

    cols = {r[1] for r in con.execute("PRAGMA table_info(attributes)")}
    if "wrestling" not in cols:
        print("this save is still on the four-category ratings.\n"
              "  Run migrate_ratings.py first — otherwise every wrestler added here\n"
              "  would need her ratings rewritten by the migration afterwards.")
        return 2

    # Match on BOTH wrestler.name and ring_name — a gimmick change is not a new
    # person, and this batch deliberately overlaps five earlier ones.
    known: dict[str, int] = {}
    for r in con.execute("SELECT id, name FROM wrestler"):
        known[r["name"].strip().casefold()] = r["id"]
    for r in con.execute("SELECT wrestler_id, name FROM ring_name"):
        known.setdefault(r["name"].strip().casefold(), r["wrestler_id"])
    banned = {r[0] for r in con.execute("SELECT wrestler_id FROM banned_wrestler")}

    added, dupes, skipped = 0, [], []
    for i, row in enumerate(NEW):
        (name, by, dc, role, wrs, pop, looks, pers, style, wt, promo, nick, bio) = row

        # Match on the incoming wrestler's ALIASES as well as her name, which the
        # earlier batch scripts did not do — and it matters. Becky Lynch is already
        # on this roster as Rebecca Knox, the name she actually used on the indies
        # in 2002-2006; checking only "Becky Lynch" would have added her twice, with
        # the two halves of one career then drafted onto opposing brands.
        aliases = [name] + list(ALSO_KNOWN_AS.get(name, []))
        hit = next((known[a.strip().casefold()] for a in aliases
                    if a.strip().casefold() in known), None)
        if hit is not None:
            wid = hit
            if not dry:
                # Record the aliases we know that she does not have yet, so the
                # next batch matches on any of them.
                for alias in aliases:
                    con.execute("INSERT OR IGNORE INTO ring_name "
                                "(wrestler_id, name, is_primary) VALUES (?,?,0)",
                                (wid, alias))
                    known.setdefault(alias.strip().casefold(), wid)
                _bio(con, wid, nick, bio)
            existing = con.execute("SELECT name FROM wrestler WHERE id=?", (wid,)).fetchone()
            dupes.append(f"{name} (already here as {existing['name']})"
                         if existing and existing["name"] != name else name)
            continue
        wid = BASE_ID + i
        if wid in banned:
            skipped.append(name)
            continue
        if dry:
            added += 1
            for alias in aliases:
                known.setdefault(alias.strip().casefold(), wid)
            continue

        age = A.RESET_YEAR - by
        con.execute(
            """INSERT INTO wrestler (id, name, birthday, birth_year, age_at_reset, age_precision,
                 birthplace, height_cm, weight_kg, rating, votes, adj_rating,
                 career_start, career_end, style, harvested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (wid, name, None, by, age, "year_only", None, None, wt, None, None, None,
             str(promo[1]), "present", style, NOW))
        con.execute(
            """INSERT INTO attributes (wrestler_id, wrestling, popularity, looks, personal,
                 availability, role, role_source, personality, formula_ver)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (wid, wrs, pop, looks, A.PERSONAL_DEFAULT, "active_2000", role, None,
             pers, A.FORMULA_VERSION))
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
        for alias in aliases:
            known.setdefault(alias.strip().casefold(), wid)
        added += 1

    if not dry:
        con.commit()

    print(f"{'would add' if dry else 'added'} {added}, already on roster {len(dupes)}")
    if dupes:
        print("  matched an existing wrestler, bio refreshed only:", ", ".join(dupes))
    if skipped:
        print("  banned, not added:", ", ".join(skipped))
    print("\n  deliberately NOT re-added — already here under an earlier name:")
    print("   ", ", ".join(EXPECTED_ALREADY_HERE))

    total = con.execute("SELECT COUNT(*) FROM wrestler").fetchone()[0]
    classes = con.execute(
        """SELECT COALESCE(o.draft_class, 2000) dc, COUNT(*) n
           FROM wrestler w LEFT JOIN attribute_override o ON o.wrestler_id=w.id
           GROUP BY dc ORDER BY dc""").fetchall()
    print(f"\nroster now {total}")
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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(Path(args[0] if args else "../data/gm2000.db"),
                  dry="--dry" in sys.argv[1:]))
