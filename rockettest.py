"""Live rocket flight test for the Arma Reforger Maps field map (github.com/whopops/arma-map).

How the game's shoulder-fired rockets fly, wind included, so the field map can tell an RPG gunner which sight setting
to use and where to aim. Rockets are flown by the game itself through the RMT_FireTest entity (Scripts/Game/RMT/
RMT_FireTest.c, flag -rmtFire): launched with MissileMoveComponent.Launch high above open sea on Everon, where nothing
is in their way and every flight runs its whole life (the rockets blow up after TimeToLive), every frame recorded.

  python rockettest.py plan               write the plans (one per wind) into the game profile
  python rockettest.py run                plan, then one game run per wind (Steam running, the game closed); ~20 min.
                                          Rerun to finish: winds already flown are skipped
  python rockettest.py score [folder]     fit and report; writes rockets.json for the site
  python rockettest.py check              random shots solved the site's way from out/rockets.json, fired in the game
                                          (one run per wind, ~25 min); how far each passed from its target
  python rockettest.py check-score [dir]  that report again

What the game's files say (Prefabs/Weapons/Ammo/Ammo_Rocket_*.et, MissileMoveComponent): a launch speed (InitSpeed), a
motor (ThrustForce for ThrustTime after ThrustInitTime), a mass, ForwardAirFriction / SideAirFriction, AlignTorque
(how hard the rocket turns into the air it flies through: weathervaning into a crosswind) and DistanceEnableGravitation.
The engine's equations for those aren't in the files, hence this test.
"""
import argparse, collections, csv, json, math, os, random, statistics, sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
import firetest  # the site's terrain, and the run folder plumbing

OUT_REL = 'rmt/rockettest'
ROCKETS = {
    'PG-7VM': 'Prefabs/Weapons/Ammo/Ammo_Rocket_PG7VM.et',
    'PG-7VL': 'Prefabs/Weapons/Ammo/Ammo_Rocket_PG7VL.et',
    'PG-7VR': 'Prefabs/Weapons/Ammo/Ammo_Rocket_PG7VR.et',
    'M72A3': 'Prefabs/Weapons/Ammo/Ammo_Rocket_M72A3.et',
    'PG-22': 'Prefabs/Weapons/Ammo/Ammo_Rocket_PG22.et',
    'RPG-75': 'Prefabs/Weapons/Ammo/Ammo_Rocket_RPG75.et',
}
ELEVS = (-12, -8, -5, -2, 0, 2, 4, 7, 10, 15, 20)  # degrees above the horizon (down a hill to well up one)
# wind: (m/s, the compass direction it blows FROM, as the in-game map shows it); the rockets fly north (bearing 0)
WINDS = ((0, 0), (10, 90), (5, 90), (10, 0), (10, 180))  # calm, from the right (east) 10 and 5, headwind, tailwind
CALM_REPEATS = 3                           # calm shots again, to see if launches vary
HEIGHT = 300                               # m above the sea


def sea_spots(n, seed=4):
    """Launch points over open sea with 1.5 km of sea to the north of each, 120 m apart."""
    ter = firetest.Terrain()
    rnd = random.Random(seed)
    out = []
    for _ in range(200000):
        x, z = rnd.uniform(300, 12500), rnd.uniform(300, 11000)
        if any(math.hypot(x - a, z - b) < 120 for a, b in out):
            continue
        if all(ter.ground(x, z + dz) <= 0 for dz in range(0, 1600, 100)):
            out.append((x, z))
            if len(out) == n:
                return out
    raise SystemExit(f'only {len(out)} sea spots found')


def make_plan():
    from blasttest import prefab_name
    rows = []
    for ws, wfrom in WINDS:
        for name, path in ROCKETS.items():
            for el in ELEVS:
                for rep in range(CALM_REPEATS if ws == 0 else 1):
                    rows.append({'id': f'T{len(rows):03d}', 'rocket': name, 'prefab': prefab_name(path), 'elev': el,
                                 'wspeed': ws, 'wfrom': wfrom, 'rep': rep})
    spots = sea_spots(len(rows))
    for r, (x, z) in zip(rows, spots):
        r['x'], r['z'] = x, z
    return rows


def game_dir(block=None, rel=OUT_REL):
    """The test's folder in the game profile; with a block number, that wind's own run folder's firetest/."""
    from rmtlib.steam import Install
    base = os.path.join(Install(None).game_profile, *rel.split('/'))
    return base if block is None else os.path.join(base, f'w{block}', 'firetest')


def blocks(rows):
    """The plan cut into one block per wind, in order of first appearance: each wind is flown in a game run of its own."""
    winds = list(dict.fromkeys((r['wspeed'], r['wfrom']) for r in rows))
    return [[r for r in rows if (r['wspeed'], r['wfrom']) == w] for w in winds]


def done(block, rel=OUT_REL):
    """Whether this wind's run finished (the game writes its status file only when every rocket is down)."""
    st = os.path.join(os.path.dirname(game_dir(block, rel)), 'firetest.status.json')
    try:
        return json.load(open(st)).get('result') == 'done'
    except (OSError, ValueError):
        return False


def write_plan(rows, block, rel=OUT_REL):
    d = game_dir(block, rel)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'plan.csv'), 'w', newline='') as f:
        f.write('id,prefab,coef,x,z,az,elev,wspeed,wdir,count,tx,tz,y\n')
        for r in rows:
            # the game's wind override takes where the wind blows TO: the map's "from" + 180
            f.write(f"{r['id']},{r['prefab']},1,{r['x']:.2f},{r['z']:.2f},{r.get('az', 0):.4f},{r['elev']:.4f},{r['wspeed']},"
                    f"{(r['wfrom'] + 180) % 360 if r['wspeed'] else 0},1,{r['x']:.2f},{r['z'] + 500:.2f},{HEIGHT}\n")
    json.dump(rows, open(os.path.join(d, 'plan.json'), 'w'), indent=1)
    print(f'plan: {len(rows)} rockets -> {d}')


def run(rows=None, rel=OUT_REL, tries=3):
    """One game run per wind, so a game that hangs costs one wind, not the lot; winds already done are skipped.
    (The game holds its output files open for the whole run, so a run killed part way leaves nothing.)"""
    from rmtlib.steam import Install
    from rmtlib.workbench import Runner
    for i, block in enumerate(blocks(rows or make_plan())):
        w = (block[0]['wspeed'], block[0]['wfrom'])
        for _ in range(tries):
            if done(i, rel):
                break
            write_plan(block, i, rel)
            code, lines, status = Runner(Install(None)).run_game('firetest', f'{rel}/w{i}', firetest.WORLD,
                                                                 flag='-rmtFire', args=('-rmtFireGap=1',),
                                                                 stall=240, limit=1200)
            print(f'wind {w}: exit', code, 'status', status)
        print(f'wind {w}:', 'done' if done(i, rel) else 'FAILED')


def flights(base):
    """Every rocket's flight: plan row and frames (t, x along the flight (north), y up, z right (east)), from launch."""
    out = []
    i = 0
    while os.path.isdir(os.path.join(base, f'w{i}')):
        d = os.path.join(base, f'w{i}', 'firetest')
        if os.path.exists(os.path.join(d, 'traj.csv')):
            out += flights_in(d)
        i += 1
    return out


# --- check: the site's own answers, fired in the game -------------------------------------------------------------
CHECK_REL = 'rmt/rockettest-check'
CHECK_WINDS = 8      # random winds, each its own game run
CHECK_SHOTS = 3      # shots per rocket per wind


def check_plan(seed=11):
    """Random shots (distance, height difference, wind) solved the site's way from rockets.json, to fly in the game:
    elevation and aim-off bearing as the site gives them. The rocket flies north; the target is D m north, H m up."""
    from blasttest import prefab_name
    import rocketfit
    J = json.load(open(os.path.join(REPO, 'out', 'rockets.json')))
    rnd = random.Random(seed)
    rows = []
    for _ in range(CHECK_WINDS):
        ws, wf = round(rnd.uniform(2, 12) * 2) / 2, rnd.randrange(360)
        # windParts for a shot due north: along + = tailwind, and the crosswind from the right
        w = (-ws * math.cos(math.radians(wf)), ws * math.sin(math.radians(wf)))
        for name, path in ROCKETS.items():
            R = J['rockets'][name]
            reach = rocketfit.flight(R, 0)[-1][0]
            n = 0
            while n < CHECK_SHOTS:
                D, H = rnd.uniform(80, 0.85 * reach), rnd.uniform(-30, 30)
                s = rocketfit.aim(R, D, H, w)
                if not s:
                    continue
                e, side, t = s
                rows.append({'id': f'T{len(rows):03d}', 'rocket': name, 'prefab': prefab_name(path), 'elev': e,
                             'az': -math.degrees(math.atan2(side, D)), 'wspeed': ws, 'wfrom': wf, 'D': D, 'H': H, 'tof': t})
                n += 1
    for r, (x, z) in zip(rows, sea_spots(len(rows), seed=seed)):
        r['x'], r['z'] = x, z
    return rows


def check_score(base):
    """How far each check shot passed from its target: at D m north, the height against H and the side against 0."""
    by = collections.defaultdict(list)
    for p, fr in flights(base):
        q = next(((a, b) for a, b in zip(fr, fr[1:]) if a[1] <= p['D'] <= b[1]), None)
        if not q:
            print(f"  {p['id']} {p['rocket']}: never got {p['D']:.0f} m out")
            continue
        a, b = q
        f = (p['D'] - a[1]) / ((b[1] - a[1]) or 1)
        up, side, t = (a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, a[0] + (b[0] - a[0]) * f)
        by[p['rocket']].append((p, up - p['H'], side, t - p['tof']))
    print('miss at the target (m): height (+ = high) and side (+ = right); one line per rocket, then its worst shots')
    for name, rs in by.items():
        hs, ss = [r[1] for r in rs], [r[2] for r in rs]
        rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v))
        print(f'{name:7s} {len(rs):2d} shots: height mean {statistics.mean(hs):+.2f} rms {rms(hs):.2f}, '
              f'side mean {statistics.mean(ss):+.2f} rms {rms(ss):.2f}, worst {max(math.hypot(h, s) for h, s in zip(hs, ss)):.2f}')
        for p, h, s, dt in sorted(rs, key=lambda r: -math.hypot(r[1], r[2]))[:2]:
            print(f"     {p['D']:4.0f} m, {p['H']:+5.1f} m up, wind {p['wspeed']} from {p['wfrom']:3d}, elev {p['elev']:+.2f}: "
                  f"{h:+.2f} high, {s:+.2f} right, time {dt:+.2f} s")


def flights_in(d):
    plan = {p['id']: p for p in json.load(open(os.path.join(d, 'plan.json')))}
    tr = collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(d, 'traj.csv'), newline='')):
        tr[r['id']].append(r)
    out = []
    for id_, rows in tr.items():
        p = plan[id_]
        fr = []
        for r in rows:
            t, x, y, z = float(r['t']), float(r['x']), float(r['y']), float(r['z'])
            vx, vy, vz = float(r['vx']), float(r['vy']), float(r['vz'])
            fr.append((t, z - p['z'], y - HEIGHT, x - p['x'], vz, vy, vx))  # along (north), up, right (east)
        if fr:
            fr.insert(0, (0.0, 0.0, 0.0, 0.0) + fr[0][4:])  # the launch point (the first frame is a tick after it)
        out.append((p, fr))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('plan', 'run', 'score', 'check', 'check-score'))
    ap.add_argument('folder', nargs='?')
    args = ap.parse_args()
    if args.cmd == 'plan':
        for i, rows in enumerate(blocks(make_plan())):
            write_plan(rows, i)
    elif args.cmd == 'run':
        run()
    elif args.cmd == 'check':
        run(check_plan(), CHECK_REL)
        check_score(game_dir(rel=CHECK_REL))
    elif args.cmd == 'check-score':
        check_score(args.folder or game_dir(rel=CHECK_REL))
    else:
        import rocketfit
        T = rocketfit.report(flights(args.folder or game_dir()))
        out = os.path.join(REPO, 'out', 'rockets.json')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump(rocketfit.site_json(T), open(out, 'w'), separators=(',', ':'))
        print(f'\n-> {out} ({os.path.getsize(out) // 1024} KB): copy to arma-map everon-map/static/data/rockets.json')
