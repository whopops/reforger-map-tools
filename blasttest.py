"""Live mortar blast test for the Arma Reforger Maps field map (github.com/whopops/arma-map).

Measures what a mortar round does to soldiers around where it lands, in the real game: on EmptyEden (Everon's terrain
with nothing standing on it, so no tree, wall or building blocks a fragment), the RMT_BlastTest entity
(Scripts/Game/RMT/RMT_BlastTest.c) stands a ring of the game's riflemen around a flat, open spot, drops a real shell onto
it at a set angle, and records who is dead, unconscious or hurt. The field map's kill and danger zones come from this.

  python blasttest.py plan               write the plan into the game profile
  python blasttest.py run                plan, then run the game (Steam running, the game closed); ~15 min
  python blasttest.py score [folder]     report on the last run (or a copy of one)
  options: --site <everon-map/static/data> (default ~/Documents/GitHub/arma-map/everon-map/static/data)

What the game's files say (Prefabs/Weapons/Warheads/Warhead_Shell_HE_*.et and Prefabs/Weapons/Core/Damage/):
  * blast: 1000 damage, out to 10 m, scaled by the charge (ChargeWeight g x TntEquivalent), falling off to 40% at 4 m
    and nothing at 10 m; plus a 333 damage blast out to 3 m that ignores cover
  * fragments: DamageFragmentCount fragments (M821 2800, O-832DU 2700), 16 damage each, out to 25 m scaled by the
    fragments' mass and speed (Gurney: M821 about 1060 m/s, O-832DU about 740 m/s)
  * the practice round M879 has a 100 g blast charge and no fragments
How the engine scales and spreads all that, and how a character's armour and hit zones take it, isn't in the files:
hence this test.
"""
import argparse, collections, csv, itertools, json, math, os, random, statistics, sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
import firetest  # the site's terrain (Terrain) and the shells' prefabs

WORLD = '{55A3176BBDD01AAE}worlds/Eden/EmptyEden.ent'  # from addons/data/resourceDatabase.rdb
OUT_REL = 'rmt/blasttest'
SOLDIER = 'Prefabs/Characters/Factions/BLUFOR/US_Army/Character_US_Rifleman.et'
SHELLS = {
    'HE M821': 'Prefabs/Weapons/Ammo/Ammo_Shell_81mm_HE_M821.et',
    'HE O-832DU': 'Prefabs/Weapons/Ammo/Ammo_Shell_82mm_HE_O832DU.et',
    'Practice M879': 'Prefabs/Weapons/Ammo/Ammo_Shell_81mm_Practice_M879.et',
    # the smoke rounds' warheads are the HE one with a 100 g charge (Warhead_Shell_Smoke_*.et), so they hurt too
    'Smoke M819': 'Prefabs/Weapons/Ammo/Ammo_Shell_81mm_Smoke_M819.et',
    'Smoke D-832DU': 'Prefabs/Weapons/Ammo/Ammo_Shell_82mm_Smoke_D832DU.et',
}
DEFAULT_SHELLS = ('HE M821', 'HE O-832DU', 'Practice M879')
DESCENTS = (50, 65, 80)          # degrees below the horizon: mortar rounds come down at about 45-85
STANCES = {0: 'standing', 2: 'prone'}
UNCON = {1: 'can be knocked out', 0: 'no unconsciousness'}
REPS = 4
# Soldiers: three at each distance, at angles turned by the golden angle so nobody stands right behind another
DISTANCES = (3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 45, 50, 60, 70)
SPOT_R = 60                      # m of even ground wanted around each aim point
SPOT_GAP = 300                   # m between aim points
SPOTS = 12


def prefab_name(path):
    """{GUID}path for a game file, from the resource database."""
    if path.startswith("{"):
        return path
    import re
    from rmtlib.steam import Install
    rdb = os.path.join(Install(None).game_dir, 'addons', 'data', 'resourceDatabase.rdb')
    d = open(rdb, 'rb').read()
    i = d.find(path.encode() + b'\x00')
    if i < 0:
        raise SystemExit(f'{path} not in the resource database')
    g = d[i + len(path) + 1 + 6:i + len(path) + 1 + 14]  # name, NUL, 6 bytes, then the GUID little-endian
    return '{%s}%s' % (g[::-1].hex().upper(), path)


def plane_fit(pts, hs):
    """Least-squares plane h = gx*a + gz*b + c through the points; returns gx, gz, c and the worst miss (m)."""
    n = len(pts)
    sa = sum(a for a, _ in pts); sb = sum(b for _, b in pts); sh = sum(hs)
    saa = sum(a * a for a, _ in pts); sbb = sum(b * b for _, b in pts); sab = sum(a * b for a, b in pts)
    sah = sum(a * h for (a, _), h in zip(pts, hs)); sbh = sum(b * h for (_, b), h in zip(pts, hs))
    m = [[saa, sab, sa], [sab, sbb, sb], [sa, sb, n]]
    v = [sah, sbh, sh]
    det = lambda q: (q[0][0] * (q[1][1] * q[2][2] - q[1][2] * q[2][1]) - q[0][1] * (q[1][0] * q[2][2] - q[1][2] * q[2][0])
                     + q[0][2] * (q[1][0] * q[2][1] - q[1][1] * q[2][0]))
    d = det(m)
    sol = []
    for i in range(3):  # Cramer's rule
        q = [row[:] for row in m]
        for r in range(3):
            q[r][i] = v[r]
        sol.append(det(q) / d)
    gx, gz, c = sol
    return gx, gz, c, max(abs(gx * a + gz * b + c - h) for (a, b), h in zip(pts, hs))


def layout():
    out, k = [], 0
    for d in DISTANCES:
        for _ in range(3):
            a = math.radians((k * 137.508) % 360)
            out.append((d * math.cos(a), d * math.sin(a)))  # along, across
            k += 1
    return out


def make_plan(shells=DEFAULT_SHELLS, seed=7):
    ter = firetest.Terrain()
    rnd = random.Random(seed)
    # The evenest open ground on Everon: every 50 m, how far the ground within SPOT_R strays from a flat plane (a steady
    # slope doesn't matter, bumps and hollows do). Everon is bumpy, so the best SPOTS are used in turn; the game side
    # clears away what each trial leaves lying about.
    pts = [(r * math.cos(t), r * math.sin(t)) for r in (0, 10, 20, 30, 40, SPOT_R)
           for t in [i * math.pi / 6 for i in range(12)]]
    cands = []
    for x in range(600, 12200, 50):
        for z in range(600, 12200, 50):
            if ter.ground(x, z) < 4:
                continue
            hs = [ter.ground(x + a, z + b) for a, b in pts]
            if min(hs) < 4:
                continue
            gx, gz, _, worst = plane_fit(pts, hs)
            if math.degrees(math.atan(math.hypot(gx, gz))) < 6:
                cands.append((worst, x, z))
    cands.sort()
    spots = []
    for worst, x, z in cands:
        if all(math.hypot(x - a, z - b) >= SPOT_GAP for a, b, _ in spots):
            spots.append((x, z, worst))
        if len(spots) == SPOTS:
            break
    print('spots: ' + ', '.join(f'{x},{z} (±{w:.2f} m)' for x, z, w in spots))
    rows = []
    soldier = prefab_name(SOLDIER)
    prefabs = {s: prefab_name(SHELLS[s]) for s in shells}
    for s, de, st, un, _ in itertools.product(shells, DESCENTS, STANCES, UNCON, range(REPS)):
        x, z, _ = spots[len(rows) % len(spots)]
        rows.append({'id': f'B{len(rows):03d}', 'shell': s, 'prefab': prefabs[s], 'soldier': soldier, 'x': x, 'z': z,
                     'az': rnd.uniform(0, 360), 'descent': de, 'stance': st, 'uncon': un})
    rnd.shuffle(rows)  # spread the kinds over the run
    return rows


def game_dir():
    from rmtlib.steam import Install
    return os.path.join(Install(None).game_profile, *OUT_REL.split('/'), 'blast')


def write_plan(rows):
    d = game_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'plan.csv'), 'w', newline='') as f:
        f.write('id,prefab,soldier,x,z,az,descent,stance,uncon\n')
        for r in rows:
            f.write(f"{r['id']},{r['prefab']},{r['soldier']},{r['x']:.2f},{r['z']:.2f},{r['az']:.3f},{r['descent']},{r['stance']},{r['uncon']}\n")
    with open(os.path.join(d, 'layout.csv'), 'w', newline='') as f:
        f.write('along,across\n')
        for a, c in layout():
            f.write(f'{a:.3f},{c:.3f}\n')
    json.dump(rows, open(os.path.join(d, 'plan.json'), 'w'), indent=1)
    print(f'plan: {len(rows)} trials x {len(layout())} soldiers -> {d}')


def run(shells=DEFAULT_SHELLS, trials=None):
    from rmtlib.steam import Install
    from rmtlib.labselection import runner as lab_runner
    write_plan(make_plan(shells)[:trials])
    code, lines, status = lab_runner(Install(None)).run_game('blasttest', OUT_REL, WORLD, flag='-rmtBlast', stall=300, limit=3600)
    print('exit', code, 'status', status)


# --- scoring --------------------------------------------------------------------------------------------------------
BANDS = (0, 4, 6, 8, 10, 12, 15, 18, 22, 26, 30, 35, 40, 50, 60, 80)


def fit(points):
    """A falling S-curve P(r) = 1 / (1 + exp((r - r50) / s)) through (distance, 0/1) points, by maximum likelihood on a
    grid. Returns (r50, s), or None when nothing (or everything) happened."""
    ys = [y for _, y in points]
    if not points or not any(ys) or all(ys):
        return None
    best = None
    for r50 in [x / 4 for x in range(4, 400)]:
        for s in (0.3, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8):
            ll = 0
            for r, y in points:
                p = 1 / (1 + math.exp(min(50, (r - r50) / s)))
                p = min(max(p, 1e-6), 1 - 1e-6)
                ll += math.log(p if y else 1 - p)
            if best is None or ll > best[0]:
                best = (ll, r50, s)
    return best[1], best[2]


def radius_at(f, p):
    """Distance where the fitted curve f = (r50, s) falls to share p."""
    return None if f is None else round(f[0] + f[1] * math.log(1 / p - 1), 1)


def score(d):
    plan = {p['id']: p for p in json.load(open(os.path.join(d, 'plan.json')))}
    bursts = {r['id']: r for r in csv.DictReader(open(os.path.join(d, 'bursts.csv'), newline=''))}
    hits = list(csv.DictReader(open(os.path.join(d, 'hits.csv'), newline='')))
    print(f'{len(bursts)} trials, {len(hits)} soldiers ({d})')
    air = [i for i, b in bursts.items() if b.get('end') == 'in_air']
    if air:
        # its last known point stands in for the burst; the game did not show where it went off
        print(f'{len(air)} burst(s) did not reach the ground in the last frame (end=in_air): {", ".join(air[:10])}')
    off = [math.hypot(float(b['x']) - plan[i]['x'], float(b['z']) - plan[i]['z']) for i, b in bursts.items()]
    print(f'bursts: a median {statistics.median(off):.2f} m from the aim point, {float(max(off)):.1f} m at most; '
          f'height above the ground median {statistics.median(float(b["y"]) - float(b["ground"]) for b in bursts.values()):+.2f} m')
    # Each soldier: distance from the burst on the ground, and its angle from the shell's direction of travel.
    # down = dead or unconscious (out of the fight); hurt = anything at all (a wound, bleeding, or down)
    groups = collections.defaultdict(list)
    for h in hits:
        p, b = plan[h['id']], bursts.get(h['id'])
        if not b:
            continue
        dx, dz = float(h['x']) - float(b['x']), float(h['z']) - float(b['z'])
        r = math.hypot(dx, dz)
        ang = (math.degrees(math.atan2(dx, dz)) - p['az'] + 540) % 360 - 180  # 0 = ahead, +-180 = behind
        life, health, bleed, mz = int(h['life']), float(h['health']), int(h['bleeding']), float(h['min_zone'])
        # life: ECharacterLifeState, ALIVE 0, INCAPACITATED 1, DEAD 10 in the engine (its generated script lists them
        # without values); state 2 = EDamageState.DESTROYED
        dead = life == 10 or int(h['state']) == 2
        out = {'dead': dead, 'down': dead or life == 1, 'hurt': life >= 1 or health < 0.999 or bool(bleed) or mz < 0.999,
               'r': r, 'side': 'ahead' if abs(ang) < 45 else 'behind' if abs(ang) > 135 else 'side', 'descent': p['descent']}
        groups[(p['shell'], p['stance'], p.get('uncon', 1))].append(out)
    summary = {}
    for (s, st, un), v in sorted(groups.items()):
        print(f'\n{s} · {STANCES.get(st, st)} · {UNCON.get(un, un)}: share dead / down (dead or unconscious) / hurt')
        for lo, hi in zip(BANDS, BANDS[1:]):
            b = [o for o in v if lo <= o['r'] < hi]
            if b:
                n = len(b)
                print(f'   {lo:3d}-{hi:<3d} m  {n:4d}   dead {sum(o["dead"] for o in b) / n:5.0%}   down {sum(o["down"] for o in b) / n:5.0%}'
                      f'   hurt {sum(o["hurt"] for o in b) / n:5.0%}')
        down, hurt = fit([(o['r'], o['down']) for o in v]), fit([(o['r'], o['hurt']) for o in v])
        row = {'down90': radius_at(down, 0.9), 'down50': radius_at(down, 0.5), 'down10': radius_at(down, 0.1),
               'hurt50': radius_at(hurt, 0.5), 'hurt10': radius_at(hurt, 0.1)}
        print('   fitted: down 90% to {down90} m, 50% to {down50} m, 10% to {down10} m; hurt 50% to {hurt50} m, 10% to {hurt10} m'.format(**row))
        # does the way it came down matter? the 50% distance for each descent, and ahead / side / behind
        by = []
        for key, vals in (('descent', DESCENTS), ('side', ('ahead', 'side', 'behind'))):
            for val in vals:
                f = fit([(o['r'], o['down']) for o in v if o[key] == val])
                by.append(f'{val}{"°" if key == "descent" else ""} {radius_at(f, 0.5)}')
        print('   down 50% by descent and side: ' + ', '.join(by))
        summary[f'{s}|{STANCES.get(st, st)}|{"uncon" if un else "nouncon"}'] = row
    out = os.path.join(d, 'summary.json')
    json.dump(summary, open(out, 'w'), indent=1)
    print(f'\nsummary -> {out}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('plan', 'run', 'score'))
    ap.add_argument('folder', nargs='?', help='score: a run folder (default: the last run in the game profile)')
    ap.add_argument('--trials', type=int, help='run: only the first N trials (a quick check)')
    ap.add_argument('--shells', default=','.join(DEFAULT_SHELLS),
                    help=f'plan/run: comma-separated, from {", ".join(SHELLS)} (default: {", ".join(DEFAULT_SHELLS)})')
    ap.add_argument('--out', default=OUT_REL, help=f'run folder under the game profile (default {OUT_REL}); '
                    'give each set of shells its own so one run does not overwrite another')
    ap.add_argument('--site', default=firetest.SITE, help="the field map's static/data folder")
    args = ap.parse_args()
    firetest.SITE = args.site
    OUT_REL = args.out
    shells = [s.strip() for s in args.shells.split(',')]
    if any(s not in SHELLS for s in shells):
        raise SystemExit(f'unknown shell; pick from {", ".join(SHELLS)}')
    if args.cmd == 'plan':
        write_plan(make_plan(shells))
    elif args.cmd == 'run':
        run(shells, args.trials)
    else:
        score(args.folder or game_dir())
