"""Live rocket launcher test for the Arma Reforger Maps field map (github.com/whopops/arma-map).

rockettest.py flew the game's rockets by launching them directly. This fires them the way a player does: a soldier
carrying the launcher (the game's own AT soldiers) stands on a cliff above the sea on Everon, zeroes the sight, raises
the weapon, aims and pulls the trigger (Scripts/Game/RMT/RMT_LauncherTest.c, flag -rmtLauncher). It checks the three
things the site's rocket calculator assumes but rockettest.py couldn't show:

  1. sights   how far each sight line sits above the bore at each zeroing mark (the site takes the prefabs'
              SightRangeInfo Angles), and which point of the PGO-7 reticle is the bore (the site takes the cross)
  2. launch   how a fired rocket leaves the tube against the bore: speed, a fixed offset (the M72's 0.5 deg spawn
              angle) and the weapon's own scatter (DispersionRange, not measured anywhere yet)
  3. hits     the calculator's own shots, fired through the weapon in still air and in wind: how far each passes
              from its target

  python launchertest.py plan              write the plan into the game profile
  python launchertest.py run               plan, then run the game (Steam running, the game closed); ~30 min
  python launchertest.py score [folder]    the three reports

Over the sea nothing gets in the way and every shot flies to its target distance; the target is a point in the air
D m out on the bearing, H m above the muzzle, and a shot's miss is read off its recorded flight where it is D m out.
"""
import argparse, collections, csv, json, math, os, random, statistics, sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
import firetest, rocketfit

WORLD = '{55A3176BBDD01AAE}worlds/Eden/EmptyEden.ent'  # Everon's terrain with nothing on it (blasttest.py)
OUT_REL = 'rmt/launchertest'
CHAR = 'Prefabs/Characters/Factions/'
# the launchers as soldiers carry them: soldier prefab, the rocket it's loaded with, the sight in use
LAUNCHERS = {
    'RPG-7 iron': (CHAR + 'INDFOR/FIA/Character_FIA_AT.et', 'RPG-7', 'PG-7VM', 'iron'),
    'RPG-7 PGO-7': (CHAR + 'OPFOR/USSR_Army/Character_USSR_AT.et', 'RPG-7', 'PG-7VM', 'pgo7'),
    'M72A3': (CHAR + 'BLUFOR/US_Army/Character_US_LAT.et', 'M72A3', 'M72A3', 'iron'),
    'RPG-22': (CHAR + 'OPFOR/USSR_Army/Character_USSR_LAT.et', 'RPG-22', 'PG-22', 'iron'),
    'RPG-75': (CHAR + 'INDFOR/FIA/Character_FIA_LAT.et', 'RPG-75', 'RPG-75', 'iron'),
}
ROUNDS = 4                 # rounds per aim (each by a fresh soldier): enough to see the weapon's scatter
WINDY = (8, 90)            # one crosswind check per launcher: m/s, and the compass direction it blows from
SPOT_GAP = 150             # m between firing spots


def cliff_spots(n, seed=5):
    """Places to stand 8-60 m above the sea on level footing, with a bearing that has open sea from 40 to 900 m out."""
    ter = firetest.Terrain()
    rnd = random.Random(seed)
    out = []
    for _ in range(400000):
        x, z = rnd.uniform(300, 12500), rnd.uniform(300, 12500)
        g = ter.ground(x, z)
        if not 8 <= g <= 60 or any(math.hypot(x - a, z - b) < SPOT_GAP for a, b, _ in out):
            continue
        if max(abs(ter.ground(x + dx, z + dz) - g) for dx, dz in ((2, 0), (-2, 0), (0, 2), (0, -2))) > 0.4:
            continue
        for az in range(0, 360, 15):
            s, c = math.sin(math.radians(az)), math.cos(math.radians(az))
            if all(ter.ground(x + s * d, z + c * d) <= 0 for d in range(40, 901, 20)):
                out.append((x, z, az))
                break
        if len(out) == n:
            return out
    raise SystemExit(f'only {len(out)} cliff spots found')


def make_plan():
    """Sights-only lines (every zeroing mark of every launcher), then fired aims: each launcher at each of its marks
    in still air (the calculator's elevation for a level target at that range), and once in a crosswind."""
    from blasttest import prefab_name
    J = json.load(open(os.path.join(REPO, 'out', 'rockets.json')))
    rows = []

    def add(kind, name, zero, D, H, wind, count):
        soldier, l, r, sight = LAUNCHERS[name]
        R, spawn = J['rockets'][r], J['launchers'][l]['spawn']
        if kind == 'sights':
            el, side = 0.0, 0.0
        else:
            ws, wf = wind
            # the shot is fired on bearing az (set per spot below); wind given relative to it: from 90 = from the right
            w = (-ws * math.cos(math.radians(wf)), ws * math.sin(math.radians(wf)))
            s = rocketfit.aim(R, D, H, w)
            if not s:
                return
            el, side = s[0] - spawn, s[1]  # the bore: the rocket leaves `spawn` degrees above it
        rows.append({'id': f'L{len(rows):03d}', 'kind': kind, 'launcher': name, 'soldier': prefab_name(soldier),
                     'rocket': r, 'zero': zero, 'D': D, 'H': H, 'el': el, 'off': -math.degrees(math.atan2(side, D)) if D else 0,
                     'wspeed': wind[0], 'wfrom_rel': wind[1], 'count': count})

    for name, (soldier, l, r, sight) in LAUNCHERS.items():
        marks = sorted(int(k) for k in J['launchers'][l]['sights']['iron']) if sight == 'iron' else [0]
        for i, _ in enumerate(marks):
            add('sights', name, i, 0, 0, (0, 0), 0)
        for i, m in enumerate(marks):
            if sight == 'pgo7':
                for D in (200, 300, 400):
                    add('fire', name, 0, D, 0.0, (0, 0), ROUNDS)
            else:
                add('fire', name, i, m, 0.0, (0, 0), ROUNDS)
        mid = 300 if sight == 'pgo7' else marks[len(marks) // 2]
        add('fire', name, 0 if sight == 'pgo7' else marks.index(mid), mid, 0.0, WINDY, ROUNDS)
    spots = cliff_spots(len(rows))
    for r, (x, z, az) in zip(rows, spots):
        r['x'], r['z'], r['az'] = x, z, az
        r['wfrom'] = (az + r['wfrom_rel']) % 360  # the wind's compass direction, from where this shot is fired
    # still air first, then the windy lines (one wind change, one settle)
    rows.sort(key=lambda r: r['wspeed'] > 0)
    return rows


def game_dir():
    from rmtlib.steam import Install
    return os.path.join(Install(None).game_profile, *OUT_REL.split('/'), 'launcher')


def write_plan(rows):
    d = game_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'plan.csv'), 'w', newline='') as f:
        f.write('id,soldier,launcher,x,z,az,el,zero,count,wspeed,wdir,stance\n')
        for r in rows:
            az = (r['az'] + r['off']) % 360  # the aim-off for the wind
            f.write(f"{r['id']},{r['soldier']},,{r['x']:.2f},{r['z']:.2f},{az:.4f},{r['el']:.4f},{r['zero']},{r['count']},"
                    f"{r['wspeed']},{(r['wfrom'] + 180) % 360 if r['wspeed'] else 0},0\n")
    json.dump(rows, open(os.path.join(d, 'plan.json'), 'w'), indent=1)
    print(f"plan: {len(rows)} aims, {sum(r['count'] for r in rows)} rockets -> {d}")


def run():
    from rmtlib.steam import Install
    from rmtlib.labselection import runner as lab_runner
    write_plan(make_plan())
    code, lines, status = lab_runner(Install(None)).run_game('launchertest', OUT_REL, WORLD, flag='-rmtLauncher',
                                                         stall=300, limit=5400)
    print('exit', code, 'status', status)


# --- score ---------------------------------------------------------------------------------------------------------
def vec(r, p):
    return [float(r[p + k]) for k in 'xyz']


def unit(v):
    n = math.sqrt(sum(a * a for a in v)) or 1
    return [a / n for a in v]


def az_el(v):
    v = unit(v)
    return math.degrees(math.atan2(v[0], v[2])), math.degrees(math.asin(max(-1, min(1, v[1]))))


def wrap(a):
    return (a + 180) % 360 - 180


def score(d):
    plan = {p['id']: p for p in json.load(open(os.path.join(d, 'plan.json')))}
    J = json.load(open(os.path.join(REPO, 'out', 'rockets.json')))
    shots = list(csv.DictReader(open(os.path.join(d, 'shots.csv'), newline='')))
    trajs = collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(d, 'traj.csv'), newline='')):
        trajs[(r['id'], r['round'])].append(r)

    print('1. sights: each reading of the sight line against the bore (deg up, deg right), and what the site takes')
    for s in shots:
        p = plan[s['id']]
        if p['kind'] != 'sights':
            continue
        soldier, l, r, sight = LAUNCHERS[p['launcher']]
        baz, bel = az_el(vec(s, 'b'))
        site = (sorted(J['launchers'][l]['sights']['iron'].items(), key=lambda kv: int(kv[0]))[p['zero']]
                if sight == 'iron' else ('PGO-7 cross', 0.0))
        out = []
        for name, pre in (('rear-front', 'sd'), ('transform', 'st'), ('zeroing', 'z')):
            v = vec(s, pre)
            if not any(v):
                continue
            a, e = az_el(v)
            # the bore above the sight line: what a mark's Angles should be
            out.append(f'{name} {bel - e:+.3f} up {wrap(baz - a):+.3f} right')
        print(f"  {p['launcher']:12s} zero {p['zero']} (reads {float(s['zero']):g}), site {site[0]} m = {float(site[1]):.2f}: " + ' | '.join(out))

    print('\n2. launch: the rocket leaving the tube against the bore')
    by = collections.defaultdict(list)
    for s in shots:
        p = plan[s['id']]
        if p['kind'] == 'sights' or float(s['tof']) < 0:
            continue
        baz, bel = az_el(vec(s, 'b'))
        v0 = vec(s, 'v0')
        vaz, vel = az_el(v0)
        vel += 9.81 * float(s['v0dt']) / max(1, math.sqrt(sum(a * a for a in v0))) * 57.2958  # gravity since firing
        by[p['launcher']].append((vel - bel, wrap(vaz - baz), math.sqrt(sum(a * a for a in v0))))
    for name, xs in by.items():
        up, right, sp = zip(*xs)
        sd = lambda v: statistics.pstdev(v) if len(v) > 1 else 0
        print(f'  {name:12s} {len(xs):2d} rockets: up {statistics.mean(up):+.3f} sd {sd(up):.3f} deg, right '
              f'{statistics.mean(right):+.3f} sd {sd(right):.3f} deg, speed {statistics.mean(sp):.1f} m/s')

    print("\n3. hits: the calculator's shots fired through the weapon; miss where each is D m out (m, + = high / right)")
    res = collections.defaultdict(list)
    for s in shots:
        p = plan[s['id']]
        if p['kind'] != 'fire' or float(s['tof']) < 0:
            continue
        fr = trajs.get((s['id'], s['round']))
        if not fr:
            continue
        m = vec(s, 'm')
        a = math.radians(p['az'])
        ux, uz = math.sin(a), math.cos(a)  # the target's bearing (the aim-off is in the shot, not the target)
        prev = None
        for q in fr:
            x, y, z = float(q['x']) - m[0], float(q['y']) - m[1], float(q['z']) - m[2]
            along, side = x * ux + z * uz, x * uz - z * ux
            if prev and prev[0] < p['D'] <= along:
                f = (p['D'] - prev[0]) / (along - prev[0])
                res[(p['launcher'], p['wspeed'] > 0)].append((p, prev[1] + (y - prev[1]) * f - p['H'], prev[2] + (side - prev[2]) * f))
                break
            prev = (along, y, side)
    for (name, windy), xs in res.items():
        hs, ss = [x[1] for x in xs], [x[2] for x in xs]
        rms = lambda v: math.sqrt(sum(a * a for a in v) / len(v))
        print(f"  {name:12s} {'wind ' if windy else 'still'} {len(xs):2d} rockets: height mean {statistics.mean(hs):+.2f} "
              f"rms {rms(hs):.2f}, side mean {statistics.mean(ss):+.2f} rms {rms(ss):.2f}")
        for D in sorted({x[0]['D'] for x in xs}):
            at = [x for x in xs if x[0]['D'] == D]
            print(f"      {D:4.0f} m: " + '  '.join(f'{h:+.1f}/{s:+.1f}' for _, h, s in at))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('plan', 'run', 'score'))
    ap.add_argument('folder', nargs='?')
    args = ap.parse_args()
    if args.cmd == 'plan':
        write_plan(make_plan())
    elif args.cmd == 'run':
        run()
    else:
        score(args.folder or game_dir())
