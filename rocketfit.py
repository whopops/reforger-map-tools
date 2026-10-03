"""How the game's rockets fly, from rockettest.py's flights: flight tables and wind tables for the field map's rocket
calculator (rockets.json), and a report on how well the launchers' own sights fit the rockets.

The engine's rocket physics (MissileMoveComponent) are native and not in the files, so the site doesn't model them: it
reads these measured flights. For each rocket:
  calm   the flight in still air at each test elevation (ELEVS), every DT seconds: distance along the ground and height
         above the launch point, averaged over the repeats. The site interpolates between elevations.
  wind   what wind adds to a flight, per 1 m/s, every DT seconds, averaged over the elevations (it hardly depends on
         them): head (wind from the front), tail (from behind), cross (from the right; side + = to the right). Along,
         up and side, in m. Linear in wind speed (5 and 10 m/s crosswinds agree), so the site scales them.
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


def tables(F, elevs, dt=DT):
    out = {}
    for name in dict.fromkeys(p['rocket'] for p, _ in F):
        mine = [(p, fr) for p, fr in F if p['rocket'] == name]
        calm = [(p, fr) for p, fr in mine if p['wspeed'] == 0]
        life = min(fr[-1][0] for _, fr in calm)
        n = int(life / dt)
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
                     'v0': round(st.mean(speed(fr[1]) for _, fr in calm)),
                     'spread': round(st.pstdev([at(fr, 2)[1] - st.mean(at(f2, 2)[1] for p2, f2 in calm if p2['elev'] == p['elev'])
                                                for p, fr in calm if at(fr, 2)]), 1)}
    return out


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


def shot_at(R, e, w, D):
    """Where a shot at elevation e is when it has come D m: (up, side, t), with wind w = (along m/s, + = tailwind;
    crosswind m/s from the right), or None if it blows up first. A copy of the site's rocketAt (static/app.js)."""
    along, right = w
    pts = flight(R, e)
    lw, ls = (R['tail'] if along >= 0 else R['head']), abs(along)

    def p(k):
        return (pts[k][0] + lw[k][0] * ls + R['cross'][k][0] * right, pts[k][1] + lw[k][1] * ls + R['cross'][k][1] * right,
                R['cross'][k][2] * right)
    prev = p(0)
    for k in range(1, len(pts)):
        q = p(k)
        if q[0] >= D:
            f = (D - prev[0]) / ((q[0] - prev[0]) or 1)
            return prev[1] + (q[1] - prev[1]) * f, prev[2] + (q[2] - prev[2]) * f, (k - 1 + f) * R['dt']
        prev = q
    return None


def aim(R, D, H, w, lo_e=-15, hi_e=25):
    """The site's rocketAim: (elevation deg, side drift m, flight s) for a hit D m out, H m up, or None."""
    lo = hi = None
    for e in range(lo_e, hi_e + 1):
        h = shot_at(R, e, w, D)
        if h and h[0] >= H:
            hi = e
            break
        lo = e if h else None
    if hi is None or lo is None:
        return None
    lo, hi = float(lo), float(hi)
    for _ in range(30):
        m = (lo + hi) / 2
        h = shot_at(R, m, w, D)
        lo, hi = (lo, m) if h and h[0] >= H else (m, hi)
    up, side, t = shot_at(R, hi, w, D)
    return hi, side, t


def report(F):
    from rockettest import ELEVS
    T = tables(F, ELEVS)
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
