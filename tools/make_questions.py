#!/usr/bin/env python3
"""Writes SIXER's question bank into index.html from the cricket database.

Usage: make_questions.py sixer.db index.html [--report]
Each question is a saved rule (RECIPES) run against the database. Tiers (1/2/4/6)
come from how prominent each player is, both in that question and overall.
A few hand-written "banker" questions already in index.html are kept by id.
"""
import sqlite3, sys, json, re, unicodedata, collections

db, html = sys.argv[1], sys.argv[2]; REPORT = '--report' in sys.argv
c = sqlite3.connect(db)
def q(s, *a): return c.execute(s, a).fetchall()
c.executescript('CREATE INDEX IF NOT EXISTS a1 ON appearances(pid); CREATE INDEX IF NOT EXISTS a2 ON appearances(mid);'
                'CREATE INDEX IF NOT EXISTS b1 ON batting(mid); CREATE INDEX IF NOT EXISTS w1 ON bowling(mid); CREATE INDEX IF NOT EXISTS n1 ON names(pid);')

FM = "('India','Australia','England','Pakistan','South Africa','New Zealand','West Indies','Sri Lanka','Bangladesh','Zimbabwe','Ireland')"
# overall prominence: international caps weighted by format and recency, plus the big leagues
FAME = dict(q(f"""SELECT a.pid, SUM((CASE WHEN m.team_type='international' AND t.name IN {FM} THEN
        (CASE m.match_type WHEN 'Test' THEN 2.5 WHEN 'ODI' THEN 1.2 WHEN 'T20' THEN 1.0 ELSE 0 END)
        WHEN m.event IN ('Indian Premier League','Women''s Premier League') THEN 0.6 ELSE 0 END)
        * (CASE WHEN m.year>=2019 THEN 1.0 WHEN m.year>=2013 THEN 0.8 ELSE 0.6 END))
    FROM appearances a JOIN matches m USING(mid) JOIN teams t ON t.tid=a.tid GROUP BY a.pid"""))
PLAYER = {pid: (name, full) for pid, name, full in q('SELECT pid,name,full_name FROM players')}
NAMES = collections.defaultdict(list)
for pid, n, src in q("SELECT pid,name,source FROM names ORDER BY CASE source WHEN 'scorecard' THEN 0 WHEN 'cricsheet' THEN 1 ELSE 2 END"): NAMES[pid].append(n)

APP  = "FROM appearances a JOIN matches m USING(mid) JOIN teams t ON t.tid=a.tid JOIN teams o ON o.tid=a.opp"
BAT  = "FROM batting b JOIN matches m USING(mid) JOIN teams t ON t.tid=b.tid JOIN teams o ON o.tid=CASE WHEN m.team1=b.tid THEN m.team2 ELSE m.team1 END"
BOWL = "FROM bowling w JOIN matches m USING(mid) JOIN teams t ON t.tid=w.tid JOIN teams o ON o.tid=CASE WHEN m.team1=w.tid THEN m.team2 ELSE m.team1 END"
MEN = "m.gender='male' AND m.team_type='international'"
TEST, ODI, T20I = MEN + " AND m.match_type='Test'", MEN + " AND m.match_type='ODI'", MEN + " AND m.match_type='T20'"
IN_ENG = "m.city IN ('London','Birmingham','Leeds','Nottingham','Manchester','Southampton','Cardiff','Chester-le-Street')"
IN_AUS = ("(m.city IN ('Sydney','Melbourne','Brisbane','Adelaide','Perth','Hobart','Canberra') OR m.venue LIKE 'Adelaide Oval%' OR m.venue LIKE 'Melbourne Cricket Ground%'"
          " OR m.venue LIKE 'Sydney Cricket Ground%' OR m.venue LIKE 'Perth Stadium%' OR m.venue LIKE 'Brisbane Cricket Ground%' OR m.venue LIKE 'W%A%C%A%Ground%' OR m.venue LIKE 'Bellerive%' OR m.venue LIKE 'Manuka%')")
IN_IND = ("m.city IN ('Mumbai','Kolkata','Chennai','Delhi','Bengaluru','Bangalore','Hyderabad','Ahmedabad','Nagpur','Chandigarh','Mohali','Kanpur','Pune','Ranchi',"
          "'Indore','Rajkot','Visakhapatnam','Dharamsala','Dharamshala','Cuttack','Guwahati','Lucknow','Thiruvananthapuram','Raipur','Jaipur','Kochi','Vadodara','Gwalior')")
WC_ODI = "m.event IN ('ICC Cricket World Cup','World Cup','ICC World Cup')"
WC_T20 = "m.event IN ('ICC World Twenty20','World T20','ICC Men''s T20 World Cup')"
IPL = "m.event='Indian Premier League'"
ASHES = TEST + " AND t.name IN ('England','Australia') AND o.name IN ('England','Australia') AND m.date>='2006-11-01'"
def pl(n, w): return f"{n} {w}" if n == 1 else f"{n} {w}es" if w.endswith('match') else f"{n} {w}s"

def played(cond, unit):
    return [(pid, n + FAME.get(pid, 0) / 1e4, pl(n, unit)) for pid, n in q(f"SELECT a.pid, COUNT(*) {APP} WHERE {cond} GROUP BY a.pid")]
def scored(runs, cond, word):
    out = []
    for pid, n, best, notout in q(f"SELECT b.pid, COUNT(*), MAX(b.runs), MIN(CASE WHEN b.runs=(SELECT MAX(b2.runs) FROM batting b2 JOIN matches m2 USING(mid) WHERE b2.pid=b.pid AND b2.mid=b.mid) THEN b.out ELSE 1 END) {BAT} WHERE b.runs>=? AND {cond} GROUP BY b.pid", runs):
        out.append((pid, n + best / 1e3, (pl(n, word) + f", best {best}") if n > 1 else f"{best}"))
    return out
def took(wk, cond, word):
    out = []
    for pid, n, best in q(f"SELECT w.pid, COUNT(*), MAX(w.wickets) {BOWL} WHERE w.wickets>=? AND {cond} GROUP BY w.pid", wk):
        out.append((pid, n + best / 1e2, pl(n, word) + f", best {best} wickets" if n > 1 else f"{best} wickets"))
    return out

def wickets(cond):
    return [(pid, n, pl(n, 'wicket')) for pid, n in q(f"SELECT w.pid, SUM(w.wickets) {BOWL} WHERE {cond} GROUP BY w.pid HAVING SUM(w.wickets)>0")]

R = []   # (id, question, subtitle, rows, competition)
def add(id, question, sub, rows, event=None): R.append((id, question, sub, rows, event))
def event_fame(event):
    return dict(q("SELECT a.pid, COUNT(*)*0.8 FROM appearances a JOIN matches m USING(mid) WHERE m.event=? GROUP BY a.pid", event)) if event else {}
# Players whose fame the data understates because their peak came before it starts. Never a six.
LEGENDS = set("""Sachin Tendulkar|Ricky Ponting|Shane Warne|Adam Gilchrist|Matthew Hayden|Jacques Kallis|Muttiah Muralitharan|Rahul Dravid|VVS Laxman|Virender Sehwag|Sourav Ganguly|Brian Lara|Glenn McGrath|Anil Kumble|Kevin Pietersen|Andrew Flintoff|Justin Langer|Brett Lee|Daniel Vettori|Zaheer Khan|Harbhajan Singh|Yuvraj Singh|Gautam Gambhir|Michael Hussey|Mahela Jayawardene|Kumar Sangakkara|Sanath Jayasuriya|Shahid Afridi|Shoaib Akhtar|Inzamam-ul-Haq|Younis Khan|Graeme Smith|Shaun Pollock|Chris Gayle|Shivnarine Chanderpaul|Andrew Strauss|Michael Vaughan|Javagal Srinath|Michael Bevan|Andrew Symonds|Chris Lynn|Mithali Raj|Jhulan Goswami|Lasith Malinga|Dale Steyn|AB de Villiers|MS Dhoni""".split('|'))
# Where Wikidata's label is not the name fans use
DISPLAY_FIX = {'Mohammad Babar Azam': 'Babar Azam', 'Kushal Janith Perera': 'Kusal Perera', 'S. Sreesanth': 'Sreesanth', 'Philip Salt': 'Phil Salt',
    'Mashrafe Bin Mortaza': 'Mashrafe Mortaza', 'Thangarasu Natarajan': 'T Natarajan', 'Ravisrinivasan Sai Kishore': 'Sai Kishore', 'Subramaniam Badrinath': 'S Badrinath',
    'Vyshak Vijay Kumar': 'Vijaykumar Vyshak', 'Mehedi Hasan': 'Mehidy Hasan Miraz', 'Fahim Ashraf': 'Faheem Ashraf', 'Sahabaz Ahmed': 'Shahbaz Ahmed',
    'Akash Mandwaal': 'Akash Madhwal', 'Joshua Little': 'Josh Little', 'James Neesham': 'Jimmy Neesham', 'Lakshmipathy Balaji': 'Lakshmipathy Balaji'}

# ---- who has played for whom
for id, team, fmt, cond, y0, unit in [
    ('ind-test', 'India', 'Test', TEST, 2010, 'Test'), ('eng-test', 'England', 'Test', TEST, 2015, 'Test'), ('aus-test', 'Australia', 'Test', TEST, 2010, 'Test'),
    ('nz-test', 'New Zealand', 'Test', TEST, 2010, 'Test'), ('sa-test', 'South Africa', 'Test', TEST, 2012, 'Test'),
    ('ind-odi', 'India', 'ODI', ODI, 2015, 'ODI'), ('aus-odi', 'Australia', 'ODI', ODI, 2015, 'ODI'), ('eng-odi', 'England', 'ODI', ODI, 2015, 'ODI'),
    ('sl-odi', 'Sri Lanka', 'ODI', ODI, 2015, 'ODI'), ('ban-odi', 'Bangladesh', 'ODI', ODI, 2015, 'ODI'),
    ('ind-t20i', 'India', 'T20 international', T20I, 2020, 'T20I'), ('pak-t20i', 'Pakistan', 'T20 international', T20I, 2018, 'T20I'),
    ('wi-t20i', 'West Indies', 'T20 international', T20I, 2016, 'T20I'), ('eng-t20i', 'England', 'T20 international', T20I, 2018, 'T20I')]:
    art = 'an' if fmt == 'ODI' else 'a'
    add(id, f"Name a man who has played {art} {fmt} for {team} since {y0}", f"Men's {fmt}s from 1 January {y0}", played(f"{cond} AND t.name='{team}' AND m.year>={y0}", unit))
for id, team, fmt, cond, y0, unit in [('pak-test', 'Pakistan', 'Test', TEST, 2015, 'Test'), ('nz-odi', 'New Zealand', 'ODI', ODI, 2015, 'ODI'),
                                      ('sa-odi', 'South Africa', 'ODI', ODI, 2015, 'ODI'), ('aus-t20i', 'Australia', 'T20 international', T20I, 2018, 'T20I')]:
    art = 'an' if fmt == 'ODI' else 'a'
    add(id, f"Name a man who has played {art} {fmt} for {team} since {y0}", f"Men's {fmt}s from 1 January {y0}", played(f"{cond} AND t.name='{team}' AND m.year>={y0}", unit))

# ---- openers: broad, friendly pools for the first ball of an over
add('ind-t20wc', "Name a man who has played for India at a T20 World Cup", "Every tournament from 2007", played(f"{T20I} AND {WC_T20} AND t.name='India'", 'T20 World Cup match'))
add('aus-wc', "Name a man who has played for Australia at an ODI World Cup since 2003", "The six tournaments from 2003 to 2023", played(f"{ODI} AND {WC_ODI} AND t.name='Australia'", 'World Cup match'))
add('ind-test-100', "Name a man who has scored a Test hundred for India since 2010", "Men's Tests from 2010", scored(100, TEST + " AND t.name='India' AND m.year>=2010", 'hundred'))
add('indeng-played', "Name a player who has appeared in an India v England Test since 2018", "Either side · men's Tests from 2018", played(TEST + " AND t.name IN ('India','England') AND o.name IN ('India','England') AND m.year>=2018", 'Test'))
add('ind-test-potm', "Name an Indian who has been Player of the Match in a Test since 2010", "Men's Tests from 2010", played(TEST + " AND t.name='India' AND a.potm=1 AND m.year>=2010", 'award'))
add('ind-odi-wkt', "Name a bowler who has taken an ODI wicket for India since 2015", "Men's ODIs from 1 January 2015", wickets(ODI + " AND t.name='India' AND m.year>=2015"))
add('ashes-wkt', "Name a bowler who has taken an Ashes wicket since 2015", "England v Australia men's Tests, 2015 onwards", wickets(ASHES + " AND m.year>=2015"))
add('eng-t20i-50', "Name a man who has scored a T20 international fifty for England", "Scores of 50 or more · men's T20Is", scored(50, T20I + " AND t.name='England'", 'fifty-plus score'))

# ---- feats at a ground or in a country
add('lords-50', "Name a batter who has scored a Test fifty at Lord's since 2010", "Scores of 50 or more · men's Tests from 2010", scored(50, TEST + " AND m.venue LIKE 'Lord%' AND m.year>=2010", 'fifty-plus score'))
add('mcg-50', "Name a batter who has scored a Test fifty at the MCG since 2010", "Scores of 50 or more · men's Tests from 2010", scored(50, TEST + " AND m.venue LIKE 'Melbourne Cricket Ground%' AND m.year>=2010", 'fifty-plus score'))
add('aus-5w', "Name a bowler who has taken a Test five-for in Australia since 2010", "Five or more wickets in an innings · men's Tests from 2010", took(5, TEST + f" AND {IN_AUS} AND m.year>=2010", 'five-for'))
add('eng-5w', "Name a bowler who has taken a Test five-for in England since 2010", "Five or more wickets in an innings · men's Tests from 2010", took(5, TEST + f" AND {IN_ENG} AND m.year>=2010", 'five-for'))
add('ind-5w', "Name a bowler who has taken a Test five-for in India since 2010", "Five or more wickets in an innings · men's Tests from 2010", took(5, TEST + f" AND {IN_IND} AND m.year>=2010", 'five-for'))
add('vis-100-ind', "Name a visiting batter who has scored a Test hundred in India since 2010", "Touring batters only · men's Tests from 2010", scored(100, TEST + f" AND {IN_IND} AND t.name<>'India' AND o.name='India' AND m.year>=2010", 'hundred'))
add('vis-100-aus', "Name a visiting batter who has scored a Test hundred in Australia since 2010", "Touring batters only · men's Tests from 2010", scored(100, TEST + f" AND {IN_AUS} AND t.name<>'Australia' AND o.name='Australia' AND m.year>=2010", 'hundred'))

# ---- rivalries and opponents
add('ashes-played', "Name a player who has appeared in an Ashes Test since 2015", "England v Australia men's Tests, 2015 onwards", played(ASHES + " AND m.year>=2015", 'Ashes Test'))
add('ashes-100', "Name a batter who has scored an Ashes hundred since 2006–07", "England v Australia men's Tests, from the 2006–07 series", scored(100, ASHES, 'hundred'))
add('ashes-5w', "Name a bowler who has taken an Ashes five-for since 2006–07", "Five or more wickets in an innings · from the 2006–07 series", took(5, ASHES, 'five-for'))
add('indaus-100', "Name a batter who has scored a Test hundred in an India v Australia Test since 2010", "Either side · men's Tests from 2010", scored(100, TEST + " AND t.name IN ('India','Australia') AND o.name IN ('India','Australia') AND m.year>=2010", 'hundred'))
add('indpak', "Name a man who has played in an India v Pakistan match since 2010", "Either side · ODIs and T20 internationals from 2010", played(MEN + " AND t.name IN ('India','Pakistan') AND o.name IN ('India','Pakistan') AND m.year>=2010", 'match'))
add('100-v-ind', "Name a batter who has scored a Test hundred against India since 2010", "Men's Tests from 2010", scored(100, TEST + " AND o.name='India' AND m.year>=2010", 'hundred'))
add('5w-v-ind', "Name a bowler who has taken a Test five-for against India since 2010", "Five or more wickets in an innings · men's Tests from 2010", took(5, TEST + " AND o.name='India' AND m.year>=2010", 'five-for'))
add('ind-odi-100', "Name a man who has scored an ODI hundred for India since 2010", "Men's ODIs from 2010", scored(100, ODI + " AND t.name='India' AND m.year>=2010", 'hundred'))
add('odi-100-v-ind', "Name a batter who has scored an ODI hundred against India since 2010", "Men's ODIs from 2010", scored(100, ODI + " AND o.name='India' AND m.year>=2010", 'hundred'))
add('ind-t20i-50', "Name a man who has scored a T20 international fifty for India", "Scores of 50 or more · men's T20Is", scored(50, T20I + " AND t.name='India'", 'fifty-plus score'))
add('eng-test-100', "Name a man who has scored a Test hundred for England since 2010", "Men's Tests from 2010", scored(100, TEST + " AND t.name='England' AND m.year>=2010", 'hundred'))
add('aus-test-100', "Name a man who has scored a Test hundred for Australia since 2010", "Men's Tests from 2010", scored(100, TEST + " AND t.name='Australia' AND m.year>=2010", 'hundred'))
add('ind-test-50', "Name a man who has scored a Test fifty for India since 2015", "Scores of 50 or more · men's Tests from 2015", scored(50, TEST + " AND t.name='India' AND m.year>=2015", 'fifty-plus score'))

# ---- tournaments
add('wc-final-xi', "Name a player who has appeared in a men's ODI World Cup final since 2003", "The six finals from 2003 to 2023", played(f"{ODI} AND {WC_ODI} AND m.stage='Final'", 'final'))
add('t20wc-final-xi', "Name a player who has appeared in a men's T20 World Cup final since 2014", "Finals from 2014 onwards", played(f"{T20I} AND {WC_T20} AND m.stage='Final' AND m.year>=2014", 'final'))
add('ct-final-xi', "Name a player who has appeared in a Champions Trophy final since 2004", "Men's finals from 2004 to 2025", played(f"{ODI} AND m.event='ICC Champions Trophy' AND m.stage='Final'", 'final'))
add('ind-wc', "Name a man who has played for India at an ODI World Cup since 2011", "The 2011, 2015, 2019 and 2023 tournaments", played(f"{ODI} AND {WC_ODI} AND t.name='India' AND m.year>=2011", 'World Cup match'))
add('wtc-final', "Name a player who has appeared in a World Test Championship final", "Every final so far", played(TEST + " AND m.stage='Final'", 'final'))

# ---- leagues (one a day at most)
add('ipl-100', "Name a batter who has scored an IPL hundred", "2008 to today", scored(100, IPL, 'hundred'), 'Indian Premier League')
add('ipl-5w', "Name a bowler who has taken five wickets in an IPL innings", "2008 to today", took(5, IPL, 'five-for'), 'Indian Premier League')
add('ipl-final', "Name a player who has appeared in an IPL final since 2020", "Finals from 2020 onwards", played(IPL + " AND m.stage='Final' AND m.year>=2020", 'final'), 'Indian Premier League')
add('rcb', "Name a player who has appeared for RCB since 2020", "IPL matches from 2020 onwards", played(IPL + " AND t.name IN ('Royal Challengers Bangalore','Royal Challengers Bengaluru') AND m.year>=2020", 'match'), 'Indian Premier League')
add('mi', "Name a player who has appeared for Mumbai Indians since 2020", "IPL matches from 2020 onwards", played(IPL + " AND t.name='Mumbai Indians' AND m.year>=2020", 'match'), 'Indian Premier League')
add('csk', "Name a player who has appeared for Chennai Super Kings since 2018", "IPL matches from 2018 onwards", played(IPL + " AND t.name='Chennai Super Kings' AND m.year>=2018", 'match'), 'Indian Premier League')
add('kkr', "Name a player who has appeared for Kolkata Knight Riders since 2020", "IPL matches from 2020 onwards", played(IPL + " AND t.name='Kolkata Knight Riders' AND m.year>=2020", 'match'), 'Indian Premier League')
add('bbl-100', "Name a batter who has scored a Big Bash League hundred", "Men's BBL, 2011–12 to today", scored(100, "m.event='Big Bash League'", 'hundred'), 'Big Bash League')
add('hundred-final', "Name a player who has appeared in a men's Hundred final", "Every final since 2021", played("m.event='The Hundred Men''s Competition' AND m.stage='Final'", 'final'), "The Hundred Men's Competition")
# ==== BACKFILL: one new over a day ====
# Every recipe below is tagged (category, team) so the daily overs can be mixed.
# Overs 1-10 (GRID) are fixed; overs from 11 on are assembled from AUTO below.
TAG = {}
# Already asked in overs 1-10, in the same or a near-identical form: never generate these again.
TAKEN = {
  'test-2014': {'India', 'England', 'Australia', 'New Zealand', 'South Africa', 'Pakistan'},
  'odi-2017': {'India', 'Australia', 'England', 'Sri Lanka', 'Bangladesh', 'New Zealand', 'South Africa'},
  't20i-2020': {'India', 'Pakistan', 'West Indies', 'England', 'Australia'},
  'test-100s': {'India', 'England', 'Australia'}, 'odi-100s': {'India'}, 't20i-50s': {'India', 'England'}, 'test-50s': {'India'},
  'test-potm': {'India'}, '5w-in': {'India', 'England', 'Australia'}, 'vis100-in': {'India', 'Australia'},
  't20wc-all': {'India'}, 'wc-2011': {'India', 'Australia'}}
CODES = ['ind', 'aus', 'eng', 'pak', 'sa', 'nz', 'wi', 'sl', 'ban', 'zim', 'ire']
def family(id, cat):
    for c in CODES:
        if id.startswith(c + '-'): return id[len(c) + 1:]
        if id.endswith('-in-' + c): return id[:-len(c) - 1]
    if cat == 'ground': return 'ground-' + id.rsplit('-', 1)[1]
    return id
# Afghanistan have played Tests at these places, and the data holds no Afghanistan matches, so lists would be missing
# right answers. Questions that can be patched by hand go in EXTRA instead.
AFG_GAP = {'vis50-in-ban', 'mirpur-50', 'mirpur-wkt', 'vis50-in-sl', '5w-in-sl'}
def addt(id, cat, team, *a, **k):
    fam = family(id, cat)
    if id in {r[0] for r in R} or id in AFG_GAP or team in TAKEN.get(fam, ()): return
    add(id, *a, **k); TAG[id] = (cat, team, fam)

TEAMS = [('ind', 'India'), ('aus', 'Australia'), ('eng', 'England'), ('pak', 'Pakistan'), ('sa', 'South Africa'), ('nz', 'New Zealand'),
         ('wi', 'West Indies'), ('sl', 'Sri Lanka'), ('ban', 'Bangladesh'), ('zim', 'Zimbabwe'), ('ire', 'Ireland')]
FMT = {'Test': (TEST, 'Test', 'a Test'), 'ODI': (ODI, 'ODI', 'an ODI'), 'T20I': (T20I, 'T20I', 'a T20 international')}
def where_country(cities, venues=()):
    v = ' OR '.join(f"m.venue LIKE '{x}'" for x in venues)
    return "(m.city IN (" + ','.join("'" + c.replace("'", "''") + "'" for c in cities) + ")" + (f" OR {v}" if v else '') + ")"
COUNTRY = {
    'England': where_country(['London','Birmingham','Leeds','Nottingham','Manchester','Southampton','Cardiff','Chester-le-Street']),
    'Australia': IN_AUS, 'India': IN_IND,
    'South Africa': where_country(['Cape Town','Johannesburg','Centurion','Durban','Port Elizabeth','Gqeberha','East London','Bloemfontein','Paarl','Potchefstroom']),
    'New Zealand': where_country(['Wellington','Auckland','Christchurch','Hamilton','Dunedin','Napier','Mount Maunganui','Nelson','Queenstown']),
    'Sri Lanka': where_country(['Colombo','Galle','Kandy','Pallekele','Hambantota','Dambulla'], ['Galle%','Pallekele%']),
    'West Indies': where_country(['Antigua','North Sound','Bridgetown','Barbados','Jamaica','Kingston','Trinidad','Port of Spain','Tarouba','St Lucia','Gros Islet','Dominica','Roseau','Guyana','Providence','Grenada',"St George's",'St Kitts','Basseterre','St Vincent','Kingstown']),
    'Bangladesh': where_country(['Dhaka','Mirpur','Chittagong','Chattogram','Sylhet','Fatullah','Khulna'], ['Sylhet%']),
}

# who has played for whom
for code, team in TEAMS:
    for f, y0 in [('Test', 2014), ('ODI', 2017), ('T20I', 2020)]:
        cond, unit, _ = FMT[f]
        label = {'Test': 'a Test', 'ODI': 'an ODI', 'T20I': 'a T20 international'}[f]
        addt(f'{code}-{f.lower()}-{y0}', 'played', team, f"Name a man who has played {label} for {team} since {y0}",
             f"Men's {'T20 internationals' if f == 'T20I' else f + 's'} from 1 January {y0}", played(f"{cond} AND t.name='{team}' AND m.year>={y0}", unit))
# runs and wickets for a team
for code, team in TEAMS:
    addt(f'{code}-test-100s', 'bat', team, f"Name a man who has scored a Test hundred for {team} since 2010", "Men's Tests from 2010", scored(100, TEST + f" AND t.name='{team}' AND m.year>=2010", 'hundred'))
    addt(f'{code}-odi-100s', 'bat', team, f"Name a man who has scored an ODI hundred for {team} since 2010", "Men's ODIs from 2010", scored(100, ODI + f" AND t.name='{team}' AND m.year>=2010", 'hundred'))
    addt(f'{code}-odi-50s', 'bat', team, f"Name a man who has scored an ODI fifty for {team} since 2018", "Scores of 50 or more · men's ODIs from 2018", scored(50, ODI + f" AND t.name='{team}' AND m.year>=2018", 'fifty-plus score'))
    addt(f'{code}-test-50s', 'bat', team, f"Name a man who has scored a Test fifty for {team} since 2018", "Scores of 50 or more · men's Tests from 2018", scored(50, TEST + f" AND t.name='{team}' AND m.year>=2018", 'fifty-plus score'))
    addt(f'{code}-t20i-50s', 'bat', team, f"Name a man who has scored a T20 international fifty for {team}", "Scores of 50 or more · men's T20Is", scored(50, T20I + f" AND t.name='{team}'", 'fifty-plus score'))
    addt(f'{code}-test-5w', 'bowl', team, f"Name a bowler who has taken a Test five-for for {team} since 2010", "Five or more wickets in an innings · men's Tests from 2010", took(5, TEST + f" AND t.name='{team}' AND m.year>=2010", 'five-for'))
    addt(f'{code}-odi-4w', 'bowl', team, f"Name a bowler who has taken four wickets in an ODI innings for {team} since 2010", "Four or more in an innings · men's ODIs from 2010", took(4, ODI + f" AND t.name='{team}' AND m.year>=2010", 'four-for'))
    addt(f'{code}-t20i-3w', 'bowl', team, f"Name a bowler who has taken three wickets in a T20 international for {team}", "Three or more in an innings · men's T20Is", took(3, T20I + f" AND t.name='{team}'", 'three-for'))
    addt(f'{code}-test-wkt', 'bowl', team, f"Name a bowler who has taken a Test wicket for {team} since 2018", "Men's Tests from 1 January 2018", wickets(TEST + f" AND t.name='{team}' AND m.year>=2018"))
    addt(f'{code}-odi-wkt', 'bowl', team, f"Name a bowler who has taken an ODI wicket for {team} since 2019", "Men's ODIs from 1 January 2019", wickets(ODI + f" AND t.name='{team}' AND m.year>=2019"))
    addt(f'{code}-test-potm', 'played', team, f"Name a man who has been Player of the Match in a Test for {team} since 2010", "Men's Tests from 2010", played(TEST + f" AND t.name='{team}' AND a.potm=1 AND m.year>=2010", 'award'))
# feats in a country
for country, cond in COUNTRY.items():
    code = [c for c, t in TEAMS if t == country][0]
    addt(f'5w-in-{code}', 'bowl', country, f"Name a bowler who has taken a Test five-for in {country} since 2010", "Either side · men's Tests from 2010", took(5, TEST + f" AND {cond} AND m.year>=2010", 'five-for'))
    addt(f'vis100-in-{code}', 'bat', country, f"Name a visiting batter who has scored a Test hundred in {country} since 2010", "Touring batters only · men's Tests from 2010",
         scored(100, TEST + f" AND {cond} AND t.name<>'{country}' AND o.name='{country}' AND m.year>=2010", 'hundred'))
    addt(f'vis50-in-{code}', 'bat', country, f"Name a visiting batter who has scored a Test fifty in {country} since 2015", "Touring batters only · scores of 50 or more · men's Tests from 2015",
         scored(50, TEST + f" AND {cond} AND t.name<>'{country}' AND o.name='{country}' AND m.year>=2015", 'fifty-plus score'))
# famous grounds
GROUNDS = [('oval', 'the Oval', "m.venue LIKE 'The Oval%' OR m.venue LIKE 'Kennington Oval%'", 'England'), ('scg', 'the SCG', "m.venue LIKE 'Sydney Cricket Ground%'", 'Australia'),
           ('adelaide', 'Adelaide Oval', "m.venue LIKE 'Adelaide Oval%'", 'Australia'), ('gabba', 'the Gabba', "m.venue LIKE 'Brisbane Cricket Ground%'", 'Australia'),
           ('edgbaston', 'Edgbaston', "m.venue LIKE 'Edgbaston%'", 'England'), ('headingley', 'Headingley', "m.venue LIKE 'Headingley%'", 'England'),
           ('trentbridge', 'Trent Bridge', "m.venue LIKE 'Trent Bridge%'", 'England'), ('oldtrafford', 'Old Trafford', "m.venue LIKE 'Old Trafford%'", 'England'),
           ('newlands', 'Newlands', "m.venue LIKE 'Newlands%'", 'South Africa'), ('wanderers', 'the Wanderers', "m.venue LIKE '%Wanderers%'", 'South Africa'),
           ('centurion', 'Centurion', "m.venue LIKE 'SuperSport Park%'", 'South Africa'), ('galle', 'Galle', "m.venue LIKE 'Galle%'", 'Sri Lanka'),
           ('basin', 'the Basin Reserve', "m.venue LIKE 'Basin Reserve%'", 'New Zealand'), ('eden', 'Eden Gardens', "m.venue LIKE 'Eden Gardens%'", 'India'),
           ('ssc', 'the SSC in Colombo', "m.venue LIKE 'Sinhalese Sports Club%'", 'Sri Lanka'),
           ('kingsmead', 'Kingsmead', "m.venue LIKE 'Kingsmead%'", 'South Africa'), ('hagley', 'Hagley Oval', "m.venue LIKE 'Hagley Oval%'", 'New Zealand'),
           ('kensington', 'Kensington Oval', "m.venue LIKE 'Kensington Oval%'", 'West Indies'),
           ('mirpur', 'Mirpur', "m.venue LIKE 'Shere Bangla%' OR m.venue LIKE 'Shere Bangla National Stadium%'", 'Bangladesh'), ('perth', 'Perth', "m.city='Perth' OR m.venue LIKE 'Perth Stadium%'", 'Australia')]
for code, name, cond, country in GROUNDS:
    addt(f'{code}-50', 'ground', country, f"Name a batter who has scored a Test fifty at {name} since 2010", "Scores of 50 or more · men's Tests from 2010", scored(50, TEST + f" AND ({cond}) AND m.year>=2010", 'fifty-plus score'))
    addt(f'{code}-wkt', 'ground', country, f"Name a bowler who has taken a Test wicket at {name} since 2015", "Men's Tests from 1 January 2015", wickets(TEST + f" AND ({cond}) AND m.year>=2015"))
addt('lords-wkt', 'ground', 'England', "Name a bowler who has taken a Test wicket at Lord's since 2015", "Men's Tests from 1 January 2015", wickets(TEST + " AND m.venue LIKE 'Lord%' AND m.year>=2015"))
addt('mcg-wkt', 'ground', 'Australia', "Name a bowler who has taken a Test wicket at the MCG since 2015", "Men's Tests from 1 January 2015", wickets(TEST + " AND m.venue LIKE 'Melbourne Cricket Ground%' AND m.year>=2015"))
# World Cups
for code, team in TEAMS[:9]:
    addt(f'{code}-t20wc-all', 'tourn', team, f"Name a man who has played for {team} at a T20 World Cup", "Every tournament from 2007", played(f"{T20I} AND {WC_T20} AND t.name='{team}'", 'T20 World Cup match'))
    addt(f'{code}-wc-2011', 'tourn', team, f"Name a man who has played for {team} at an ODI World Cup since 2011", "The 2011, 2015, 2019 and 2023 tournaments", played(f"{ODI} AND {WC_ODI} AND t.name='{team}' AND m.year>=2011", 'World Cup match'))
addt('wc-100s', 'tourn', '', "Name a batter who has scored a century at a men's ODI World Cup since 2011", "The 2011, 2015, 2019 and 2023 tournaments", scored(100, f"{ODI} AND {WC_ODI} AND m.year>=2011", 'hundred'))
addt('wc-4w', 'tourn', '', "Name a bowler who has taken four wickets in a men's ODI World Cup match since 2011", "Four or more in an innings · 2011 to 2023", took(4, f"{ODI} AND {WC_ODI} AND m.year>=2011", 'four-for'))
addt('t20wc-50s', 'tourn', '', "Name a batter who has scored a fifty at a men's T20 World Cup for a Test nation", "Scores of 50 or more · every tournament from 2007", scored(50, f"{T20I} AND {WC_T20} AND t.name IN {FM}", 'fifty-plus score'))
addt('ct-played-2013', 'tourn', '', "Name a player who has appeared in a Champions Trophy semi-final or final since 2013", "Men's knockouts from 2013 to 2025", played(f"{ODI} AND m.event='ICC Champions Trophy' AND m.stage IN ('Final','Semi Final') AND m.year>=2013", 'knockout'))
# rivalries
RIV = [('engaus-odi', "an England v Australia ODI since 2015", ODI, 'England', 'Australia', 2015), ('indsa-test', "an India v South Africa Test since 2010", TEST, 'India', 'South Africa', 2010),
       ('indnz-test', "an India v New Zealand Test since 2012", TEST, 'India', 'New Zealand', 2012), ('engpak-test', "an England v Pakistan Test since 2010", TEST, 'England', 'Pakistan', 2010),
       ('indsl-odi', "an India v Sri Lanka ODI since 2015", ODI, 'India', 'Sri Lanka', 2015), ('indeng-odi', "an India v England ODI since 2015", ODI, 'India', 'England', 2015),
       ('ausnz-test', "an Australia v New Zealand Test since 2010", TEST, 'Australia', 'New Zealand', 2010), ('engsa-test', "an England v South Africa Test since 2012", TEST, 'England', 'South Africa', 2012),
       ('aussa-test', "an Australia v South Africa Test since 2012", TEST, 'Australia', 'South Africa', 2012), ('auspak-test', "an Australia v Pakistan Test since 2010", TEST, 'Australia', 'Pakistan', 2010),
       ('engwi-test', "an England v West Indies Test since 2012", TEST, 'England', 'West Indies', 2012), ('engnz-test', "an England v New Zealand Test since 2013", TEST, 'England', 'New Zealand', 2013),
       ('indwi-odi', "an India v West Indies ODI since 2015", ODI, 'India', 'West Indies', 2015), ('indban-odi', "an India v Bangladesh ODI since 2010", ODI, 'India', 'Bangladesh', 2010),
       ('pakssl-test', "a Pakistan v Sri Lanka Test since 2010", TEST, 'Pakistan', 'Sri Lanka', 2010), ('indaus-odi', "an India v Australia ODI since 2017", ODI, 'India', 'Australia', 2017)]
for id, phrase, cond, a, b, y0 in RIV:
    addt(id, 'played', f'{a}|{b}', f"Name a man who has played in {phrase}", f"Either side · men's {'Tests' if cond == TEST else 'ODIs'} from {y0}",
         played(cond + f" AND t.name IN ('{a}','{b}') AND o.name IN ('{a}','{b}') AND m.year>={y0}", 'Test' if cond == TEST else 'ODI'))
# leagues (at most one an over)
IPLT = [('srh', 'Sunrisers Hyderabad', "('Sunrisers Hyderabad')", 2020), ('rr', 'Rajasthan Royals', "('Rajasthan Royals')", 2020), ('dc', 'Delhi Capitals', "('Delhi Capitals')", 2020),
        ('pbks', 'Punjab Kings', "('Punjab Kings','Kings XI Punjab')", 2020), ('gt', 'Gujarat Titans', "('Gujarat Titans')", 2022), ('lsg', 'Lucknow Super Giants', "('Lucknow Super Giants')", 2022)]
for code, name, teams, y0 in IPLT:
    sub = 'IPL matches from 2020 onwards' if y0 == 2020 else 'Every IPL match since they joined in 2022'
    q_ = f"Name a player who has appeared for {name} since 2020" if y0 == 2020 else f"Name a player who has appeared for {name}"
    addt(code, 'league', '', q_, sub, played(IPL + f" AND t.name IN {teams} AND m.year>={y0}", 'match'), 'Indian Premier League')
addt('ipl-playoff-50', 'league', '', "Name a batter who has scored a fifty in an IPL playoff or final", "Qualifiers, eliminators and finals, 2008 to today", scored(50, IPL + " AND m.stage IS NOT NULL", 'fifty-plus score'), 'Indian Premier League')
addt('ipl-4w-2020', 'league', '', "Name a bowler who has taken four wickets in an IPL innings since 2020", "Four or more in an innings · 2020 onwards", took(4, IPL + " AND m.year>=2020", 'four-for'), 'Indian Premier League')
addt('psl-100', 'league', '', "Name a batter who has scored a Pakistan Super League hundred", "2016 to today", scored(100, "m.event='Pakistan Super League'", 'hundred'), 'Pakistan Super League')
addt('cpl-100', 'league', '', "Name a batter who has scored a Caribbean Premier League hundred", "2013 to today", scored(100, "m.event='Caribbean Premier League'", 'hundred'), 'Caribbean Premier League')
addt('sa20-played', 'league', '', "Name a player who has appeared in an SA20 final", "Every final since 2023", played("m.event='SA20' AND m.stage='Final'", 'final'), 'SA20')
addt('bbl-4w', 'league', '', "Name a bowler who has taken four wickets in a Big Bash League innings", "Men's BBL, 2011–12 to today", took(4, "m.event='Big Bash League'", 'four-for'), 'Big Bash League')

# ---- names, aliases, tiers
# Nicknames and everyday spellings fans type. Short ones are allowed here; clashes inside a question are still dropped.
NICK = {'James Anderson': ['Jimmy Anderson', 'Jimmy'], 'AB de Villiers': ['ABD', 'AB', 'Abraham de Villiers'], 'Yuvraj Singh': ['Yuvi'], 'MS Dhoni': ['MSD', 'Mahi', 'Mahendra Singh Dhoni', 'Thala'],
    'Rohit Sharma': ['Hitman'], 'Ravichandran Ashwin': ['R Ashwin', 'Ash'], 'Ravindra Jadeja': ['Jaddu', 'Sir Jadeja'], 'Suryakumar Yadav': ['SKY', 'Surya'], 'KL Rahul': ['Lokesh Rahul', 'K L Rahul'],
    'Steve Smith': ['Steven Smith', 'Smudge'], 'Brendon McCullum': ['Baz'], 'Michael Hussey': ['Mike Hussey', 'Mr Cricket'], 'Matthew Hayden': ['Matt Hayden'], 'Shikhar Dhawan': ['Gabbar'],
    'Harbhajan Singh': ['Bhajji'], 'Virender Sehwag': ['Viru'], 'Sourav Ganguly': ['Dada'], 'Kumar Sangakkara': ['Sanga'], 'Jonny Bairstow': ['Jonathan Bairstow', 'YJB'],
    'Mohammed Shami': ['Mohammad Shami'], 'Mohammed Siraj': ['Mohammad Siraj', 'Miyan'], 'Phil Salt': ['Philip Salt'], 'Jimmy Neesham': ['James Neesham'], 'Josh Little': ['Joshua Little'],
    'Mitchell Starc': ['Mitch Starc'], 'Mitchell Marsh': ['Mitch Marsh'], 'Mitchell Johnson': ['Mitch Johnson'], 'Mitchell Santner': ['Mitch Santner'], 'Pat Cummins': ['Patrick Cummins'],
    'Nathan Lyon': ['Garry', 'Gazza'], 'Glenn Maxwell': ['Maxi', 'Big Show'], 'David Warner': ['Dave Warner'], 'Babar Azam': ['Babar', 'Mohammad Babar Azam'], 'Shaheen Afridi': ['Shaheen Shah Afridi', 'Shaheen'],
    'Shakib Al Hasan': ['Shakib'], 'Mushfiqur Rahim': ['Mushfiq'], 'Mehidy Hasan Miraz': ['Mehidy Hasan', 'Mehedi Hasan Miraz', 'Miraz', 'Mehedi Hasan'], 'Mashrafe Mortaza': ['Mashrafe', 'Mashrafe Bin Mortaza'],
    'Kusal Perera': ['Kusal Janith Perera', 'KJP'], 'T Natarajan': ['Natarajan', 'Thangarasu Natarajan'], 'Sreesanth': ['S Sreesanth'], 'Bhuvneshwar Kumar': ['Bhuvi'], 'Yuzvendra Chahal': ['Yuzi'],
    'Jasprit Bumrah': ['Boom Boom'], 'Dinesh Karthik': ['DK'], 'Quinton de Kock': ['QDK', 'de Kock'], 'Faf du Plessis': ['Faf'], 'Kagiso Rabada': ['KG', 'KG Rabada'], 'Kevin Pietersen': ['KP'],
    'Alastair Cook': ['Alistair Cook'], 'Andre Russell': ['Dre Russ'], 'Sai Kishore': ['R Sai Kishore'], 'S Badrinath': ['Badrinath', 'Subramaniam Badrinath'], 'Vijaykumar Vyshak': ['Vyshak'],
    'Faheem Ashraf': ['Fahim Ashraf'], 'Shahbaz Ahmed': ['Shahbaz Ahamad'], 'Akash Madhwal': ['Madhwal'], 'Sachin Tendulkar': ['Master Blaster'], 'Virat Kohli': ['King Kohli', 'Cheeku'],
    'Chris Gayle': ['Universe Boss'], 'Lasith Malinga': ['Slinga'], 'Ben Stokes': ['Stokesy'], 'Hardik Pandya': ['Kung Fu Pandya'], 'Rishabh Pant': ['Spidey'], 'Washington Sundar': ['Washi'],
    'Cheteshwar Pujara': ['Che Pujara', 'Puji'], 'Ajinkya Rahane': ['Jinks'], 'Ishant Sharma': ['Lambu'], 'Travis Head': ['Trav Head'], 'Marnus Labuschagne': ['Marnus'], 'Usman Khawaja': ['Uzzie'],
    'Smriti Mandhana': ['Smriti'], 'Harmanpreet Kaur': ['Harman'], 'Jemimah Rodrigues': ['Jemi'], 'Shafali Verma': ['Shefali Verma']}
def norm(s):
    s = unicodedata.normalize('NFD', s.lower()); s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace('&', ' and '); s = re.sub(r"['’]", '', s); s = re.sub(r'[^a-z0-9 ]', ' ', s); s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^the ', '', s); return re.sub(r'\b([a-z]) (?=[a-z]\b)', r'\1', s)
def display(pid): name, full = PLAYER[pid]; return DISPLAY_FIX.get(full or name, full or name)

def build(id, question, sub, rows, event=None):
    ef = event_fame(event); fame = lambda pid: FAME.get(pid, 0) + ef.get(pid, 0)
    best = {}
    for pid, metric, note in rows:                      # two database ids for one person: keep the stronger row
        d = display(pid)
        if d not in best or metric > best[d][1]: best[d] = (pid, metric, note)
    items = [(d, *v) for d, v in best.items()]; n = len(items)
    by_metric = {d: i for i, (d, *_ ) in enumerate(sorted(items, key=lambda x: -x[2]))}
    by_fame = {d: i for i, (d, *_ ) in enumerate(sorted(items, key=lambda x: -fame(x[1])))}
    items.sort(key=lambda x: 0.55 * by_metric[x[0]] + 0.45 * by_fame[x[0]])
    n1 = max(2, round(.10 * n)); n2 = max(2, round(.20 * n)); n4 = round(.40 * n)
    toks = collections.Counter(t for d, *_ in items for t in set(norm(d).split()))
    names_norm = {norm(d) for d, *_ in items}
    ans = []
    for i, (d, pid, metric, note) in enumerate(items):
        tier = 1 if i < n1 else 2 if i < n1 + n2 else 4 if i < n1 + n2 + n4 else 6
        if tier == 6 and (d in LEGENDS or by_fame[d] < .25 * n): tier = 4     # a household name is never a six
        al, seen = [], {norm(d)}
        nick = NICK.get(d, [])
        for a in nick + NAMES.get(pid, []):
            k = norm(a)
            if not k or k in seen or k in names_norm or len(a) > 26 or len(k.split()) > 4 or not re.match(r"^[A-Za-z .'\-]+$", a): continue
            if len(k.split()) == 1 and ((len(k) < 4 and a not in nick) or toks[k] - (1 if k in norm(d).split() else 0) > 0): continue
            seen.add(k); al.append(a)
            if len(al) == 4 + len(nick): break
        ans.append([d, tier, al, note, pid])
    owner = collections.defaultdict(set)
    for a in ans:
        for x in a[2]: owner[norm(x)].add(a[0])
    for a in ans: a[2] = [x for x in a[2] if len(owner[norm(x)]) == 1]
    return {'id': id, 'q': question, 's': sub, 'a': ans}

QS = {r[0]: build(*r) for r in R}
# Right answers the database cannot see (Cricsheet holds no Afghanistan matches). [name, tier, aliases, note]
EXTRA = {'odi-100-v-ind': [['Mohammad Shahzad', 6, ['Shahzad', 'Mohammad Shahzad Mohammadi'], '124 in the tied Asia Cup match, 2018']],
         'vis100-in-ban': [['Rahmat Shah', 6, ['Rahmat'], "102 at Chattogram, 2019: Afghanistan's first Test hundred"]],
         '5w-in-ban': [['Rashid Khan', 4, ['Rashid'], '11 wickets in the match at Chattogram, 2019']],
         'vis100-in-sl': [['Ibrahim Zadran', 6, ['Ibrahim'], '114 at the SSC, 2024']]}
for k, rows in EXTRA.items():
    have = {a[0] for a in QS[k]['a']}
    QS[k]['a'] += [r + [None] for r in rows if r[0] not in have]
if REPORT:
    nofull = collections.Counter()
    for k, v in QS.items():
        a = v['a']; t = collections.Counter(x[1] for x in a)
        print(f"\n{k}: {len(a)} answers  tiers {dict(sorted(t.items()))}\n   1s: " + ', '.join(x[0] for x in a if x[1] == 1)[:230] +
              "\n   2s: " + ', '.join(x[0] for x in a if x[1] == 2)[:200] + "\n   6s: " + ', '.join(f"{x[0]} ({x[3]})" for x in a if x[1] == 6)[-330:])
        for x in a:
            if x[4] and not PLAYER[x[4]][1]: nofull[x[0]] += 1
    print('\nNO FULL NAME:', dict(nofull))
    print('WTC finals:', q("SELECT date,venue FROM matches m WHERE " + TEST + " AND m.stage='Final'"))
    print('India-involved Tests since 2010 not counted as in India (city):', q(f"SELECT m.city,COUNT(*) FROM matches m JOIN teams a ON a.tid=m.team1 JOIN teams b ON b.tid=m.team2 WHERE {TEST} AND m.year>=2010 AND (a.name='India' OR b.name='India') AND NOT ({IN_IND}) GROUP BY 1"))
    print('Tests since 2010 with no city:', q(f"SELECT m.venue,COUNT(*) FROM matches m WHERE {TEST} AND m.year>=2010 AND m.city IS NULL GROUP BY 1"))
    print('finals found:', [(k, q(f"SELECT COUNT(DISTINCT m.mid) {APP} WHERE {cnd}")[0][0]) for k, cnd in [('wc', f"{ODI} AND {WC_ODI} AND m.stage='Final'"), ('t20wc', f"{T20I} AND {WC_T20} AND m.stage='Final' AND m.year>=2014"), ('ct', f"{ODI} AND m.event='ICC Champions Trophy' AND m.stage='Final'"), ('ipl', IPL + " AND m.stage='Final' AND m.year>=2020"), ('hundred', "m.event='The Hundred Men''s Competition' AND m.stage='Final'"), ('wpl', "m.event='Women''s Premier League' AND m.stage='Final'")]])
    sys.exit()

BANKERS = []   # ids of hand-written questions to keep from index.html (none at present)
GRID = [['ind-t20wc', 'ind-test', 'lords-50', 'ipl-100', 'wc-final-xi', '100-v-ind'],
        ['pak-test', 'aus-odi', 'ashes-100', 'bbl-100', 'ind-t20i', 'eng-5w'],
        ['ind-test-100', 'eng-test', 'odi-100-v-ind', 'rcb', 't20wc-final-xi', 'aus-5w'],
        ['indeng-played', 'ind-odi', 'vis-100-aus', 'ipl-5w', 'ashes-played', 'sa-test'],
        ['aus-wc', 'pak-t20i', 'mcg-50', 'mi', 'ct-final-xi', 'ind-test-50'],
        ['ind-test-potm', 'nz-test', '5w-v-ind', 'ipl-final', 'indpak', 'eng-odi'],
        ['ashes-wkt', 'aus-test', 'ind-odi-100', 'csk', 'wtc-final', 'wi-t20i'],
        ['ind-odi-wkt', 'sl-odi', 'vis-100-ind', 'eng-t20i-50', 'ind-wc', 'eng-test-100'],
        ['nz-odi', 'ban-odi', 'indaus-100', 'kkr', 'ashes-5w', 'ind-t20i-50'],
        ['sa-odi', 'eng-t20i', 'ind-5w', 'hundred-final', 'aus-test-100', 'aus-t20i']]
# ---- overs 11 onwards, one a day, built from the tagged recipes
import random
def pool_ok(k, lo=22, hi=150): return lo <= len(QS[k]['a']) <= hi
used = {k for r in GRID for k in r}
cand = [k for k in TAG if k not in used and pool_ok(k)]
rnd = random.Random(2026)
rnd.shuffle(cand)
by = collections.defaultdict(list)
for k in cand: by[TAG[k][0]].append(k)
def teams_of(k): return set(t for t in TAG[k][1].split('|') if t)
OBSCURE = {'Zimbabwe', 'Ireland'}
for c_ in list(by): by[c_] = [k for k in by[c_] if not (teams_of(k) & OBSCURE)]
AUTO = []
league_turn = 0
while True:
    over, tms, fams = [], collections.Counter(), set()
    def take(cats, opener=False):
        for cat in cats:
            for k in by[cat]:
                if opener and len(QS[k]['a']) < 45: continue
                if any(tms[t] >= 1 for t in teams_of(k)): continue
                if TAG[k][2] in fams: continue
                by[cat].remove(k); over.append(k); tms.update(teams_of(k)); fams.add(TAG[k][2]); return True
        return False
    ok = take(['played', 'ground'], opener=True)
    ok = ok and take(['bat', 'ground'])
    ok = ok and take(['bowl', 'ground'])
    league_turn += 1
    ok = ok and (take(['league']) if league_turn % 2 == 0 and by['league'] else take(['tourn', 'ground', 'played']))
    ok = ok and take(['tourn', 'bat', 'ground', 'played'])
    ok = ok and take(['bowl', 'bat', 'ground', 'played'])
    if not ok: break
    AUTO.append(over)
GRID = GRID + AUTO
print('auto overs:', len(AUTO), '| left over:', {c: len(v) for c, v in by.items()}, '| dropped for pool size:', sorted(k for k in TAG if k not in used and not pool_ok(k)))
page = open(html, encoding='utf-8').read()
start = page.index('const OVERS = ['); end = page.index('\n];\n', start) + 4
old = page[start:end]
banker_src = {}
for m in re.finditer(r'\{id:"([^"]+)".*?\]\]\}', old, re.S):
    if m.group(1) in BANKERS: banker_src[m.group(1)] = m.group(0)
missing = [b for b in BANKERS if b not in banker_src]
assert not missing, f'banker questions not found in index.html: {missing}'
J = lambda v: json.dumps(v, ensure_ascii=False, separators=(',', ':'))
def js(qd):
    a = ',\n   '.join(J([x[0], x[1], x[2], x[3]]) for x in qd['a'])
    return f"{{id:{J(qd['id'])}, q:{J(qd['q'])}, s:{J(qd['s'])}, people:true, gen:true, a:[\n   {a}]}}"
out = ['const OVERS = [']
for i, row in enumerate(GRID, 1):
    out.append(f' [ // ---------- OVER {i} ----------\n  ' + ',\n  '.join(banker_src[k] if k in banker_src else js(QS[k]) for k in row) + '\n ]' + (',' if i < len(GRID) else ''))
out.append('];\n')
open(html, 'w', encoding='utf-8').write(page[:start] + '\n'.join(out) + page[end:])
used = {k for r in GRID for k in r}
print('written', len(GRID), 'overs;', sum(len(QS[k]['a']) for k in used if k in QS), 'generated answers; unused recipes:', sorted(set(QS) - used))
