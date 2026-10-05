"""Live rocket flight test for the Arma Reforger Maps field map (github.com/whopops/arma-map).

How the game's shoulder-fired rockets fly, wind included, so the field map can tell an RPG gunner which sight setting
to use and where to aim. Rockets are flown by the game itself through the RMT_FireTest entity (Scripts/Game/RMT/
RMT_FireTest.c, flag -rmtFire): launched with MissileMoveComponent.Launch high above open sea on Everon, where nothing
is in their way and every flight runs its whole life (the rockets blow up after TimeToLive), every frame recorded.

  python rockettest.py plan               write the plans (one per wind) into the game profile
  python rockettest.py run                plan, then one game run per wind (Steam running, the game closed); ~80 min
                                          for all sixteen (WINDS). Rerun to finish: runs already flown are skipped
  python rockettest.py score [folder]     fit and report; writes rockets.json for the site
  python rockettest.py check              random shots solved the site's way from out/rockets.json, fired in the game
                                          (one run per wind, ~50 min); how far each passed from its target
  python rockettest.py check-score [dir]  that report again
  python rockettest.py check-twins        the check's shots again in still air (~50 min), each the twin of one (the same
                                          draw of the game's scatter): the wind's part of each miss, scatter taken out
  python rockettest.py check-twins-score [dir]  that report again

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
# wind: (m/s, the compass direction it blows FROM, as the in-game map shows it); the rockets fly north (bearing 0).
# The first five are the original set (still air, from the right (east) at 10 and 5, head and tail at 10); the rest
# measure how the wind's effect grows with its speed (3 to 20 m/s) and whether a crosswind from the left (west) is the
# mirror of one from the right, so rocketfit needn't assume either. Each wind is its own run (w0, w1, ...): keep this
# order, so runs already flown keep their numbers.
#
# The game's random scatter (a shot's launch differs from the next one's: up to 3 m in height at 500 m for the M72A3
# and PG-22) is drawn from a sequence that starts afresh every run, so the shot in the same place in two runs gets the
# same draw. SAME_LAYOUT is still air flown once more, laid out exactly like a wind run (one rocket per elevation):
# against it, every wind run's shot has its twin, and the difference is the wind's alone (rocketfit.wind_runs).
SAME_LAYOUT = (0, 360)  # still air ("from" 360 only tells it from the repeated still-air run)
WINDS = ((0, 0), (10, 90), (5, 90), (10, 0), (10, 180),
         (3, 90), (15, 90), (20, 90),
         (5, 270), (10, 270), (20, 270),
         (5, 0), (20, 0), (5, 180), (20, 180),
         SAME_LAYOUT)
CALM_REPEATS = 3                           # still-air shots per elevation in the first run: the still-air flight is
                                           # their average with SAME_LAYOUT's (four of the game's random draws)
HEIGHT = 300                               # m above the sea


def sea_spots(n, seed=4, most=400):
    """Launch points over open sea with 1.5 km of sea to the north of each, 120 m apart. Past `most` they repeat (rounds
    launched from the same point at different times don't meet)."""
    ter = firetest.Terrain()
    rnd = random.Random(seed)
    out = []
    want = min(n, most)
    for _ in range(200000):
        x, z = rnd.uniform(300, 12500), rnd.uniform(300, 11000)
        if any(math.hypot(x - a, z - b) < 120 for a, b in out):
            continue
        if all(ter.ground(x, z + dz) <= 0 for dz in range(0, 1600, 100)):
            out.append((x, z))
            if len(out) == want:
                return [out[i % want] for i in range(n)]
    raise SystemExit(f'only {len(out)} sea spots found')


def make_plan(projectiles=None, elevs=ELEVS, winds=WINDS, repeats=CALM_REPEATS):
    """projectiles: name -> prefab path, or (prefab path, launch speed coefficient: the weapon's BulletInitSpeedCoef)."""
    from blasttest import prefab_name
    rows = []
    for ws, wfrom in winds:
        for name, what in (projectiles or ROCKETS).items():
            path, coef = what if isinstance(what, tuple) else (what, 1)
            for el in elevs:
                for rep in range(repeats if (ws, wfrom) == (0, 0) else 1):
                    rows.append({'id': f'T{len(rows):04d}', 'rocket': name, 'prefab': prefab_name(path), 'coef': coef,
                                 'elev': el, 'wspeed': ws, 'wfrom': wfrom, 'rep': rep})
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
            f.write(f"{r['id']},{r['prefab']},{r.get('coef', 1)},{r['x']:.2f},{r['z']:.2f},{r.get('az', 0):.4f},{r['elev']:.4f},{r['wspeed']},"
                    f"{(r['wfrom'] + 180) % 360 if r['wspeed'] else 0},1,{r['x']:.2f},{r['z'] + 500:.2f},{r.get('y', HEIGHT)}\n")
    json.dump(rows, open(os.path.join(d, 'plan.json'), 'w'), indent=1)
    print(f'plan: {len(rows)} rockets -> {d}')


def run(rows=None, rel=OUT_REL, tries=3, args=('-rmtFireGap=1',)):
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
                                                                 flag='-rmtFire', args=tuple(args),
                                                                 stall=240, limit=1800)
            print(f'wind {w}: exit', code, 'status', status)
        print(f'wind {w}:', 'done' if done(i, rel) else 'FAILED')


def flights(base):
    """Every rocket's flight: plan row and frames (t, x along the flight (north), y up, z right (east)), from launch.
    Only finished runs count: a run still going (or killed) has a half-written traj.csv whose flights stop mid-air."""
    out = []
    i = 0
    while os.path.isdir(os.path.join(base, f'w{i}')):
        d = os.path.join(base, f'w{i}', 'firetest')
        st_file = os.path.join(base, f'w{i}', 'firetest.status.json')
        try:
            finished = json.load(open(st_file)).get('result') == 'done'
        except (OSError, ValueError):
            finished = False
        if os.path.exists(os.path.join(d, 'traj.csv')):
            if finished:
                out += flights_in(d)
            else:
                print(f'  (w{i}: not finished, left out)')
        i += 1
    return out


# --- check: the site's own answers, fired in the game -------------------------------------------------------------
CHECK_REL = 'rmt/rockettest-check'
CHECK_WINDS = 10     # random winds (2 to 20 m/s, from anywhere: both sides, head and tail), each its own game run
CHECK_SHOTS = 4      # shots per rocket per wind


def check_plan(seed=11):
    """Random shots (distance, height difference, wind) solved the site's way from rockets.json, to fly in the game:
    elevation and aim-off bearing as the site gives them (rocketfit.aim, the site's solver copied; test_sitesolver.py
    keeps them the same). Distances run from 80 m out to the launcher's range at that height, so the self-destruct
    limit is checked too. The rocket flies north; the target is D m north, H m up."""
    from blasttest import prefab_name
    import rocketfit
    J = json.load(open(os.path.join(REPO, 'out', 'rockets.json')))
    rnd = random.Random(seed)
    rows = []
    for _ in range(CHECK_WINDS):
        ws, wf = round(rnd.uniform(2, 20) * 2) / 2, rnd.randrange(360)
        # windParts for a shot due north: along + = tailwind, and the crosswind from the right
        w = (-ws * math.cos(math.radians(wf)), ws * math.sin(math.radians(wf)))
        for name, path in ROCKETS.items():
            R = rocketfit.prepare(J['rockets'][name])
            reach = R['reach']
            n = 0
            while n < CHECK_SHOTS:
                D, H = rnd.uniform(80, reach), rnd.uniform(-30, 30)
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


CHECK_TWIN_REL = 'rmt/rockettest-check-twins'


def check_twin_rows(check_rel=CHECK_REL):
    """The check's shots again, aimed the same, in still air: each check run replayed in a run of its own with the same
    layout, so every shot has its twin (the same draw of the game's scatter; see SAME_LAYOUT)."""
    rows, i = [], 0
    while os.path.exists(os.path.join(game_dir(i, check_rel), 'plan.json')):
        for r in json.load(open(os.path.join(game_dir(i, check_rel), 'plan.json'))):
            rows.append(dict(r, wspeed=0, wfrom=1000 + i))  # still air; "from" only keeps each run's twins together
        i += 1
    return rows


def check_twins_score(check_base, twin_base, data, bullet=False):
    """The wind's part of the check, free of the game's scatter: per shot, how much the wind moved it from its still-air
    twin at the target's distance (height and side), against how much the site's calculator says it should
    (rocketfit.shot_at at the shot's elevation with and without the wind). Also the twins' miss against the
    calculator's still-air flight: its still-air error plus the game's scatter."""
    import rocketfit
    J = json.load(open(data))
    table = J['rounds'] if bullet else J['rockets']
    tw = {p['id']: fr for p, fr in flights(twin_base)}
    by = collections.defaultdict(list)
    for p, fr in flights(check_base):
        t = tw.get(p['id'])
        if t is None:
            continue
        R = dict(table[p['rocket']], bullet=True) if bullet else rocketfit.prepare(table[p['rocket']])
        D = p['D']

        def at(f):  # (up, right) when the flight is D m north
            return next(((a[2] + (b[2] - a[2]) * (D - a[1]) / ((b[1] - a[1]) or 1), a[3] + (b[3] - a[3]) * (D - a[1]) / ((b[1] - a[1]) or 1))
                         for a, b in zip(f, f[1:]) if a[1] <= D <= b[1]), None)
        mw, mt = at(fr), at(t)
        w = (-p['wspeed'] * math.cos(math.radians(p['wfrom'])), p['wspeed'] * math.sin(math.radians(p['wfrom'])))
        pw, pc = rocketfit.shot_at(R, p['elev'], w, D), rocketfit.shot_at(R, p['elev'], (0, 0), D)
        if not (mw and mt and pw and pc):
            continue
        # (the twins share the shot's aim-off, so their difference is the wind's alone, as the calculator's is)
        by[p['rocket']].append(((mw[0] - mt[0]) - (pw[0] - pc[0]), (mw[1] - mt[1]) - (pw[1] - pc[1]), mt[0] - pc[0], p))
    print("the wind's part (each shot minus its still-air twin, against the calculator's), and the twins against the"
          " calculator's still-air flight (its still-air error plus the game's scatter); m")
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v)) if v else float('nan')
    for name, rs in by.items():
        h, s, c = [r[0] for r in rs], [r[1] for r in rs], [r[2] for r in rs]
        worst = max(rs, key=lambda r: math.hypot(r[0], r[1]))
        print(f"{name:22s} {len(rs):2d} shots: wind's part off by height rms {rms(h):.2f}, side rms {rms(s):.2f} (worst "
              f"{math.hypot(worst[0], worst[1]):.2f}, {worst[3]['D']:.0f} m in {worst[3]['wspeed']} m/s) | still-air twins: "
              f"height mean {statistics.mean(c):+.2f} rms {rms(c):.2f}")


def flight_time(fr):
    """Each frame's time since launch, rebuilt from the flight itself: the path walked, step by step, over the speed the
    game reports (the mean of the step's two ends). The recordings' own time stamps aren't the projectile's: it sits
    still for 2 to 34 ms after it is spawned (different for every shot and on average for every run), and a hitch in
    the game shifts the stamps of everything in the air by up to 0.2 s. Timed by the stamps, a run whose shots started
    later looked like a flight held back by its wind (the 7N6's crosswind runs started 18 ms after its still-air ones:
    17 m at 900 m/s, read as 1.7 m per m/s of wind), and a twin pair of flights (same draw of the game's scatter, a
    3 m/s crosswind against still air) differed by up to 0.15 s at the same distance; rebuilt, by under 1 ms for most
    rockets. fr: frames from the launch point, as flights_in makes them; returns the times."""
    ts = [0.0]
    for a, b in zip(fr, fr[1:]):
        va, vb = math.sqrt(a[4] ** 2 + a[5] ** 2 + a[6] ** 2), math.sqrt(b[4] ** 2 + b[5] ** 2 + b[6] ** 2)
        step = math.sqrt((b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2 + (b[3] - a[3]) ** 2)
        ts.append(ts[-1] + (step * 0.5 * (1 / va + 1 / vb) if va > 0 and vb > 0 else b[0] - a[0]))
    return ts


def flights_in(d):
    """Every flight in one run folder: (plan row, frames (t, along (north), up, right (east), their speeds)), from the
    launch point, timed by flight_time."""
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
            fr.append((t, z - p['z'], y - p.get('y', HEIGHT), x - p['x'], vz, vy, vx))  # along (north), up, right (east)
        if fr:
            # from the launch point: the frames still sitting there are dropped, the launch point keeps the launch
            # velocity the game reports while the projectile sits there
            moved = [q for q in fr if math.sqrt(q[1] ** 2 + q[2] ** 2 + q[3] ** 2) > 0.001]
            still = [q for q in fr if math.sqrt(q[1] ** 2 + q[2] ** 2 + q[3] ** 2) <= 0.001]
            fr = [(0.0, 0.0, 0.0, 0.0) + (still[-1][4:] if still else moved[0][4:])] + moved
            fr = [(t,) + q[1:] for t, q in zip(flight_time(fr), fr)]
        out.append((p, fr))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('plan', 'run', 'score', 'check', 'check-score', 'check-twins', 'check-twins-score'))
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
    elif args.cmd in ('check-twins', 'check-twins-score'):
        if args.cmd == 'check-twins':
            run(check_twin_rows(), CHECK_TWIN_REL)
        check_twins_score(game_dir(rel=CHECK_REL), args.folder or game_dir(rel=CHECK_TWIN_REL),
                          os.path.join(REPO, 'out', 'rockets.json'))
    else:
        import rocketfit
        T = rocketfit.report(flights(args.folder or game_dir()))
        out = os.path.join(REPO, 'out', 'rockets.json')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump(rocketfit.site_json(T), open(out, 'w'), separators=(',', ':'))
        print(f'\n-> {out} ({os.path.getsize(out) // 1024} KB): copy to arma-map everon-map/static/data/rockets.json')
