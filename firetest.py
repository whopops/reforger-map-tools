"""Live mortar firing test for the Arma Reforger Maps field map (github.com/whopops/arma-map).

Plans aims on Everon with the field map's own firing solution (a line-for-line Python copy of static/app.js: solve,
flight, highAngleFor, windParts, spreadOf, and its 1 m terrain), fires them as real shells in the game (the RMT_FireTest
entity, Scripts/Game/RMT/RMT_FireTest.c), and scores where every round landed.

  python firetest.py plan               write the plan into the game profile
  python firetest.py run                plan, then run the game (Steam running, the game closed); ~25 min
  python firetest.py score [folder]     report on the last run (or a copy of one)
  options: --site <everon-map/static/data> (default ~/Documents/GitHub/arma-map/everon-map/static/data)

What each round tells us:
  * its launch velocity (the game adds a random speed): the site's physics, flown from that exact launch to the height it
    landed at, against where it really landed. This is the physics with no randomness left in it.
  * the aims: where the rounds' centre landed against the target, with its standard error (6 rounds is noisy: the random
    speed alone spreads rounds 20-60 m long and short).
  * the spread groups (20 rounds): the long/short spread against the site's prediction for the speed part. (Launching
    directly doesn't use the mortar's barrel, so the barrel's sideways spread isn't in a direct launch.)
  * the wind probe: the same aim with no wind and 10 m/s from four sides, uncorrected, to show how the game's wind pushes.

Keep the SHELLS, MUZZLE_H, SPEED_SD, BARREL and P90 numbers in step with app.js.
"""
import argparse, collections, csv, gzip, json, math, os, random, statistics, struct, sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
WORLD = '{853E92315D1D9EFE}worlds/Eden/Eden.ent'
OUT_REL = 'rmt/firetest'
GRAV = 9.81
SITE = os.path.expanduser('~/Documents/GitHub/arma-map/everon-map/static/data')
# app.js SHELL_PHYS for the two HE shells, plus each one's prefab for the game
SHELLS = {
    ('M252', 'HE M821'): ('{38BAE094333E31BF}Prefabs/Weapons/Ammo/Ammo_Shell_81mm_HE_M821.et', 66, 0.000462 / 4.06,
                          {0: 1, 1: 1.531, 2: 2.085, 3: 2.541, 4: 2.977}),
    ('2B14', 'HE O-832DU'): ('{98EC9C526AFBA282}Prefabs/Weapons/Ammo/Ammo_Shell_82mm_HE_O832DU.et', 76, 0.000615 / 3.1,
                             {0: 1, 1: 1.321, 2: 1.736, 3: 2.087, 4: 2.455}),
}
MUZZLE_H, SPEED_SD, BARREL, P90 = 1.3, 1.07, 0.5 / 48, 2.146
TABLES = None


# --- the site's terrain (static/data/maps/everon/los tiles: 1 m terrain, and what stands on every 0.5 m) -------------
class Terrain:
    def __init__(self):
        d = os.path.join(SITE, 'maps', 'everon', 'los')
        self.dir = d
        ix = json.load(open(os.path.join(d, 'index.json')))
        self.names = set(ix['tiles'])
        self.unit = ix['terrain']['unit']
        self.cache = {}

    def tile(self, x, z):
        name = f'{int(x // 500)}_{int(z // 500)}'
        if name not in self.names:
            return None
        if name not in self.cache:
            raw = gzip.open(os.path.join(self.dir, name + '.bin.gz')).read()
            ter = struct.unpack_from('<%dH' % (501 * 501), raw, 0)
            kind = raw[501 * 501 * 2 + 1000 * 1000: 501 * 501 * 2 + 2 * 1000 * 1000]
            self.cache[name] = (int(x // 500) * 500, int(z // 500) * 500, ter, kind)
        return self.cache[name]

    def ground(self, x, z):
        """groundFine() in app.js"""
        t = self.tile(x, z)
        if not t:
            return 0.0
        x0, z0, T, _ = t
        lx, lz = min(max(x - x0, 0), 499.999), min(max(z - z0, 0), 499.999)
        c, r = int(lx), int(lz)
        fx, fz = lx - c, lz - r
        a, b, d, e = T[r * 501 + c], T[r * 501 + c + 1], T[(r + 1) * 501 + c], T[(r + 1) * 501 + c + 1]
        return ((a + (b - a) * fx) * (1 - fz) + (d + (e - d) * fx) * fz) * self.unit

    def near(self, x, z, r=3, kinds=(1, 2)):
        """anything of these kinds within r m (1 building, 2 wall/rock, 3 tree, 5 bush)"""
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                t = self.tile(x + dx, z + dz)
                if not t:
                    continue
                x0, z0, _, kind = t
                c, rr = min(999, int((x + dx - x0) * 2)), min(999, int((z + dz - z0) * 2))
                if kind[rr * 1000 + c] in kinds:
                    return True
        return False


# --- the site's firing solution (app.js flight / highAngleFor / windParts / spreadOf / solve) ------------------------
def flight(v, k, ang, dh, along=0.0, across=0.0):
    dt = 0.1
    x = y = z = 0.0
    vx, vy, vz, t = 0.0, v * math.sin(ang), v * math.cos(ang), 0.0

    def acc(ux, uy, uz):
        rx, rz = ux - across, uz - along
        s = math.sqrt(rx * rx + uy * uy + rz * rz)
        return (-k * s * rx, -GRAV - k * s * uy, -k * s * rz)
    while True:
        a1 = acc(vx, vy, vz)
        a2 = acc(vx + a1[0] * dt / 2, vy + a1[1] * dt / 2, vz + a1[2] * dt / 2)
        a3 = acc(vx + a2[0] * dt / 2, vy + a2[1] * dt / 2, vz + a2[2] * dt / 2)
        a4 = acc(vx + a3[0] * dt, vy + a3[1] * dt, vz + a3[2] * dt)
        py, px, pz = y, x, z
        x += dt * (vx + dt / 6 * (a1[0] + a2[0] + a3[0]))
        y += dt * (vy + dt / 6 * (a1[1] + a2[1] + a3[1]))
        z += dt * (vz + dt / 6 * (a1[2] + a2[2] + a3[2]))
        vx += dt / 6 * (a1[0] + 2 * a2[0] + 2 * a3[0] + a4[0])
        vy += dt / 6 * (a1[1] + 2 * a2[1] + 2 * a3[1] + a4[1])
        vz += dt / 6 * (a1[2] + 2 * a2[2] + 2 * a3[2] + a4[2])
        t += dt
        if vy < 0 and y <= dh:
            if py < dh:
                return None
            f = (py - dh) / (py - y)
            return {'range': pz + (z - pz) * f, 'drift': px + (x - px) * f, 'tof': t - dt + dt * f}
        if t > 150:
            return None


def high_angle(v, k, d, dh, along, across):
    lo, hi = math.radians(44), math.radians(89.5)
    first = flight(v, k, lo, dh, along, across)
    if not first or first['range'] < d:
        return None
    for _ in range(22):
        mid = (lo + hi) / 2
        f = flight(v, k, mid, dh, along, across)
        if not f or f['range'] < d:
            hi = mid
        else:
            lo = mid
    ang = (lo + hi) / 2
    return {'ang': ang, **flight(v, k, ang, dh, along, across)}


def wind_parts(wind, az):
    """wind = (m/s, compass direction it blows FROM, as the in-game map shows it)"""
    if not wind or wind[0] <= 0:
        return 0.0, 0.0
    toward = math.radians((wind[1] + 180) - az)
    return wind[0] * math.cos(toward), wind[0] * math.sin(toward)


def bearing(a, b):
    return (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) + 360) % 360


def spread_of(v, coef, k, ang, dh, along, across, d):
    """spreadOf(): the 90% ellipse's half-lengths along and across the line of fire, and the speed part's sd (m)"""
    f = lambda vv, aa: flight(vv, k, aa, dh, along, across)
    up, dn, hi, lo = f(v + 1, ang), f(v - 1, ang), f(v, ang + 0.002), f(v, ang - 0.002)
    if not (up and dn and hi and lo):
        return None
    dRdv, dRda = (up['range'] - dn['range']) / 2, (hi['range'] - lo['range']) / 0.004
    sd_speed, barrel = abs(dRdv) * SPEED_SD * coef, BARREL / 2
    return {'long': P90 * math.hypot(sd_speed, dRda * barrel), 'side': P90 * d * barrel / math.cos(ang), 'sd_speed': sd_speed}


def solve(w, s, frm, to, ter, wind=None):
    W = TABLES[w]
    mpc = W['milsPerCircle']
    prefab, v0, k, coefs = SHELLS[(w, s)]
    d = math.dist(frm, to)
    dh = ter.ground(*to) - ter.ground(*frm)
    az = bearing(frm, to)
    along, across = wind_parts(wind, az)
    rings = []
    for ring, df in W['shells'][s].items():
        t = df['table']
        if d < t[0][0] or d > t[-1][0]:
            continue
        coef = coefs[int(ring)]
        v = v0 * coef
        real = high_angle(v, k, d, dh - MUZZLE_H, along, across)
        if not real:
            continue
        elev = real['ang'] * mpc / (2 * math.pi)
        if elev > t[0][1] + 40:
            continue
        rings.append({'ring': int(ring), 'elev': elev, 'tof': real['tof'], 'coef': coef,
                      'az_mil': az * mpc / 360 - math.atan2(real['drift'], d) * mpc / (2 * math.pi),
                      'spread': spread_of(v, coef, k, real['ang'], dh - MUZZLE_H, along, across, d)})
    rings.sort(key=lambda r: r['ring'])
    return {'d': d, 'dh': dh, 'az': az, 'mpc': mpc, 'best': rings[0] if rings else None, 'prefab': prefab}


# --- the plan -------------------------------------------------------------------------------------------------------
def make_plan(seed=11):
    ter = Terrain()
    rnd = random.Random(seed)
    rows = []

    def land(x, z):
        return 200 < x < 12800 and 200 < z < 12800 and ter.ground(x, z) > 3 and not ter.near(x, z)

    def row(kind, sol, frm, to, wind, count, elev=None, az=None, probe=False):
        b, mpc = sol['best'], sol['mpc']
        # The game's wind override takes its own direction: where the wind blows TOWARD. Its map shows that + 180,
        # which is what a crew types into the site as "from".
        rows.append({'id': f'{kind}{len(rows):03d}', 'prefab': sol['prefab'], 'coef': b['coef'], 'x': frm[0], 'z': frm[1],
                     'az': az if az is not None else b['az_mil'] / mpc * 360, 'elev': elev if elev is not None else b['elev'] / mpc * 360,
                     'wspeed': wind[0] if wind else 0, 'wdir': ((wind[1] - 180) % 360) if wind else 0, 'count': count,
                     'tx': to[0], 'tz': to[1], 'ring': b['ring'], 'd': sol['d'], 'dh': sol['dh'], 'map_az': sol['az'],
                     'wind_from': wind[1] if wind else None, 'tof': b['tof'], 'spread': b['spread'], 'probe': probe})

    def add(kind, w, s, frm, to, wind, count):
        sol = solve(w, s, frm, to, ter, wind)
        if sol['best']:
            row(kind, sol, frm, to, wind, count)
            rows[-1].update(w=w, s=s)

    def pairs(n, dmin, dmax, want_dh=None):
        out = []
        while len(out) < n:
            frm = (rnd.uniform(1000, 11800), rnd.uniform(1000, 11800))
            # a mortar in the open: nothing standing within 12 m that a low shot could clip on its way out
            if not land(*frm) or ter.near(*frm, r=12, kinds=(1, 2, 3, 5)):
                continue
            az, d = rnd.uniform(0, 360), rnd.uniform(dmin, dmax)
            to = (frm[0] + d * math.sin(math.radians(az)), frm[1] + d * math.cos(math.radians(az)))
            if not land(*to):
                continue
            dh = ter.ground(*to) - ter.ground(*frm)
            if want_dh and not (want_dh[0] <= dh <= want_dh[1]):
                continue
            out.append((frm, to))
        return out

    # H: target well below, level, and well above the mortar (no wind)
    for w, s in SHELLS:
        for band in ((-250, -60), (-60, -15), (-15, 15), (15, 60), (60, 250)):
            for frm, to in pairs(2, 400, 2600, band):
                add('H', w, s, frm, to, None, 6)
    # T: whole flights recorded (traj.csv): big drops, big climbs and level
    for w, s in SHELLS:
        for band in ((-250, -120), (100, 250), (-5, 5)):
            for frm, to in pairs(1, 700, 2200, band):
                add('T', w, s, frm, to, None, 3)
    # W: 8 m/s from three directions (as the in-game map shows it), solved with the wind
    for wind in ((8, 90), (8, 225), (8, 0)):
        for w, s in SHELLS:
            for frm, to in pairs(2, 800, 2400):
                add('W', w, s, frm, to, wind, 6)
    # P: the same aim with no wind, then 10 m/s from four sides, aimed with no wind correction
    frm, to = pairs(1, 1500, 1500, (-5, 5))[0]
    sol = solve('M252', 'HE M821', frm, to, ter, None)
    for wind in (None, (10, 180), (10, 270), (10, 0), (10, 90)):
        row('P', sol, frm, to, wind, 6, probe=True)
        rows[-1].update(w='M252', s='HE M821')
    # S: 20 rounds at a short, middle and long aim for each mortar (no wind)
    for w, s in SHELLS:
        for dmin, dmax in ((500, 700), (1400, 1600), (2300, 2500)):
            for frm, to in pairs(1, dmin, dmax, (-5, 5)):
                add('S', w, s, frm, to, None, 20)
    rows.sort(key=lambda r: (r['wspeed'], r['wdir']))  # the game changes the wind only between groups
    return rows


def game_dir():
    from rmtlib.steam import Install
    return os.path.join(Install(None).game_profile, *OUT_REL.split('/'), 'firetest')


def write_plan(rows):
    d = game_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'plan.csv'), 'w', newline='') as f:
        f.write('id,prefab,coef,x,z,az,elev,wspeed,wdir,count,tx,tz\n')
        for r in rows:
            f.write(f"{r['id']},{r['prefab']},{r['coef']},{r['x']:.2f},{r['z']:.2f},{r['az']:.5f},{r['elev']:.5f},"
                    f"{r['wspeed']},{r['wdir']},{r['count']},{r['tx']:.2f},{r['tz']:.2f}\n")
    json.dump(rows, open(os.path.join(d, 'plan.json'), 'w'), indent=1)
    print(f"plan: {len(rows)} aims, {sum(r['count'] for r in rows)} rounds -> {d}")


def run():
    from rmtlib.steam import Install
    from rmtlib.workbench import Runner
    write_plan(make_plan())
    code, lines, status = Runner(Install(None)).run_game('firetest', OUT_REL, WORLD, flag='-rmtFire', stall=300, limit=3600)
    print('exit', code, 'status', status)


# --- scoring --------------------------------------------------------------------------------------------------------
def score(d):
    plan = {p['id']: p for p in json.load(open(os.path.join(d, 'plan.json')))}
    rows = list(csv.DictReader(open(os.path.join(d, 'shots.csv'), newline='')))
    shots = collections.defaultdict(list)
    for r in rows:
        shots[r['id']].append(r)
    print(f"{len(rows)} rounds landed, {len(shots)} aims ({d})")

    ter = Terrain()
    hd = [abs(ter.ground(plan[i]['x'], plan[i]['z']) - float(ss[0]['ground_mortar'])) for i, ss in shots.items()] + \
         [abs(ter.ground(plan[i]['tx'], plan[i]['tz']) - float(ss[0]['ground_target'])) for i, ss in shots.items()]
    print(f"\nterrain: the site's ground height against the game's at every mortar and target: mean {statistics.mean(hd):.2f} m, "
          f"worst {max(hd):.2f} m")

    # launch speed: the game's random variation, on the base speed (the ring multiplies it)
    var = [math.sqrt(sum(float(r[c]) ** 2 for c in ('v0x', 'v0y', 'v0z'))) / plan[r['id']]['coef'] - SHELLS[(plan[r['id']]['w'], plan[r['id']]['s'])][1]
           for r in rows]
    print(f"launch speed, on the base speed: mean {statistics.mean(var):+.2f} m/s, sd {statistics.stdev(var):.2f} "
          f"(site uses {SPEED_SD}), extremes {min(var):+.2f} / {max(var):+.2f}")

    # 1. physics: each round from its real launch to the height it landed at
    res = collections.defaultdict(list)
    for r in rows:
        p = plan[r['id']]
        v0 = [float(r['v0x']), float(r['v0y']), float(r['v0z'])]
        sp = math.sqrt(sum(c * c for c in v0))
        el, az = math.asin(v0[1] / sp), math.atan2(v0[0], v0[2])
        ws, wd = float(r['wind_speed']), math.radians(float(r['wind_dir']))
        wx, wz = ws * math.sin(wd), ws * math.cos(wd)  # the game's direction: where the wind blows toward
        along, across = wx * math.sin(az) + wz * math.cos(az), wx * math.cos(az) - wz * math.sin(az)
        f = flight(sp, SHELLS[(p['w'], p['s'])][2], el, float(r['y']) - float(r['y0']), along, across)
        if not f:
            continue
        dx, dz = float(r['x']) - float(r['x0']), float(r['z']) - float(r['z0'])
        res[r['id'][0]].append((dx * math.sin(az) + dz * math.cos(az) - f['range'], dx * math.cos(az) - dz * math.sin(az) - f['drift']))
    print("\n1) physics: every round flown by the site's model from its real launch, against where it landed")
    names = {'H': 'height differences', 'T': 'recorded flights', 'W': 'wind, corrected', 'P': 'wind probe', 'S': 'spread groups'}
    for g, v in sorted(res.items()):
        rr, dd = [a for a, _ in v], [b for _, b in v]
        med = statistics.median(abs(x) for x in rr)
        print(f"   {names.get(g, g):20s} {len(v):4d} rounds: range off by median {med:.2f} m (mean {statistics.mean(rr):+.2f}), "
              f"sideways mean {statistics.mean(dd):+.2f} m; {sum(abs(x) > 10 for x in rr)} rounds over 10 m (they hit something on the way)")

    # 2. aims: the rounds' centre against the target, as fired and with every round's own speed error taken out (its
    # distance long or short, less what its speed error alone moved it). The game's speed error drifts with time instead
    # of being new for every round, so the rounds of one aim share much of it and the raw centre can sit well off; with
    # it taken out, the centre is where the site's aim puts the rounds.
    print("\n2) aims: centre of the rounds (median, m long +) against the target: as fired, and with each round's speed error taken out")
    fixed_all = []
    for id_, ss in sorted(shots.items()):
        p = plan[id_]
        if p.get('probe'):
            continue
        _, v0, k, _ = SHELLS[(p['w'], p['s'])]
        vn, a, ang = v0 * p['coef'], math.radians(p['map_az']), math.radians(p['elev'])
        along, across = wind_parts((p['wspeed'], p['wind_from']) if p['wspeed'] else None, p['map_az'])
        dh = p['dh'] - MUZZLE_H
        dRdv = flight(vn + 0.5, k, ang, dh, along, across)['range'] - flight(vn - 0.5, k, ang, dh, along, across)['range']
        longs, sides, fixed = [], [], []
        for s in ss:
            dx, dz = float(s['x']) - p['tx'], float(s['z']) - p['tz']
            l = dx * math.sin(a) + dz * math.cos(a)
            v = math.sqrt(sum(float(s[c]) ** 2 for c in ('v0x', 'v0y', 'v0z')))
            longs.append(l); sides.append(dx * math.cos(a) - dz * math.sin(a)); fixed.append(l - dRdv * (v - vn))
        fixed_all.append(statistics.median(fixed))
        wind = f"{p['wspeed']}@{p['wind_from']}" if p['wspeed'] else '-'
        print(f"   {id_}  {p['w']:4s} ring {p['ring']}  {p['d']:5.0f} m  dh {p['dh']:+5.0f}  wind {wind:7s}  "
              f"as fired {statistics.median(longs):+7.1f} m long, {statistics.median(sides):+5.1f} m right   "
              f"speed error out {statistics.median(fixed):+6.1f} m")
    print(f"   {len(fixed_all)} aims: with the speed error out, the centre is a median {statistics.median(map(abs, fixed_all)):.1f} m "
          f"from the target; {sum(abs(x) > 10 for x in fixed_all)} over 10 m")

    # 3. spread: the speed part of the long/short spread
    print("\n3) spread groups: long/short spread (sd) against the site's speed part (a direct launch has no barrel spread)")
    for id_, ss in sorted(shots.items()):
        p = plan[id_]
        if id_[0] != 'S' or not p.get('spread'):
            continue
        a = math.radians(p['map_az'])
        longs = [(float(s['x']) - p['tx']) * math.sin(a) + (float(s['z']) - p['tz']) * math.cos(a) for s in ss]
        print(f"   {id_}  {p['w']} ring {p['ring']} at {p['d']:.0f} m: measured sd {statistics.stdev(longs):5.1f} m, "
              f"site's speed part {p['spread']['sd_speed']:5.1f} m; the site's 90% ellipse: +/-{p['spread']['long']:.0f} m long, "
              f"+/-{p['spread']['side']:.0f} m side")

    # 4. the wind probe
    print("\n4) wind probe (same aim, no wind correction): centre of the rounds")
    for id_, ss in sorted(shots.items()):
        p = plan[id_]
        if not p.get('probe'):
            continue
        a = math.radians(p['map_az'])
        ml = statistics.mean((float(s['x']) - p['tx']) * math.sin(a) + (float(s['z']) - p['tz']) * math.cos(a) for s in ss)
        mr = statistics.mean((float(s['x']) - p['tx']) * math.cos(a) - (float(s['z']) - p['tz']) * math.sin(a) for s in ss)
        wind = f"{p['wspeed']} m/s from {p['wind_from']} (map)" if p['wspeed'] else 'no wind'
        print(f"   {id_}  {wind:24s} aim bearing {p['map_az']:3.0f}: {ml:+6.1f} m long, {mr:+6.1f} m right")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('plan', 'run', 'score'))
    ap.add_argument('folder', nargs='?', help='score: a run folder (default: the last run in the game profile)')
    ap.add_argument('--site', default=SITE, help='the field map\'s static/data folder')
    args = ap.parse_args()
    SITE = args.site
    TABLES = json.load(open(os.path.join(SITE, 'mortar-tables.json')))['weapons']
    if args.cmd == 'plan':
        write_plan(make_plan())
    elif args.cmd == 'run':
        run()
    else:
        score(args.folder or game_dir())
