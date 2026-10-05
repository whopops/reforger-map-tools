"""Live mortar firing test for the Arma Reforger Maps field map (github.com/whopops/arma-map).

Plans aims on Everon with the field map's own firing solution (a line-for-line Python copy of static/app.js: solve,
flight, highAngleFor, windParts, spreadOf, and its 1 m terrain), fires them as real shells in the game (the RMT_FireTest
entity, Scripts/Game/RMT/RMT_FireTest.c), and scores where every round landed.

  python firetest.py plan               write the plan into the game profile
  python firetest.py run                plan, then run the game (Steam running, the game closed); ~25 min
  python firetest.py score [folder]     report on the last run (or a copy of one)
  python firetest.py group [folder]     one aim fired again and again with the same numbers, a pause between rounds
                                        (as a crew re-laying after each); then where each landed. With a folder: just
                                        report on it. --distance 1200 --ring 3 --rounds 10 --gap 15
  python firetest.py gun [folder]       the same, fired through a real mortar (RMT_GunTest.c: no crew; the tube is laid
                                        on the numbers before every round, the shell loaded into the barrel and fired),
                                        so the barrel's dispersion is in it; then where each landed and how far each left
                                        the barrel's direction. Same options.
  python firetest.py barrel [folder]    the muzzle study: every charge ring of both mortars through the real weapon,
                                        --per-ring rounds each (default 40), each measured leaving the muzzle (speed,
                                        and direction against the barrel); 1 in 8 followed to impact. ~1 h.
  options: --site <everon-map/static/data> (default ~/Documents/GitHub/arma-map/everon-map/static/data)

What each round tells us:
  * its launch velocity (the game adds a random speed): the site's physics, flown from that exact launch to the height it
    landed at, against where it really landed. This is the physics with no randomness left in it.
  * the aims: where the rounds' centre landed against the target, with its standard error (6 rounds is noisy: the random
    speed alone spreads rounds 20-60 m long and short).
  * the spread groups (20 rounds): the long/short spread against the site's prediction for the speed part. (Launching
    directly doesn't use the mortar's barrel, so the barrel's sideways spread isn't in a direct launch.)
  * the wind probe: the same aim with no wind and 10 m/s from four sides, uncorrected, to show how the game's wind pushes.

Keep the SHELLS, MUZZLE_H, SPEED_SD, SPEED_BIAS, BARREL, BARREL_SD and P90 numbers in step with app.js.
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
# Measured through the real mortars (firetest.py barrel, 400 rounds; with the direct launches, 1,080 rounds): the game's
# launch speeds average 0.13 m/s above the shell's (on the base speed: the ring multiplies it), and the barrel throws a
# round off its direction by a spread (sd, rad) that differs by mortar and by axis: up/down, sideways. BARREL is the most
# it can (0.5 m at 48 m).
SPEED_BIAS = 0.13
_MIL = 2 * math.pi / 6400
BARREL_SD = {'M252': (3.09 * _MIL, 4.19 * _MIL), '2B14': (3.90 * _MIL, 2.94 * _MIL)}
TABLES = None


# --- the site's terrain (static/data/maps/everon/los tiles: 1 m terrain, and what stands on every 0.5 m) -------------
class Terrain:
    def __init__(self):
        d = os.path.join(SITE, 'maps', 'everon', 'los')
        self.dir = d
        with open(os.path.join(d, 'index.json')) as f:
            ix = json.load(f)
        self.names = set(ix['tiles'])
        self.unit = ix['terrain']['unit']
        self.cache = {}

    def tile(self, x, z):
        name = f'{int(x // 500)}_{int(z // 500)}'
        if name not in self.names:
            return None
        if name not in self.cache:
            with gzip.open(os.path.join(self.dir, name + '.bin.gz')) as f:
                raw = f.read()
            ter = struct.unpack_from('<%dH' % (501 * 501), raw, 0)
            # Layout: terrain, top, bottom, kind, cover (as in los/index.json).
            kind = raw[501 * 501 * 2 + 2 * 1000 * 1000: 501 * 501 * 2 + 3 * 1000 * 1000]
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


MIN_ELEV = math.radians(45)  # the flattest the tube fires: LimitsVert 45 85 in Prefabs/Weapons/Core/Mortar_Base.et


def high_angle(v, k, d, dh, along, across):
    lo, hi = MIN_ELEV, math.radians(89.5)
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


def spread_of(v, coef, k, ang, dh, along, across, d, w='M252'):
    """spreadOf(): the 90% ellipse's half-lengths along and across the line of fire, and the speed part's sd (m)"""
    f = lambda vv, aa: flight(vv, k, aa, dh, along, across)
    up, dn, hi, lo = f(v + 1, ang), f(v - 1, ang), f(v, ang + 0.002), f(v, ang - 0.002)
    if not (up and dn and hi and lo):
        return None
    dRdv, dRda = (up['range'] - dn['range']) / 2, (hi['range'] - lo['range']) / 0.004
    b_up, b_side = BARREL_SD[w]
    sd_speed = abs(dRdv) * SPEED_SD * coef
    return {'long': P90 * math.hypot(sd_speed, dRda * b_up), 'side': P90 * d * b_side / math.cos(ang), 'sd_speed': sd_speed}


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
        if d < t[0][0]:  # the table sets the shortest distance; the reach comes from the model (high_angle at MIN_ELEV)
            continue
        coef = coefs[int(ring)]
        v = (v0 + SPEED_BIAS) * coef
        real = high_angle(v, k, d, dh - MUZZLE_H, along, across)
        if not real:
            continue
        elev = real['ang'] * mpc / (2 * math.pi)
        if elev > t[0][1] + 40:
            continue
        rings.append({'ring': int(ring), 'elev': elev, 'tof': real['tof'], 'coef': coef,
                      'az_mil': az * mpc / 360 - math.atan2(real['drift'], d) * mpc / (2 * math.pi),
                      'spread': spread_of(v, coef, k, real['ang'], dh - MUZZLE_H, along, across, d, w)})
    rings.sort(key=lambda r: r['ring'])
    return {'d': d, 'dh': dh, 'az': az, 'mpc': mpc, 'best': rings[0] if rings else None, 'rings': rings, 'prefab': prefab}


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
    probe_w, probe_s = next(iter(SHELLS))
    sol = solve(probe_w, probe_s, frm, to, ter, None)
    for wind in ((None, (10, 180), (10, 270), (10, 0), (10, 90)) if sol['best'] else ()):
        row('P', sol, frm, to, wind, 6, probe=True)
        rows[-1].update(w=probe_w, s=probe_s)
    # S: 20 rounds at a short, middle and long aim for each mortar (no wind)
    for w, s in SHELLS:
        for dmin, dmax in ((500, 700), (1400, 1600), (2300, 2500)):
            for frm, to in pairs(1, dmin, dmax, (-5, 5)):
                add('S', w, s, frm, to, None, 20)
    rows.sort(key=lambda r: (r['wspeed'], r['wdir']))  # the game changes the wind only between groups
    return rows


def group_plan(dist=1200, ring=3, rounds=10, w=None, s=None, seed=5):
    """One aim, fired `rounds` times with the same elevation and azimuth: the spread a crew sees re-laying the same
    numbers after every round. Level, open ground at both ends, no wind, the ring asked for."""
    if w is None or s is None: w, s = next(iter(SHELLS))
    ter = Terrain()
    rnd = random.Random(seed)
    for _ in range(100000):
        frm = (rnd.uniform(1000, 11800), rnd.uniform(1000, 11800))
        if ter.ground(*frm) < 3 or ter.near(*frm, r=12, kinds=(1, 2, 3, 5)):
            continue
        az = rnd.uniform(0, 360)
        to = (frm[0] + dist * math.sin(math.radians(az)), frm[1] + dist * math.cos(math.radians(az)))
        if ter.ground(*to) < 3 or ter.near(*to) or abs(ter.ground(*to) - ter.ground(*frm)) > 3:
            continue
        sol = solve(w, s, frm, to, ter)
        b = next((r for r in sol['rings'] if r['ring'] == ring), None)
        if not b:
            continue
        mpc = sol['mpc']
        return [{'id': 'G000', 'prefab': sol['prefab'], 'coef': b['coef'], 'x': frm[0], 'z': frm[1],
                 'az': b['az_mil'] / mpc * 360, 'elev': b['elev'] / mpc * 360, 'wspeed': 0, 'wdir': 0, 'count': rounds,
                 'tx': to[0], 'tz': to[1], 'ring': ring, 'd': sol['d'], 'dh': sol['dh'], 'map_az': sol['az'],
                 'wind_from': None, 'tof': b['tof'], 'spread': b['spread'], 'probe': False, 'w': w, 's': s,
                 'elev_mil': b['elev'], 'az_mil': b['az_mil']}]
    raise SystemExit('no level aim found')


def group_score(d):
    """Where each round of the group landed against the target, and the group's size."""
    p = json.load(open(os.path.join(d, 'plan.json')))[0]
    rows = list(csv.DictReader(open(os.path.join(d, 'shots.csv'), newline='')))
    a = math.radians(p['map_az'])
    pts = []
    for r in rows:
        dx, dz = float(r['x']) - p['tx'], float(r['z']) - p['tz']
        pts.append((dx * math.sin(a) + dz * math.cos(a), dx * math.cos(a) - dz * math.sin(a)))
    print(f"{p['w']} {p['s']} ring {p['ring']} at {p['d']:.0f} m (target {p['dh']:+.1f} m above the mortar), no wind: "
          f"elevation {p['elev_mil']:.0f} mil, azimuth {p['az_mil']:.0f} mil, the same for every round")
    for i, (l, s) in enumerate(pts):
        print(f'   round {i + 1:2d}: {l:+7.1f} m long, {s:+6.1f} m right   ({math.hypot(l, s):5.1f} m from the target)')
    n = len(pts)
    ml, ms = statistics.mean(l for l, _ in pts), statistics.mean(s for _, s in pts)
    rt = sorted(math.hypot(l, s) for l, s in pts)
    rc = sorted(math.hypot(l - ml, s - ms) for l, s in pts)
    print(f'{n} rounds. Centre of the group: {ml:+.1f} m long, {ms:+.1f} m right of the target.')
    print(f'   from the target: half within {statistics.median(rt):.1f} m, all within {rt[-1]:.1f} m')
    print(f'   from the group centre: half within {statistics.median(rc):.1f} m, all within {rc[-1]:.1f} m')
    if n > 2:
        print(f'   spread (sd): {statistics.stdev(l for l, _ in pts):.1f} m long/short, {statistics.stdev(s for _, s in pts):.1f} m sideways')
    sp = p['spread']
    print(f"the site's 90% ellipse for this shot: +/-{sp['long']:.0f} m long/short, +/-{sp['side']:.0f} m sideways "
          f"(sd {sp['long'] / P90:.1f} m and {sp['side'] / P90:.1f} m; the speed part alone sd {sp['sd_speed']:.1f} m long/short). "
          'A direct launch has no barrel wobble, so the sideways spread here is only the launch.')


MORTARS = {'M252': 'Prefabs/Weapons/Mortars/M252/Mortar_M252.et', '2B14': 'Prefabs/Weapons/Mortars/2B14/Mortar_2B14.et'}
GUN_REL = 'rmt/guntest'


def gun_run(p, rounds, gap):
    """Fire plan p (from group_plan) through a real mortar (RMT_GunTest.c): laid on the numbers before every round."""
    from blasttest import prefab_name
    from rmtlib.steam import Install
    from rmtlib.labselection import runner as lab_runner
    d = os.path.join(Install(None).game_profile, *GUN_REL.split('/'), 'gun')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'plan.csv'), 'w', newline='') as f:
        f.write('id,mortar,shell,ring,x,z,az,elev,count,tx,tz,gap\n')
        f.write(f"{p['id']},{prefab_name(MORTARS[p['w']])},{p['prefab']},{p['ring']},{p['x']:.2f},{p['z']:.2f},"
                f"{p['az']:.5f},{p['elev']:.5f},{rounds},{p['tx']:.2f},{p['tz']:.2f},{gap}\n")
    json.dump([p], open(os.path.join(d, 'plan.json'), 'w'), indent=1)
    print(f"plan: {p['w']} {p['s']} ring {p['ring']}, {rounds} rounds at {p['d']:.0f} m -> {d}")
    code, lines, status = lab_runner(Install(None)).run_game('guntest', GUN_REL, WORLD, flag='-rmtGun', stall=300, limit=3600)
    print('exit', code, 'status', status)
    return d


def gun_score(d):
    """Where each round fired through the real mortar landed, how well the tube was laid, and how far each round left
    the barrel's direction (the barrel's dispersion, which a direct launch never has)."""
    p = json.load(open(os.path.join(d, 'plan.json')))[0]
    rows = list(csv.DictReader(open(os.path.join(d, 'shots.csv'), newline='')))
    mpc = 6400
    a = math.radians(p['map_az'])
    to_mil = lambda rad: rad * mpc / (2 * math.pi)
    print(f"{p['w']} {p['s']} ring {p['ring']} at {p['d']:.0f} m (target {p['dh']:+.1f} m above the mortar), no wind; "
          f"laid on elevation {p['elev_mil']:.1f} mil, azimuth {p['az'] * mpc / 360:.1f} mil before every round")
    pts, d_el, d_az, speeds, lay = [], [], [], [], []
    for i, r in enumerate(rows):
        dx, dz = float(r['x']) - p['tx'], float(r['z']) - p['tz']
        l, s = dx * math.sin(a) + dz * math.cos(a), dx * math.cos(a) - dz * math.sin(a)
        pts.append((l, s))
        # the barrel's direction, and the shell's when it left (gravity taken back out of the first velocity seen)
        b = [float(r[k]) for k in ('bx', 'by', 'bz')]
        v = [float(r['v0x']), float(r['v0y']) + GRAV * float(r['v0dt']), float(r['v0z'])]
        sp = math.sqrt(sum(c * c for c in v))
        speeds.append(sp)
        b_el, b_az = math.asin(b[1] / math.sqrt(sum(c * c for c in b))), math.atan2(b[0], b[2])
        v_el, v_az = math.asin(v[1] / sp), math.atan2(v[0], v[2])
        de = to_mil(v_el - b_el)
        da = to_mil((v_az - b_az + math.pi) % (2 * math.pi) - math.pi) * math.cos(b_el)  # as an angle across the shot
        d_el.append(de); d_az.append(da)
        lay.append((float(r['lay_el']) - p['elev'], ((float(r['lay_az']) - p['az'] + 180) % 360 - 180)))
        print(f'   round {i + 1:2d}: {l:+7.1f} m long, {s:+6.1f} m right ({math.hypot(l, s):5.1f} m from the target); '
              f'left the barrel {de:+5.2f} mil up, {da:+5.2f} mil right, at {sp:6.2f} m/s')
    n = len(pts)
    if not n:
        print('no rounds landed')
        return
    print(f"   the tube was laid within {max(abs(e) for e, _ in lay) * mpc / 360:.2f} mil in elevation and "
          f"{max(abs(z) for _, z in lay) * mpc / 360:.2f} mil in azimuth of the numbers every time")
    ml, ms = statistics.mean(l for l, _ in pts), statistics.mean(s for _, s in pts)
    rt = sorted(math.hypot(l, s) for l, s in pts)
    rc = sorted(math.hypot(l - ml, s - ms) for l, s in pts)
    print(f'{n} rounds. Centre of the group: {ml:+.1f} m long, {ms:+.1f} m right of the target.')
    print(f'   from the target: half within {statistics.median(rt):.1f} m, 90% within {rt[min(n - 1, int(math.ceil(0.9 * n)) - 1)]:.1f} m, '
          f'all within {rt[-1]:.1f} m')
    print(f'   from the group centre: half within {statistics.median(rc):.1f} m, all within {rc[-1]:.1f} m')
    if n > 2:
        print(f'   spread (sd): {statistics.stdev(l for l, _ in pts):.1f} m long/short, {statistics.stdev(s for _, s in pts):.1f} m sideways')
        print(f'   barrel dispersion (sd): {statistics.stdev(d_el):.2f} mil up/down, {statistics.stdev(d_az):.2f} mil sideways; '
              f'largest {max(math.hypot(e, z) for e, z in zip(d_el, d_az)):.2f} mil off the barrel. Launch speed sd {statistics.stdev(speeds):.2f} m/s')
    sp = p['spread']
    print(f"the site's 90% ellipse for this shot: +/-{sp['long']:.0f} m long/short, +/-{sp['side']:.0f} m sideways "
          f"(sd {sp['long'] / P90:.1f} m and {sp['side'] / P90:.1f} m). The site's barrel spread for the {p['w']}: sd "
          f"{to_mil(BARREL_SD[p['w']][0]):.2f} mil up/down, {to_mil(BARREL_SD[p['w']][1]):.2f} mil sideways (measured), "
          f"never past {to_mil(BARREL):.1f} mil.")


# --- the muzzle study: every charge ring of both mortars, fired through the real weapon ------------------------------
BARREL_REL = 'rmt/barreltest'
STUDY = (('M252', 'HE M821'), ('2B14', 'HE O-832DU'))
FRESH_GUN = 20


def barrel_plan(per_ring=40, track_every=8, seed=21):
    """Rows for RMT_GunTest: per mortar one spot, and per charge ring a target at about the middle of that ring's reach,
    level ground, no wind. per_ring rounds per ring, the rings taken in a fresh random order every cycle so the game's
    slowly drifting launch speed falls on all of them alike. Every track_every-th round is followed to impact; the rest
    are only measured leaving the muzzle (how fast, which way against the barrel), which is all the spread depends on."""
    from blasttest import prefab_name
    ter = Terrain()
    rnd = random.Random(seed)
    rows = []
    for w, s in STUDY:
        rings = sorted(int(r) for r in TABLES[w]['shells'][s])
        mortar = prefab_name(MORTARS[w])
        for _ in range(200000):
            frm = (rnd.uniform(1500, 11300), rnd.uniform(1500, 11300))
            if ter.ground(*frm) < 3 or ter.near(*frm, r=15, kinds=(1, 2, 3, 5)):
                continue
            az = rnd.uniform(0, 360)
            aims, ok = {}, True
            for ring in rings:
                t = TABLES[w]['shells'][s][str(ring)]['table']
                dist = (t[0][0] + t[-1][0]) / 2
                to = (frm[0] + dist * math.sin(math.radians(az)), frm[1] + dist * math.cos(math.radians(az)))
                if ter.ground(*to) < 3 or abs(ter.ground(*to) - ter.ground(*frm)) > 15:
                    ok = False
                    break
                sol = solve(w, s, frm, to, ter)
                b = next((r for r in sol['rings'] if r['ring'] == ring), None)
                if not b:
                    ok = False
                    break
                aims[ring] = (to, sol, b)
            if ok:
                break
        else:
            raise SystemExit(f'no spot found for {w}')
        n = 0
        for cycle in range(per_ring):
            order = rings[:]
            rnd.shuffle(order)
            for ring in order:
                to, sol, b = aims[ring]
                mpc = sol['mpc']
                # a fresh gun every FRESH_GUN rounds: one gun fired about 140 times stopped the game with "BitBuffer
                # memory overflow". Lines for a gun in a new place get a new gun; 1 cm along is a new place.
                rows.append({'id': f'{w}-R{ring}-{cycle:02d}', 'w': w, 's': s, 'ring': ring, 'mortar': mortar,
                             'prefab': sol['prefab'], 'coef': b['coef'], 'x': frm[0] + (n // FRESH_GUN) * 0.01, 'z': frm[1],
                             'az': b['az_mil'] / mpc * 360, 'elev': b['elev'] / mpc * 360, 'tx': to[0], 'tz': to[1],
                             'd': sol['d'], 'dh': sol['dh'], 'map_az': sol['az'], 'spread': b['spread'],
                             'gap': round(rnd.uniform(1, 5), 2), 'track': int(cycle % track_every == 0)})
                n += 1
    return rows


def barrel_run(rows, rel=BARREL_REL):
    from rmtlib.steam import Install
    from rmtlib.labselection import runner as lab_runner
    d = os.path.join(Install(None).game_profile, *rel.split('/'), 'gun')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'plan.csv'), 'w', newline='') as f:
        f.write('id,mortar,shell,ring,x,z,az,elev,count,tx,tz,gap,track\n')
        for r in rows:
            f.write(f"{r['id']},{r['mortar']},{r['prefab']},{r['ring']},{r['x']:.2f},{r['z']:.2f},{r['az']:.5f},"
                    f"{r['elev']:.5f},1,{r['tx']:.2f},{r['tz']:.2f},{r['gap']},{r['track']}\n")
    json.dump(rows, open(os.path.join(d, 'plan.json'), 'w'), indent=1)
    print(f'plan: {len(rows)} rounds ({sum(r["track"] for r in rows)} followed to impact) -> {d}')
    code, lines, status = lab_runner(Install(None)).run_game('guntest', rel, WORLD, flag='-rmtGun', stall=600, limit=3 * 3600)
    print('exit', code, 'status', status)
    return d


def launch_of(r, k):
    """A round's velocity the instant it left the muzzle: the first one seen, v0dt s later, with gravity and drag over
    that time taken back out."""
    v = [float(r['v0x']), float(r['v0y']), float(r['v0z'])]
    dt = float(r['v0dt'])
    s = math.sqrt(sum(c * c for c in v))
    a = [-k * s * v[0], -GRAV - k * s * v[1], -k * s * v[2]]
    return [v[i] - a[i] * dt for i in range(3)]


def study_rows(dirs):
    """The rounds of one or more muzzle-study runs (a run resumed in a new session goes to its own folder), with the
    plan line of each; a round in more than one run is taken from the first."""
    seen, out = set(), []
    for d in dirs:
        plan = {p['id']: p for p in json.load(open(os.path.join(d, 'plan.json')))}
        for r in csv.DictReader(open(os.path.join(d, 'shots.csv'), newline='')):
            if r['id'] in seen or not r.get('ground_target'):  # a line cut short when a run stopped
                continue
            seen.add(r['id'])
            out.append((r, plan[r['id']]))
    return out


def muzzle_samples(dirs):
    """Every round of a muzzle study: weapon, ring, coef, its launch speed against the expected (dv, m/s, and dv_base,
    on the base speed), and how far it left the barrel's direction (de up, da right, mils), plus the row and plan."""
    if isinstance(dirs, str):
        dirs = [dirs]
    out = []
    for r, p in study_rows(dirs):
        _, v0, k, coefs = SHELLS[(p['w'], p['s'])]
        v = launch_of(r, k)
        sp = math.sqrt(sum(c * c for c in v))
        b = [float(r[q]) for q in ('bx', 'by', 'bz')]
        bn = math.sqrt(sum(c * c for c in b))
        b = [c / bn for c in b]
        # the round's direction in the barrel's frame: up (in the vertical plane through the barrel) and right
        u = [c / sp for c in v]
        right = [b[2], 0.0, -b[0]]
        rn = math.sqrt(sum(c * c for c in right))
        right = [c / rn for c in right]
        up = [right[1] * b[2] - right[2] * b[1], right[2] * b[0] - right[0] * b[2], right[0] * b[1] - right[1] * b[0]]
        if up[1] < 0:
            up = [-c for c in up]
        fwd = sum(u[i] * b[i] for i in range(3))
        mil = 6400 / (2 * math.pi)
        de = math.atan2(sum(u[i] * up[i] for i in range(3)), fwd) * mil
        da = math.atan2(sum(u[i] * right[i] for i in range(3)), fwd) * mil
        coef = coefs[p['ring']]
        out.append({'w': p['w'], 's': p['s'], 'ring': p['ring'], 'coef': coef, 'speed': sp, 'dv': sp - v0 * coef,
                    'dv_base': (sp - v0 * coef) / coef, 'de': de, 'da': da, 'r': math.hypot(de, da), 'row': r, 'plan': p,
                    'v': v})
    return out


def barrel_score(dirs):
    S = muzzle_samples(dirs)
    print(f'{len(S)} rounds ({", ".join(dirs) if isinstance(dirs, list) else dirs})')
    R = BARREL * 6400 / (2 * math.pi)  # the game's dispersion circle's radius in mils (0.5 m at 48 m)
    sd = lambda xs: statistics.stdev(xs) if len(xs) > 1 else float('nan')
    print('\n1) launch speed against the shell\'s speed x the ring\'s multiplier (m/s), and per base speed (/ coef)')
    for w, s in STUDY:
        for ring in sorted({x['ring'] for x in S if x['w'] == w}):
            v = [x for x in S if x['w'] == w and x['ring'] == ring]
            dv, db = [x['dv'] for x in v], [x['dv_base'] for x in v]
            print(f'   {w} ring {ring} (x{v[0]["coef"]}): {len(v):3d} rounds, mean {statistics.mean(dv):+6.2f}, sd {sd(dv):5.2f}, '
                  f'range {min(dv):+6.2f} to {max(dv):+6.2f}; on the base speed sd {sd(db):.3f} (mean {statistics.mean(db):+.3f})')
        v = [x['dv_base'] for x in S if x['w'] == w]
        q = sorted(v)
        print(f'   {w} all rings, on the base speed: sd {sd(v):.3f} m/s, mean {statistics.mean(v):+.3f}, '
              f'5/25/50/75/95%: ' + ' '.join(f'{q[int(f * (len(q) - 1))]:+.2f}' for f in (0.05, 0.25, 0.5, 0.75, 0.95)) +
              f', extremes {q[0]:+.2f} / {q[-1]:+.2f}')
    print(f'\n2) direction off the barrel (mils). The game\'s circle: radius {R:.2f} mil. Picked evenly over its area: mean '
          f'distance {2 * R / 3:.2f}, sd {R / 2:.2f} each way, a quarter within half the radius; picked at an even distance '
          f'from the middle: mean {R / 2:.2f}, sd {R / math.sqrt(6):.2f} each way, half within half the radius.')
    for w, s in STUDY:
        v = [x for x in S if x['w'] == w]
        rr = sorted(x['r'] for x in v)
        print(f'   {w}: {len(v)} rounds: sd {sd([x["de"] for x in v]):.2f} up/down, {sd([x["da"] for x in v]):.2f} sideways; '
              f'mean {statistics.mean(x["de"] for x in v):+.2f} up, {statistics.mean(x["da"] for x in v):+.2f} right; '
              f'distance mean {statistics.mean(rr):.2f}, largest {rr[-1]:.2f}, within half the radius {sum(x < R / 2 for x in rr) / len(rr):.0%}')
        for ring in sorted({x['ring'] for x in v}):
            vr = [x for x in v if x['ring'] == ring]
            print(f'      ring {ring}: sd {sd([x["de"] for x in vr]):.2f} / {sd([x["da"] for x in vr]):.2f}, '
                  f'mean distance {statistics.mean(x["r"] for x in vr):.2f}')
    print('\n3) the rounds followed down: the model flown from each one\'s own launch, against where it landed (physics alone)')
    res = []
    for x in S:
        r, p = x['row'], x['plan']
        if float(r['tof']) < 0:
            continue
        v = x['v']
        sp = x['speed']
        el, az = math.asin(v[1] / sp), math.atan2(v[0], v[2])
        _, _, k, _ = SHELLS[(p['w'], p['s'])]
        f = flight(sp, k, el, float(r['y']) - float(r['my']))
        if not f:
            continue
        dx, dz = float(r['x']) - float(r['mx']), float(r['z']) - float(r['mz'])
        res.append((dx * math.sin(az) + dz * math.cos(az) - f['range'], dx * math.cos(az) - dz * math.sin(az) - f['drift']))
    if res:
        print(f'   {len(res)} rounds: range off by median {statistics.median(abs(a) for a, _ in res):.2f} m (worst '
              f'{max(abs(a) for a, _ in res):.2f}), sideways median {statistics.median(abs(b) for _, b in res):.2f} m')
    barrel_model(S)
    return S


def barrel_model(S, seed=3, draws=4000):
    """From a muzzle study: the constants for the site's spread (launch speed sd on the base speed, the barrel's sd each
    way), and how well the site's ellipse (spread_of, P90) with them holds 90% of rounds: the measured rounds themselves
    (each one's speed error and direction off the barrel, drawn at random from that mortar's rounds) flown by the model at
    short, middle and long range for every ring, flat ground, no wind."""
    rnd = random.Random(seed)
    mil = 6400 / (2 * math.pi)
    print('\n4) the constants the measurements give')
    consts = {}
    for w, s in STUDY:
        v = [x for x in S if x['w'] == w]
        sd_speed = statistics.stdev(x['dv_base'] for x in v)
        mean_speed = statistics.mean(x['dv_base'] for x in v)
        sd_up = statistics.pstdev([x['de'] for x in v]) / mil
        sd_side = statistics.pstdev([x['da'] for x in v]) / mil
        consts[w] = (sd_speed, sd_up, sd_side, mean_speed)
        print(f'   {w}: launch speed sd {sd_speed:.3f} m/s on the base speed (site {SPEED_SD}), mean {mean_speed:+.3f} '
              f'(site {SPEED_BIAS:+.2f}); barrel sd {sd_up * mil:.2f} mil up/down, {sd_side * mil:.2f} mil sideways '
              f'(site {BARREL_SD[w][0] * mil:.2f} / {BARREL_SD[w][1] * mil:.2f})')
    print(f'\n5) the site\'s ellipse (its own constants) against the measured rounds flown by the model ({draws} draws each);'
          ' aimed as the site aims, so the measured rounds\' speed bias is in the aim only as far as SPEED_BIAS takes it')
    worst = []
    for w, s in STUDY:
        _, v0, k, coefs = SHELLS[(w, s)]
        pool = [x for x in S if x['w'] == w]
        for ring in sorted(int(r) for r in TABLES[w]['shells'][s]):
            t = TABLES[w]['shells'][s][str(ring)]['table']
            for frac in (0.15, 0.5, 0.85):
                d = t[0][0] + (t[-1][0] - t[0][0]) * frac
                v = (v0 + SPEED_BIAS) * coefs[ring]   # the speed the site aims with
                real = high_angle(v, k, d, -MUZZLE_H, 0, 0)
                if not real:
                    continue
                ang = real['ang']
                sp = spread_of(v, coefs[ring], k, ang, -MUZZLE_H, 0, 0, d, w)
                sd_long, sd_side = sp['long'] / P90, sp['side'] / P90
                # the rounds: each drawn round's speed error (scaled to this ring; it carries the game's own bias) and
                # direction off the barrel
                pts = []
                for _ in range(draws):
                    x = rnd.choice(pool)
                    vv = v0 * coefs[ring] + x['dv_base'] * coefs[ring]
                    aa = ang + x['de'] / mil
                    f = flight(vv, k, aa, -MUZZLE_H)
                    if not f:
                        continue
                    side = math.tan(x['da'] / mil / math.cos(ang)) * f['range']
                    pts.append((f['range'] - real['range'], side))
                m_l = statistics.mean(a for a, _ in pts)
                q = sorted(math.sqrt(((a - 0) / sd_long) ** 2 + (b / sd_side) ** 2) for a, b in pts)
                inside = sum(z <= P90 for z in q) / len(q)
                need = q[int(0.9 * len(q))]
                worst.append(need)
                rr = sorted(math.hypot(a, b) for a, b in pts)
                print(f'   {w} ring {ring} {d:5.0f} m: ellipse +/-{P90 * sd_long:4.0f} x {P90 * sd_side:3.0f} m holds {inside:5.1%}; '
                      f'size for 90%: {need:.2f} sd (site {P90}); centre {m_l:+.1f} m long; rounds within '
                      f'{rr[len(rr) // 2]:.0f} m (half) / {rr[int(0.9 * len(rr))]:.0f} m (90%) of the aim')
    print(f'\n   size that holds 90% in every case above: {max(worst):.2f} sd; median {statistics.median(worst):.2f} (site uses {P90})')
    return consts


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


def run(rows=None, args=()):
    from rmtlib.steam import Install
    from rmtlib.labselection import runner as lab_runner
    write_plan(rows or make_plan())
    code, lines, status = lab_runner(Install(None)).run_game('firetest', OUT_REL, WORLD, flag='-rmtFire', args=args, stall=300, limit=3600)
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
    ap.add_argument('cmd', choices=('plan', 'run', 'score', 'group', 'gun', 'barrel'))
    ap.add_argument('--per-ring', type=int, default=40, help='barrel: rounds per charge ring of each mortar')
    ap.add_argument('--resume', help='barrel: a run folder that stopped part way: fire only the rounds it lacks (in a '
                    'new session, into --out) and score both together')
    ap.add_argument('--out', default=BARREL_REL, help=f'barrel: run folder under the game profile (default {BARREL_REL})')
    ap.add_argument('--also', action='append', default=[], help='barrel with a folder: more run folders to score with it')
    ap.add_argument('folder', nargs='?', help='score / group: a run folder to report on (default: score the last run; '
                    'group fires a new one)')
    ap.add_argument('--distance', type=float, default=1200, help='group: metres to the target')
    ap.add_argument('--ring', type=int, default=3, help='group: charge ring')
    ap.add_argument('--rounds', type=int, default=10, help='group: rounds')
    ap.add_argument('--gap', type=float, default=15, help='group: seconds between rounds (re-laying and loading)')
    ap.add_argument('--site', default=SITE, help='the field map\'s static/data folder')
    args = ap.parse_args()
    SITE = args.site
    TABLES = json.load(open(os.path.join(SITE, 'mortar-tables.json')))['weapons']
    if args.cmd == 'plan':
        write_plan(make_plan())
    elif args.cmd == 'run':
        run()
    elif args.cmd == 'group':
        if not args.folder:
            OUT_REL = 'rmt/firetest-group'  # its own folder, so the full test's results stay
            run(group_plan(args.distance, args.ring, args.rounds), args=(f'-rmtFireGap={args.gap}',))
        group_score(args.folder or game_dir())
    elif args.cmd == 'barrel':
        if args.folder:
            dirs = [args.folder] + args.also
        elif args.resume:
            # the same plan, less the rounds an earlier run (stopped part way) already has, into a folder of its own
            done = {r['id'] for r, _ in study_rows([args.resume])}
            rows = [r for r in barrel_plan(args.per_ring) if r['id'] not in done]
            dirs = [args.resume, barrel_run(rows, args.out)]
        else:
            dirs = [barrel_run(barrel_plan(args.per_ring), args.out)]
        barrel_score(dirs)
    elif args.cmd == 'gun':
        gun_score(args.folder or gun_run(group_plan(args.distance, args.ring, args.rounds)[0], args.rounds, args.gap))
    else:
        score(args.folder or game_dir())
