#!/usr/bin/env python3
"""Builds SIXER's cricket database from Cricsheet match files.

Usage: build_db.py RAW_DIR OUT_DIR
RAW_DIR holds all_json.zip, people.csv and names.csv from cricsheet.org.
OUT_DIR receives sixer.db.gz (SQLite), summary.json and a few raw samples.

Data: Cricsheet (https://cricsheet.org), Open Data Commons Attribution License.
Full names: Wikidata (CC0), joined on the ESPNcricinfo player id.
"""
import sys, os, json, zipfile, csv, sqlite3, gzip, shutil, collections, time, urllib.request, urllib.parse

raw, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True); os.makedirs(os.path.join(out, 'samples'), exist_ok=True)
db_path = os.path.join(out, 'sixer.db')
if os.path.exists(db_path): os.remove(db_path)
con = sqlite3.connect(db_path); cur = con.cursor()
cur.executescript('''
CREATE TABLE players(pid INTEGER PRIMARY KEY, cricsheet_id TEXT, name TEXT, unique_name TEXT, full_name TEXT,
                     cricinfo TEXT, wikidata TEXT, born TEXT);
CREATE TABLE names(pid INTEGER, name TEXT, source TEXT);
CREATE TABLE teams(tid INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE matches(mid INTEGER PRIMARY KEY, file TEXT, date TEXT, year INTEGER, season TEXT, gender TEXT,
                     match_type TEXT, team_type TEXT, event TEXT, stage TEXT, match_number TEXT, venue TEXT, city TEXT,
                     team1 INTEGER, team2 INTEGER, winner INTEGER, result TEXT);
CREATE TABLE appearances(mid INTEGER, pid INTEGER, tid INTEGER, opp INTEGER, catches INTEGER, stumpings INTEGER, potm INTEGER);
CREATE TABLE batting(mid INTEGER, inns INTEGER, pid INTEGER, tid INTEGER, pos INTEGER, runs INTEGER, balls INTEGER,
                     fours INTEGER, sixes INTEGER, out INTEGER, how TEXT);
CREATE TABLE bowling(mid INTEGER, inns INTEGER, pid INTEGER, tid INTEGER, balls INTEGER, runs INTEGER, wickets INTEGER);
''')

pids, tids = {}, {}
seen_names = collections.defaultdict(set)   # cricsheet id -> names used in scorecards
def pid_of(name, reg):
    key = reg.get(name) or ('x:' + name)
    if key not in pids: pids[key] = len(pids) + 1
    seen_names[key].add(name)
    return pids[key]
def tid_of(name):
    if name is None: return None
    if name not in tids: tids[name] = len(tids) + 1
    return tids[name]

NOT_BOWLER = {'run out', 'retired hurt', 'retired out', 'retired not out', 'obstructing the field', 'timed out', 'handled the ball'}
NOT_OUT = {'retired hurt', 'retired not out'}
samples_wanted = {'Test': 1, 'ODI': 1, 'T20': 1, 'IT20': 1}
bad = 0; mid = 0
z = zipfile.ZipFile(os.path.join(raw, 'all_json.zip'))
for fn in sorted(z.namelist()):
    if not fn.endswith('.json'): continue
    try:
        blob = z.read(fn); d = json.loads(blob); info = d['info']
        reg = (info.get('registry') or {}).get('people') or {}
        teams = info.get('teams') or list((info.get('players') or {}).keys())
        if len(teams) != 2: bad += 1; continue
        mt = info.get('match_type')
        if samples_wanted.get(mt):
            samples_wanted[mt] -= 1
            open(os.path.join(out, 'samples', f'{mt}-{os.path.basename(fn)}'), 'wb').write(blob[:400000])
        mid += 1
        ev = info.get('event') or {}
        if not isinstance(ev, dict): ev = {'name': str(ev)}
        oc = info.get('outcome') or {}
        date = str((info.get('dates') or [''])[0])
        cur.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            mid, os.path.basename(fn)[:-5], date, int(date[:4]) if date[:4].isdigit() else None, str(info.get('season', '')),
            info.get('gender'), mt, info.get('team_type'), ev.get('name'), str(ev.get('stage') or ev.get('group') or '') or None,
            str(ev.get('match_number')) if ev.get('match_number') is not None else None, info.get('venue'), info.get('city'),
            tid_of(teams[0]), tid_of(teams[1]), tid_of(oc.get('winner')), oc.get('result') or ('won' if oc.get('winner') else None)))
        potm = set(info.get('player_of_match') or [])
        field = collections.defaultdict(lambda: [0, 0])
        squad = {}
        for team, plist in (info.get('players') or {}).items():
            for p in plist: squad[p] = team
        for n, inn in enumerate(d.get('innings') or [], 1):
            if inn.get('super_over'): continue
            team = inn.get('team'); other = teams[1] if team == teams[0] else teams[0]
            bat = collections.OrderedDict(); bowl = collections.OrderedDict(); how = {}
            def B(name):
                if name not in bat: bat[name] = [0, 0, 0, 0]
                return bat[name]
            for over in inn.get('overs') or []:
                for dl in over.get('deliveries') or []:
                    ex = dl.get('extras') or {}; r = dl.get('runs') or {}
                    b = B(dl['batter']); B(dl['non_striker']) if dl.get('non_striker') else None
                    rb = r.get('batter', 0); b[0] += rb
                    if 'wides' not in ex: b[1] += 1
                    if not r.get('non_boundary'):
                        if rb == 4: b[2] += 1
                        elif rb == 6: b[3] += 1
                    w = bowl.setdefault(dl['bowler'], [0, 0, 0])
                    w[1] += rb + ex.get('wides', 0) + ex.get('noballs', 0)
                    if 'wides' not in ex and 'noballs' not in ex: w[0] += 1
                    for wk in dl.get('wickets') or []:
                        kind = wk.get('kind', ''); how[wk.get('player_out')] = kind; B(wk.get('player_out'))
                        if kind not in NOT_BOWLER: w[2] += 1
                        if kind == 'caught and bowled': field[dl['bowler']][0] += 1
                        for f in wk.get('fielders') or []:
                            nm = f.get('name') if isinstance(f, dict) else f
                            if not nm: continue
                            if kind == 'caught': field[nm][0] += 1
                            elif kind == 'stumped': field[nm][1] += 1
            for pos, (name, s) in enumerate(bat.items(), 1):
                squad.setdefault(name, team)
                k = how.get(name)
                cur.execute('INSERT INTO batting VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                            (mid, n, pid_of(name, reg), tid_of(team), pos, s[0], s[1], s[2], s[3], 1 if k and k not in NOT_OUT else 0, k))
            for name, s in bowl.items():
                squad.setdefault(name, other)
                cur.execute('INSERT INTO bowling VALUES(?,?,?,?,?,?,?)', (mid, n, pid_of(name, reg), tid_of(other), s[0], s[1], s[2]))
        for name, team in squad.items():
            other = teams[1] if team == teams[0] else teams[0]
            f = field.get(name, [0, 0])
            cur.execute('INSERT INTO appearances VALUES(?,?,?,?,?,?,?)',
                        (mid, pid_of(name, reg), tid_of(team), tid_of(other), f[0], f[1], 1 if name in potm else 0))
    except Exception as e:
        bad += 1
        if bad <= 20: print('skip', fn, repr(e)[:200])
print('matches', mid, 'skipped', bad, 'players', len(pids), 'teams', len(tids))
cur.executemany('INSERT INTO teams VALUES(?,?)', [(t, n) for n, t in tids.items()])

# ---- register: ids, alternative names, ESPNcricinfo ids
people = {}
with open(os.path.join(raw, 'people.csv'), newline='', encoding='utf-8') as f:
    rd = csv.DictReader(f); people_cols = rd.fieldnames
    for row in rd: people[row.get('identifier')] = row
alt = collections.defaultdict(set)
with open(os.path.join(raw, 'names.csv'), newline='', encoding='utf-8') as f:
    rd = csv.DictReader(f); names_cols = rd.fieldnames
    for row in rd: alt[row.get('identifier')].add(row.get('name'))
for nm in ('people.csv', 'names.csv'):
    with open(os.path.join(raw, nm), encoding='utf-8') as f:
        open(os.path.join(out, 'samples', nm), 'w', encoding='utf-8').write(''.join(f.readlines()[:40]))

# ---- Wikidata: full names by ESPNcricinfo id (failure here must not stop the build)
def sparql(q):
    url = 'https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={'User-Agent': 'SixerQuizDataBuild/1.0 (https://github.com/cc81-pz/Sixer)', 'Accept': 'application/sparql-results+json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)['results']['bindings']
        except Exception as e:
            print('wikidata attempt', attempt + 1, 'failed:', repr(e)[:200]); time.sleep(10 * (attempt + 1))
    return []
wd = {}; wd_alt = collections.defaultdict(set)
for b in sparql('SELECT ?item ?cid ?label ?dob WHERE { ?item wdt:P2697 ?cid ; rdfs:label ?label . FILTER(LANG(?label)="en") OPTIONAL { ?item wdt:P569 ?dob } }'):
    cid = b['cid']['value'].strip()
    wd.setdefault(cid, (b['item']['value'].rsplit('/', 1)[-1], b['label']['value'], b.get('dob', {}).get('value', '')[:10]))
for b in sparql('SELECT ?cid ?alt WHERE { ?item wdt:P2697 ?cid ; skos:altLabel ?alt . FILTER(LANG(?alt)="en") }'):
    wd_alt[b['cid']['value'].strip()].add(b['alt']['value'])
print('wikidata players', len(wd), 'with aliases', len(wd_alt))

full = 0
for key, pid in pids.items():
    row = people.get(key) or {}
    cids = [row.get(c) for c in (people_cols or []) if c and c.startswith('key_cricinfo') and row.get(c)]
    hit = next((wd[c] for c in cids if c in wd), None)
    name = row.get('name') or sorted(seen_names[key])[0]
    cur.execute('INSERT INTO players VALUES(?,?,?,?,?,?,?,?)', (pid, None if key.startswith('x:') else key, name, row.get('unique_name'),
                hit[1] if hit else None, cids[0] if cids else None, hit[0] if hit else None, hit[2] if hit else None))
    full += 1 if hit else 0
    rows = {(n, 'scorecard') for n in seen_names[key]} | {(n, 'cricsheet') for n in alt.get(key, ())}
    for c in cids: rows |= {(n, 'wikidata') for n in wd_alt.get(c, ())}
    cur.executemany('INSERT INTO names VALUES(?,?,?)', [(pid, n, s) for n, s in rows if n])
con.commit()

# ---- summary for a quick sanity check
q = lambda s: cur.execute(s).fetchall()
summary = {
    'built': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), 'matches': mid, 'skipped_files': bad, 'players': len(pids),
    'players_with_full_name': full, 'wikidata_rows': len(wd), 'people_columns': people_cols, 'names_columns': names_cols,
    'by_type': q('SELECT match_type, gender, team_type, COUNT(*), MIN(year), MAX(year) FROM matches GROUP BY 1,2,3 ORDER BY 4 DESC'),
    'international_players_full_name': q('''SELECT m.gender, COUNT(DISTINCT p.pid), COUNT(DISTINCT CASE WHEN p.full_name IS NOT NULL THEN p.pid END)
        FROM appearances a JOIN matches m USING(mid) JOIN players p USING(pid) WHERE m.team_type='international' GROUP BY 1'''),
    'top_events': q('SELECT event, COUNT(*), MIN(year), MAX(year) FROM matches WHERE event IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 60'),
    'check_top_test_runs': q('''SELECT p.name, p.full_name, SUM(b.runs), SUM(b.runs>=100) FROM batting b JOIN matches m USING(mid) JOIN players p USING(pid)
        WHERE m.match_type='Test' AND m.gender='male' GROUP BY b.pid ORDER BY 3 DESC LIMIT 12'''),
    'check_top_odi_wkts': q('''SELECT p.name, p.full_name, SUM(w.wickets) FROM bowling w JOIN matches m USING(mid) JOIN players p USING(pid)
        WHERE m.match_type='ODI' AND m.gender='male' GROUP BY w.pid ORDER BY 3 DESC LIMIT 12'''),
}
json.dump(summary, open(os.path.join(out, 'summary.json'), 'w'), indent=1, ensure_ascii=False)
con.execute('VACUUM'); con.close()
with open(db_path, 'rb') as a, gzip.open(db_path + '.gz', 'wb', compresslevel=9) as b: shutil.copyfileobj(a, b)
os.remove(db_path)
open(os.path.join(out, 'README.md'), 'w').write('''# SIXER cricket database

Built automatically by `.github/workflows/build-data.yml`. Do not edit by hand.

- `sixer.db.gz`: SQLite database (players, names, teams, matches, appearances, batting, bowling)
- `summary.json`: counts and sanity checks from the last build

Match data: [Cricsheet](https://cricsheet.org), Open Data Commons Attribution License.
Full player names: [Wikidata](https://www.wikidata.org), CC0.
''')
print('db.gz MB', round(os.path.getsize(db_path + '.gz') / 1e6, 1))
