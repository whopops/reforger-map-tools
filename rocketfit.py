"""How the game's rockets fly, from rockettest.py's flights: flight tables and wind tables for the field map's rocket
calculator (rockets.json), and a report on how well the launchers' own sights fit the rockets.

The engine's rocket physics (MissileMoveComponent) are native and not in the files, so the site doesn't model them: it
reads these measured flights, every frame timed by the flight itself (rockettest.flight_time).
For each rocket:
  calm   the flight in still air at each test elevation (ELEVS), every DT seconds: distance along the ground and height
         above the launch point, averaged over all the still-air flights. The site interpolates between elevations.
  winds  every test wind on its own (wind_runs), per elevation: how much later, higher and further right each shot is
         than its still-air twin (rockettest.SAME_LAYOUT) at the same distance. The site blends between the wind speeds,
         sides and elevations flown: the PG-7 rockets' drift doesn't grow in step with the wind (the PG-7VL's grows
         faster, the PG-7VM's slower, the PG-7VR's turns back), and changes with elevation.
  head, tail, cross   the older summary, per 1 m/s, averaged over the elevations, for readers older than `winds`.
Every table stops where the rocket's first flight ends. Bullets (bullettest.py) use the same tables; the site flies
their wind from their drag instead (bullet_wind). Below the tables: a copy of the site's calculator (prepare,
wind_offset, shot_at, aim), which check and launchertest.py fire; test_sitesolver.py keeps it the same as the site's.
"""
import json, math, os, statistics as st

DT = 0.05
SIGHTS = {  # launcher: rocket(s), and its sight: range (m) -> angle of the bore above the line of sight (deg)
    # (Prefabs/Weapons/Launchers/*/..._base.et SightsComponent; the M72 launches its rocket 0.5 deg above its bore,
    # ProjectileSpawnPositions Angles 0.5; the PGO-7's lines measured off its reticle texture, from the cross)
    'RPG-7': {'rockets': ['PG-7VM', 'PG-7VL', 'PG-7VR'], 'spawn': 0,
              'iron': {200: 1.55, 300: 2.01, 400: 2.45, 500: 2.8}},
    'M72A3': {'rockets': ['M72A3'], 'spawn': 0.5,
              'iron': {50: -1, 100: 0, 150: 1, 200: 2, 250: 3, 300: 4, 350: 5}},
    'RPG-22': {'rockets': ['PG-22'], 'spawn': 0, 'iron': {50: 0.69, 150: 2.5, 250: 4.5}},
    'RPG-75': {'rockets': ['RPG-75'], 'spawn': 0, 'iron': {100: 1.34, 200: 2.26, 250: 3.07, 300: 4.07}},
}
# PGO-7V3 reticle (UI/Textures/Sights/PGO7/PGO7_white_solid_UI.edds, 2048 px; m_fReticleAngularSize 6 deg over
# m_fReticlePortion 0.65234 of it = 222.67 px/deg). The cross (row 445.9) is the bore; lines below it, by scale.
PGO7_PX_DEG = 0.65234 * 2048 / 6
PGO7_ROWS = {'PG-7VM': {200: 807.65, 300: 903.1, 400: 1007.69, 500: 1139.98},
             'PG-7VL': {100: 807.65, 150: 903.1, 200: 1007.69, 300: 1139.98},
             'PG-7VR': {100: 1272.37, 150: 1508.08, 200: 1750.72}}
PGO7_CROSS = 445.89
PGO7_LEAD = 0.6  # deg per lateral grid unit (133.6 px)


def at(fr, t):
    """The frame at time t, interpolated (None past the end of the flight)."""
    for a, b in zip(fr, fr[1:]):
        if a[0] <= t <= b[0]:
            f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0
            return tuple(x + (y - x) * f for x, y in zip(a, b))
    return None


def speed(q):
    return math.sqrt(q[4] ** 2 + q[5] ** 2 + q[6] ** 2)


WIND_SIDE = {90: 'right', 270: 'left', 0: 'head', 180: 'tail'}  # where a test wind blows from, for a rocket flying north
SHORT_MOST = 0.35  # s: a recording that stops this much before the others is carried on; more, and it's left out


def carried_on(p, fr, life, name=''):
    """A flight whose recording stopped short of the rocket's self-destruct time (life), carried on to it. Some runs lose
    a flight's last 0.2 s or so, a few consecutive shots at a time, in mid-air (a hitch in the game's recording, not the
    rocket: it blows up at a fixed time). Carried on at its last recorded velocity under gravity (the motor is long out;
    drag over 0.3 s moves it about 0.1 m), so tables needn't stop at the shortest recording. More than SHORT_MOST
    short: left out (None), with a note. Bullets, flown for a fixed time, are never short."""
    gap = life - fr[-1][0]
    if gap <= 0.005:
        return p, fr
    if gap > SHORT_MOST:
        print(f"  ({name} {p['id']}: recording stops {gap:.2f} s short, left out)")
        return None
    q = fr[-1]
    t = q[0] + gap
    return p, fr + [(t, q[1] + q[4] * gap, q[2] + q[5] * gap - 0.5 * 9.81 * gap * gap, q[3] + q[6] * gap) + q[4:]]


def tables(F, elevs, dt=DT, winds=False):
    """Flight tables per rocket (see the module docstring). Every table stops at the first moment any of the rocket's
    flights has ended, so no average switches to fewer flights at the end (that made the last frames jump by metres).
    `life` is how long its flights last (the median; for rockets, the self-destruct time from the moment of launch).
    winds=True adds `winds`: every test wind on its own, per elevation (see wind_runs)."""
    out = {}
    for name in dict.fromkeys(p['rocket'] for p, _ in F):
        mine = [(p, fr) for p, fr in F if p['rocket'] == name and len(fr) > 2]
        life = st.median(fr[-1][0] for _, fr in mine)
        mine = [x for x in (carried_on(p, fr, life, name) for p, fr in mine) if x]
        calm = [(p, fr) for p, fr in mine if p['wspeed'] == 0]
        n = int(min(fr[-1][0] for _, fr in mine) / dt)
        ts = [i * dt for i in range(n + 1)]
        cal = {}
        for e in elevs:
            frs = [fr for p, fr in calm if p['elev'] == e]
            cal[e] = [[round(st.mean(at(fr, t)[k] for fr in frs), 2) for k in (1, 2)] for t in ts]

        def delta(rows, t):
            ds = []
            for p, fr in rows:
                a = at(fr, t)
                bs = [at(c, t) for cp, c in calm if cp['elev'] == p['elev']]
                if a and all(bs):
                    ds.append([a[k] - st.mean(b[k] for b in bs) for k in (1, 2, 3)])
            return [st.mean(d[k] for d in ds) for k in range(3)] if ds else [0, 0, 0]

        def wind(ws_from):
            # per 1 m/s: least squares through zero over the wind speeds flown from that side
            rows = [(p, fr) for p, fr in mine if p['wspeed'] and p['wfrom'] == ws_from]
            speeds = sorted({p['wspeed'] for p, _ in rows})
            res = []
            for t in ts:
                per = [(s, delta([x for x in rows if x[0]['wspeed'] == s], t)) for s in speeds]
                ss = sum(s * s for s, _ in per)
                res.append([round(sum(s * d[k] for s, d in per) / ss, 4) for k in range(3)])
            return res

        cross, head, tail = wind(90), wind(0), wind(180)
        out[name] = {'life': round(life, 2), 'dt': dt, 'elevs': list(elevs), 'calm': [cal[e] for e in elevs],
                     'head': [r[:2] for r in head], 'tail': [r[:2] for r in tail], 'cross': cross,
                     'v0': round(st.mean(speed(fr[0]) for _, fr in calm)),  # the launch point's (rockettest.flights_in)
                     'spread': round(st.pstdev([at(fr, 2)[1] - st.mean(at(f2, 2)[1] for p2, f2 in calm if p2['elev'] == p['elev'])
                                                for p, fr in calm if at(fr, 2)]), 1)}
        if winds:
            out[name]['format'] = 2
            out[name]['winds'] = wind_runs(mine, calm, elevs, ts)
    return out


def along_at(fr, D):
    """(t, up, side) of a flight when it has come D m along the ground, or None if it never gets there."""
    for a, b in zip(fr, fr[1:]):
        if a[1] <= D <= b[1]:
            f = (D - a[1]) / ((b[1] - a[1]) or 1)
            return a[0] + (b[0] - a[0]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f
    return None


def wind_runs(mine, calm, elevs, ts):
    """Each test wind on its own: {from: right/left/head/tail, speed: m/s, by: 'distance', n: frames, step, x: per
    elevation, every `step` frames, [dt, up, side]}: when the still-air flight at that elevation is at frame k, D m
    along the ground, how much later (s), higher (m) and further right (m) the wind's flight is when it has come those
    same D m. Every shot is measured against its twin in rockettest.SAME_LAYOUT (still air, the same place in its run:
    the same draw of the game's random scatter, which so cancels), and at the same distance, so neither the scatter nor
    the recordings' time stamps get into it. Nothing is assumed about how the effect grows with wind speed, which side
    it comes from or how it changes with elevation: the site blends between the winds and elevations flown. Without a
    SAME_LAYOUT run (an older data set): against the still-air average at the same time (by: 'time', d: [along, up,
    side] every frame)."""
    from rockettest import SAME_LAYOUT
    twin = {p['elev']: fr for p, fr in mine if (p['wspeed'], p['wfrom']) == SAME_LAYOUT}
    base = {e: [[st.mean(at(fr, t)[k] for p, fr in calm if p['elev'] == e) for k in (1, 2, 3)] for t in ts] for e in elevs}
    ks = sorted(set(list(range(0, len(ts), WIND_STEP)) + [len(ts) - 1]))
    out = []
    for ws, wf in sorted({(p['wspeed'], p['wfrom']) for p, _ in mine if p['wspeed']}, key=lambda w: (WIND_SIDE.get(w[1], ''), w[0])):
        runs = [(p, fr) for p, fr in mine if (p['wspeed'], p['wfrom']) == (ws, wf)]
        if not twin:
            d = []
            for e in elevs:
                frs = [fr for p, fr in runs if p['elev'] == e]
                d.append([[round(st.mean(at(fr, t)[k] for fr in frs) - base[e][i][k - 1], 2) for k in (1, 2, 3)]
                          for i, t in enumerate(ts)] if frs else None)
            out.append({'from': WIND_SIDE.get(wf, str(wf)), 'speed': ws, 'by': 'time', 'd': d})
            continue
        x = []
        for e in elevs:
            fr = next((fr for p, fr in runs if p['elev'] == e), None)
            if fr is None or e not in twin:
                x.append(None)
                continue
            rows = []
            for i in range(len(ts)):
                a, b = along_at(fr, base[e][i][0]), along_at(twin[e], base[e][i][0])
                rows.append([a[k] - b[k] for k in range(3)] if a and b and i else None)
            rows[0] = [0.0, 0.0, 0.0]  # the launch point
            # past where either flight ends, carried on straight from its last two (a gap within: across it)
            good = [i for i, r in enumerate(rows) if r]
            for i in range(len(rows)):
                if rows[i] is None:
                    j0, j1 = next(((g0, g1) for g0, g1 in zip(good, good[1:]) if g1 > i), (good[-2], good[-1]))
                    rows[i] = [rows[j0][k] + (rows[j1][k] - rows[j0][k]) * (i - j0) / (j1 - j0) for k in range(3)]
            x.append([[round(rows[i][0], 4), round(rows[i][1], 2), round(rows[i][2], 2)] for i in ks])
        out.append({'from': WIND_SIDE.get(wf, str(wf)), 'speed': ws, 'by': 'distance', 'n': len(ts), 'step': WIND_STEP, 'x': x})
    return out


WIND_STEP = 2  # frames between the stored wind samples (0.1 s for rockets; the site interpolates between them)


def expand_wind(R, run):
    """A stored wind run (wind_runs) as per-elevation tables, every frame: d[elevation][frame] = [dt, up, side] (by
    distance) or [along, up, side] (by time), None for an elevation the run didn't fly. shot-core.js does the same as
    rockets.json loads (rocketPrep)."""
    if 'd' in run:
        return run['d']
    n, step = run['n'], run['step']
    ks = sorted(set(list(range(0, n, step)) + [n - 1]))

    def lerp(vals, k, c):
        j = min(k // step, len(ks) - 2)
        k0, k1 = ks[j], ks[j + 1]
        f = (k - k0) / ((k1 - k0) or 1)
        return vals[j][c] + (vals[j + 1][c] - vals[j][c]) * f
    return [None if xs is None else [[lerp(xs, k, c) for c in range(3)] for k in range(n)] for xs in run['x']]


def flight(R, e):
    """The calm flight (along, up per DT) at elevation e (deg), between the two test elevations around it. Interpolated
    in each flight's own launch frame (distance along the launch line, drop below it), which changes far less with
    elevation than height does, then turned back to elevation e. Past the end elevations the end flight is turned (closer
    to the game than carrying the interpolation on). (The site's rocket calculator does the same.)"""
    el = R['elevs']
    i = max(0, min(len(el) - 2, next((k for k in range(len(el) - 1) if e <= el[k + 1]), len(el) - 2)))
    f = min(max((e - el[i]) / (el[i + 1] - el[i]), 0), 1)

    def frame(pts, a):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        return [(x * c + y * s, x * s - y * c) for x, y in pts]

    A, B = frame(R['calm'][i], el[i]), frame(R['calm'][i + 1], el[i + 1])
    c, s = math.cos(math.radians(e)), math.sin(math.radians(e))
    out = []
    for p, q in zip(A, B):
        u, d = p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
        out.append((u * c + d * s, u * s - d * c))
    return out


def height_at(R, e, D):
    """Height (m) of a calm flight fired at elevation e (deg) when it is D m out, or None if it never gets there."""
    el = R['elevs']
    i = max(0, min(len(el) - 2, next((k for k in range(len(el) - 1) if e <= el[k + 1]), len(el) - 2)))
    pts = flight(R, e)
    for p, q in zip(pts, pts[1:]):
        if p[0] <= D <= q[0]:
            return p[1] + (q[1] - p[1]) * (D - p[0]) / (q[0] - p[0])
    return None


def zero(R, D, H=0.0):
    """The elevation (deg) that puts a calm flight through (D, H), by bisection; None if out of reach."""
    lo, hi = R['elevs'][0], R['elevs'][-1]
    hl, hh = height_at(R, lo, D), height_at(R, hi, D)
    if hl is None or hh is None or not hl <= H <= hh:
        return None
    for _ in range(50):
        m = (lo + hi) / 2
        hm = height_at(R, m, D)
        if hm is None:
            return None
        lo, hi = (m, hi) if hm < H else (lo, m)
    return (lo + hi) / 2


# --- The site's rocket calculator (static/shot-core.js), copied: check and launchertest fire its answers ----------------
# Keep in step with shot-core.js: rocketPrep, rocketWind, rocketAt, rocketAim (test_sitesolver.py compares the two).
END_JUMP = {'calm': 0.8, 'wind': 0.05}


def prepare(R):
    """shot-core.js rocketPrep: trim jumping last frames, carry the flights on to the moment the rocket blows up, and
    work out reach, windReach and windLen. Changes R (call it once, on a freshly loaded rockets.json entry)."""
    if R.get('_ready'):
        return R
    for run in R.get('winds') or []:
        if 'd' not in run:
            run['d'] = expand_wind(R, run)
    # wind runs measured at the same distance ([dt, up, side]) or, in an older file, at the same time ([along, up, side])
    R['windBy'] = 'distance' if any(r.get('by') == 'distance' for r in R.get('winds') or []) else 'time'

    def trim(tables):
        n = len(tables[0][0])
        for k in range(max(2, int(n * 0.9)), n):
            if any(abs(a[k][i] - 2 * a[k - 1][i] + a[k - 2][i]) > lim for a, cols, lim in tables for i in cols):
                for a, _, _ in tables:
                    del a[k:]
                return
    if R.get('winds'):
        wtabs = [(a, (0, 1, 2), END_JUMP['wind'] * r['speed']) for r in R['winds'] for a in r['d'] if a]
    else:
        wtabs = [(R['head'], (0, 1), END_JUMP['wind']), (R['tail'], (0, 1), END_JUMP['wind']), (R['cross'], (2,), END_JUMP['wind'])]
    trim([(c, (0, 1), END_JUMP['calm']) for c in R['calm']])
    trim(wtabs)
    end = math.ceil(R['life'] / R['dt'] + 1e-9) + 1
    g = 9.81 * R['dt'] * R['dt']
    with_it = len(R['calm'][0]) - len(wtabs[0][0]) <= 3
    while len(R['calm'][0]) < end:
        for c in R['calm']:
            a, b = c[-1], c[-2]
            c.append([2 * a[0] - b[0], 2 * a[1] - b[1] - g])
    while with_it and len(wtabs[0][0]) < end:
        for t, _, _ in wtabs:
            a, b = t[-1], t[-2]
            t.append([2 * v - b[i] for i, v in enumerate(a)])
    R['windLen'] = min(len(t) for t, _, _ in wtabs)

    def along(c, t):
        x = t / R['dt']
        k = min(int(math.floor(x)), len(c) - 2)
        f = x - k
        return c[k][0] + (c[k + 1][0] - c[k][0]) * f
    R['reach'] = max(along(c, R['life']) for c in R['calm'])
    R['windReach'] = max(along(c, min(R['life'], (R['windLen'] - 1) * R['dt'])) for c in R['calm'])
    R['_ready'] = True
    return R


def wind_offset(R, e, w):
    """shot-core.js rocketWind: [along, up, side] per frame for wind w = (along m/s, + = tailwind; m/s from the right),
    blended between the winds and elevations flown (rockets.json format 2)."""
    along_w, right = w
    el = R['elevs']
    i = next((k for k in range(len(el) - 1) if e <= el[k + 1]), len(el) - 2)
    f = min(max((e - el[i]) / (el[i + 1] - el[i]), 0), 1)
    n = R['windLen']

    def at_elev(run):
        a = run['d'][i] or run['d'][i + 1]
        b = run['d'][i + 1] or run['d'][i]
        return lambda k: [v + (b[k][c] - v) * f for c, v in enumerate(a[k])]

    def part(frm, mirror, s):
        if not s > 0:
            return None
        runs, flip = [r for r in R['winds'] if r['from'] == frm], 1
        if not runs and mirror:
            runs, flip = [r for r in R['winds'] if r['from'] == mirror], -1
        if not runs:
            return None
        runs = sorted(runs, key=lambda r: r['speed'])
        hi = next((r for r in runs if r['speed'] >= s), None)
        lo = next((r for r in reversed(runs) if r['speed'] < s), None)
        side = lambda v: [x * flip if c == 2 else x for c, x in enumerate(v)]
        if hi is None:
            top = runs[-1]
            g, q = at_elev(top), s / top['speed']
            return lambda k: [x * q for x in side(g(k))]
        gh = at_elev(hi)
        if lo is None:
            q = s / hi['speed']
            return lambda k: [x * q for x in side(gh(k))]
        gl, q = at_elev(lo), (s - lo['speed']) / (hi['speed'] - lo['speed'])
        return lambda k: side([v + (gh(k)[c] - v) * q for c, v in enumerate(gl(k))])
    cross = part('right', 'left', right) if right >= 0 else part('left', 'right', -right)
    along = part('tail', None, along_w) if along_w >= 0 else part('head', None, -along_w)
    out = []
    for k in range(n):
        a = cross(k) if cross else [0, 0, 0]
        b = along(k) if along else [0, 0, 0]
        out.append([a[0] + b[0], a[1] + b[1], a[2] + b[2]])
    return out


# Bullets (bullets.json, R['bullet'] set): shot-core.js flies their wind from their drag, fitted to their still-air
# flight (the wind runs, before rockettest.flight_time, were timed by the recordings' stamps and so useless for this).
G = 9.81


def fly_drag(k, v0, e, W, dt, n, sub):
    """shot-core.js flyDrag: positions [along, up, side] every dt for drag k (per m, times airspeed squared), launch speed
    v0, elevation e (deg), air moving at W; midpoint steps, `sub` per sample."""
    h = dt / sub
    out = [[0.0, 0.0, 0.0]]
    x = y = z = 0.0
    vx, vy, vz = v0 * math.cos(math.radians(e)), v0 * math.sin(math.radians(e)), 0.0

    def acc(ax, ay, az):
        ux, uy, uz = ax - W[0], ay - W[1], az - W[2]
        u = math.sqrt(ux * ux + uy * uy + uz * uz)
        return -k * u * ux, -k * u * uy - G, -k * u * uz
    for _ in range(1, n):
        for _ in range(sub):
            a1 = acc(vx, vy, vz)
            mx, my, mz = vx + a1[0] * h / 2, vy + a1[1] * h / 2, vz + a1[2] * h / 2
            a2 = acc(mx, my, mz)
            x += mx * h
            y += my * h
            z += mz * h
            vx += a2[0] * h
            vy += a2[1] * h
            vz += a2[2] * h
        out.append([x, y, z])
    return out


def bullet_drag(R):
    """shot-core.js bulletDrag: the drag that best fits the still-air flight at the elevation nearest level."""
    if 'drag' in R:
        return R['drag']
    i0 = min(range(len(R['elevs'])), key=lambda i: (abs(R['elevs'][i]), i))
    meas = R['calm'][i0]
    n = len(meas)

    def err(lk):
        return sum((p[0] - m[0]) ** 2 + (p[1] - m[1]) ** 2 for p, m in zip(fly_drag(math.exp(lk), R['v0'], R['elevs'][i0], (0, 0, 0), R['dt'], n, 4), meas))
    a, b = math.log(1e-6), math.log(1e-2)
    r = (math.sqrt(5) - 1) / 2
    c, d = b - r * (b - a), a + r * (b - a)
    fc, fd = err(c), err(d)
    for _ in range(60):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - r * (b - a)
            fc = err(c)
        else:
            a, c, fc = c, d, fd
            d = a + r * (b - a)
            fd = err(d)
    R['drag'] = math.exp((a + b) / 2)
    return R['drag']


def bullet_wind(R, e, w):
    """shot-core.js bulletWind: what the wind adds to a bullet's flight at elevation e, [along, up, side] per sample."""
    along, right = w
    cache = R.setdefault('_wind', {})
    key = (round(e, 4), round(along, 3), round(right, 3))
    if key not in cache:
        k, n = bullet_drag(R), len(R['calm'][0])
        still = fly_drag(k, R['v0'], e, (0, 0, 0), R['dt'], n, 5)
        windy = fly_drag(k, R['v0'], e, (along, 0, -right), R['dt'], n, 5)
        cache[key] = [[p[i] - q[i] for i in range(3)] for p, q in zip(windy, still)]
    return cache[key]


def shot_at(R, e, w, D):
    """shot-core.js rocketAt: where a shot at elevation e is when it has come D m: (up, side, t), with wind w = (along
    m/s, + = tailwind; crosswind m/s from the right), or None if it blows up first."""
    along, right = w
    windy = bool(along or right)
    if R.get('bullet'):
        pts = flight(R, e)
        off = bullet_wind(R, e, w) if windy else None
        p = (lambda k: (pts[k][0] + off[k][0], pts[k][1] + off[k][1], off[k][2])) if windy else (lambda k: (pts[k][0], pts[k][1], 0.0))
        prev = p(0)
        for k in range(1, len(pts)):
            q = p(k)
            if q[0] >= D:
                f = (D - prev[0]) / ((q[0] - prev[0]) or 1)
                return prev[1] + (q[1] - prev[1]) * f, prev[2] + (q[2] - prev[2]) * f, (k - 1 + f) * R['dt']
            prev = q
        return None
    prepare(R)
    pts = flight(R, e)
    n = len(pts)
    # p(k): (along, up, side, extra time) at frame k
    if not windy:
        p = lambda k: (pts[k][0], pts[k][1], 0.0, 0.0)
    elif R.get('winds') and R['windBy'] == 'distance':
        # measured at the same distance: the still-air flight's distance, the wind's height, side and delay
        off = wind_offset(R, e, w)
        n = min(n, len(off))
        p = lambda k: (pts[k][0], pts[k][1] + off[k][1], off[k][2], off[k][0])
    elif R.get('winds'):
        off = wind_offset(R, e, w)
        n = min(n, len(off))
        p = lambda k: (pts[k][0] + off[k][0], pts[k][1] + off[k][1], off[k][2], 0.0)
    else:  # an older rockets.json: head and tail as measured, of the crosswind only the sideways part
        lw, ls = (R['tail'] if along >= 0 else R['head']), abs(along)
        n = min(n, R['windLen'])
        p = lambda k: (pts[k][0] + lw[k][0] * ls, pts[k][1] + lw[k][1] * ls, R['cross'][k][2] * right, 0.0)
    prev = p(0)
    for k in range(1, n):
        q = p(k)
        if q[0] >= D:
            f = (D - prev[0]) / ((q[0] - prev[0]) or 1)
            t = (k - 1 + f) * R['dt'] + prev[3] + (q[3] - prev[3]) * f
            if t > R['life']:
                return None
            return prev[1] + (q[1] - prev[1]) * f, prev[2] + (q[2] - prev[2]) * f, t
        prev = q
    return None


AIM_STEP = 0.25  # deg: shot-core.js aimStep (rockets; bullets 1)


def aim(R, D, H, w, lo_e=-15, hi_e=25):
    """shot-core.js rocketAim: (elevation deg, side drift m, flight s) for a hit D m out, H m up, or None (out of range,
    or too steep). Rockets and bullets (R['bullet'])."""
    if not R.get('bullet'):
        prepare(R)
        if D > R['reach']:
            return None
    step = 1.0 if R.get('bullet') else AIM_STEP
    lo = hi = None
    e = float(lo_e)
    while e <= hi_e:
        h = shot_at(R, e, w, D)
        if h and h[0] >= H:
            hi = e
            break
        lo = e if h else None
        e += step
    if hi is None or (lo is None and hi == lo_e):
        return None
    if lo is not None:
        for _ in range(30):
            m = (lo + hi) / 2
            h = shot_at(R, m, w, D)
            lo, hi = (lo, m) if h and h[0] >= H else (m, hi)
    up, side, t = shot_at(R, hi, w, D)
    return hi, side, t


def wind_report(T, elev=0, dists=(100, 200, 300, 400, 500)):
    """What each test wind did at level elevation, where the rocket was D m out, per m/s of wind: sideways drift (+ =
    into the wind), change in height, and delay (ms). Equal numbers down a column mean the effect grows in step with the
    wind; right and left equal mean they're mirror images."""
    print(f'\nwinds at {elev} deg, per m/s of wind, where the rocket is D m out: side (+ = into the wind) / up / delay ms')
    for name, R in T.items():
        if not R.get('winds'):
            continue
        i = R['elevs'].index(elev)
        calm = R['calm'][i]

        def at_d(run, D):
            d = expand_wind(R, run)[i]
            if d is None:
                return None
            if run.get('by') == 'distance':  # [dt, up, side] at the still-air flight's frames
                for k in range(len(calm) - 1):
                    a, b = calm[k], calm[k + 1]
                    if a[0] <= D <= b[0] and k + 1 < len(d):
                        f = (D - a[0]) / ((b[0] - a[0]) or 1)
                        return [d[k][c] + (d[k + 1][c] - d[k][c]) * f for c in (2, 1, 0)]
                return None
            pts = [(c[0] + x[0], c[1] + x[1], x[2]) for c, x in zip(calm, d)]  # older: [along, up, side] at equal time
            for p, q in zip(pts, pts[1:]):
                if p[0] <= D <= q[0]:
                    f = (D - p[0]) / ((q[0] - p[0]) or 1)
                    up0 = next(((a[1] + (b[1] - a[1]) * (D - a[0]) / ((b[0] - a[0]) or 1)) for a, b in zip(calm, calm[1:]) if a[0] <= D <= b[0]), None)
                    return [p[2] + (q[2] - p[2]) * f, (p[1] + (q[1] - p[1]) * f) - up0 if up0 is not None else 0, 0]
            return None
        print(f'  {name}' + ''.join(f'{D:>19d} m' for D in dists))
        for run in sorted(R['winds'], key=lambda r: (r['from'], r['speed'])):
            cells = []
            for D in dists:
                v = at_d(run, D)
                if v is None:
                    cells.append(f"{'-':>21s}")
                    continue
                s = run['speed']
                into = v[0] / s * (-1 if run['from'] == 'left' else 1)
                cells.append(f'{into:+7.3f}/{v[1] / s:+6.3f}/{v[2] / s * 1000:+5.1f}')
            print(f"    {run['from']:5s} {run['speed']:>4} m/s" + ''.join(cells))


def report(F):
    from rockettest import ELEVS
    T = tables(F, ELEVS, winds=True)
    wind_report(T)
    for name, R in T.items():
        far = R['calm'][ELEVS.index(0)][-1][0]
        print(f"{name}: launch {R['v0']} m/s, life {R['life']} s, level reach {far:.0f} m, launch spread at 2 s +-{R['spread']} m")
        for D in (100, 200, 300, 400, 500, 600, 700):
            z = zero(R, D)
            if z is not None:
                print(f"   {D} m: elevation {z:.2f} deg")
    print('\nsights (the angle each mark gives, against the angle the rocket needs at that range, level ground)')
    for lname, s in SIGHTS.items():
        for rk in s['rockets']:
            R = T[rk]
            marks = ', '.join(f"{r}: {a + s['spawn']:.2f} vs {zero(R, r):.2f}" if zero(R, r) is not None else f'{r}: -'
                              for r, a in s['iron'].items())
            print(f'  {lname} iron, {rk}: {marks}')
    for rk, rows in PGO7_ROWS.items():
        marks = ', '.join(f"{r}: {(y - PGO7_CROSS) / PGO7_PX_DEG:.2f} vs {zero(T[rk], r):.2f}" for r, y in rows.items())
        print(f'  PGO-7, {rk}: {marks}')
    return T


def site_json(T):
    """What the field map reads (static/data/rockets.json)."""
    launchers = {}
    for lname, s in SIGHTS.items():
        sights = {'iron': {str(r): round(a, 3) for r, a in s['iron'].items()}}
        if lname == 'RPG-7':
            sights['pgo7'] = {rk: {str(r): round((y - PGO7_CROSS) / PGO7_PX_DEG, 3) for r, y in rows.items()}
                              for rk, rows in PGO7_ROWS.items()}
        launchers[lname] = {'rockets': s['rockets'], 'spawn': s['spawn'], 'sights': sights}
    return {'about': 'Measured in the game by reforger-map-tools rockettest.py; see its rocketfit.py',
            'pgo7_lead_deg': PGO7_LEAD, 'launchers': launchers, 'rockets': T}
