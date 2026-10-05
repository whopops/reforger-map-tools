"""Live bullet flight test for the Arma Reforger Maps field map (github.com/whopops/arma-map).

How the rounds of the game's scoped rifles, machine guns and vehicle guns fly, wind included, so the field map can tell
a gunner which zeroing or range line to use, how far to hold and where to aim (its sight calculator). Bullets use the
same ShellMoveComponent as mortar shells, but the drag the site's mortar model uses (AirDrag / Mass, times speed
squared) doesn't hold for them: the engine's own AI tables (Configs/Weapons/AIBallisticTables) show a bullet losing speed
faster early on and slower later than that, as if drag changes with speed. So, as for rockets, the rounds are flown in
the game and the site reads the measured flights.

Each round is launched directly (RMT_FireTest, -rmtFire) at its weapon's speed (the ammo's InitSpeed times the weapon's
BulletInitSpeedCoef), 1500 m above open sea on Everon so even a shot 12 degrees down flies its full 10 s, at the same
elevations and winds as rockettest.py, every 0.02 s of flight recorded.

  python bullettest.py plan               write the plans (one per wind) into the game profile
  python bullettest.py run                plan, then one game run per wind; ~25 min. Rerun to finish a broken run
  python bullettest.py score [folder]     tables -> out/bullets.json (the site's static/data/bullets.json)
  python bullettest.py check              random shots solved the site's way from out/bullets.json, fired in the game
                                          (one run per wind, ~30 min); how far each passed from its target
  python bullettest.py check-score [dir]  that report again
  python bullettest.py check-twins        the check's shots again in still air (~30 min): the wind's part of each miss
  python bullettest.py check-twins-score [dir]  that report again

The site flies a round's wind from its drag (fitted to its still-air flight), not from the wind runs here; `check`
fires its answers in random winds to show how close that comes.
"""
import argparse, json, math, os, random, sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
import rockettest, rocketfit

OUT_REL = 'rmt/bullettest'
A = 'Prefabs/Weapons/Ammo/'
# round name -> (ammo prefab, the weapon's launch speed coefficient). Named by round and weapon where the barrel differs.
BULLETS = {
    '7N1 (SVD)': (A + 'Ammo_762x54r_Ball_7N1.et', 1),
    '57N323S (PKM, UK59)': (A + 'Ammo_762x54r_Ball_57N323S.et', 1),
    '57N323S (PKT)': (A + 'Ammo_762x54r_Ball_57N323S.et', 1.036),
    'M118 (M21)': (A + 'Ammo_762x51_Ball_M118.et', 1),
    'M80 (M240)': (A + 'Ammo_762x51_Ball_M80.et', 1),
    'M855 (M16A2)': (A + 'Ammo_556x45_Ball_M855.et', 1),
    'M855 (M16A2 carbine)': (A + 'Ammo_556x45_Ball_M855.et', 0.93),
    '7N6 (AK-74)': (A + 'Ammo_545x39_Ball_7N6.et', 1),
    '7N6 (AKS-74U)': (A + 'Ammo_545x39_Ball_7N6.et', 0.835),
    '7N6 (RPK-74)': (A + 'Ammo_545x39_Ball_7N6.et', 1.06),
    'B32 (NSV)': (A + 'Ammo_127x108_API_B32.et', 1),
    'BZ (KPVT)': (A + 'Ammo_145x114_API_57BZ561S.et', 1),
    'M792 HEI-T (M242)': (A + 'Ammo_25x137/Ammo_25x137_HEIT_M792.et', 1),
    'M791 APDS-T (M242)': (A + 'Ammo_25x137/Ammo_25x137_APDST_M791.et', 1),
}
HEIGHT = 1500
CALM_REPEATS = 2
ARGS = ('-rmtFireGap=0.3', '-rmtFireTraceDt=0.02', '-rmtFireMaxT=10')
DT = 0.1  # the tables' time step: a bullet's path is smooth enough to interpolate between


WINDS = rockettest.WINDS[:5]  # still air, 10 and 5 m/s from the right, head and tail (the bullets' wind is flown by the
                              # site from their drag, and checked with `check`; these runs show the drift it matches)


def plan():
    rows = rockettest.make_plan(BULLETS, winds=WINDS, repeats=CALM_REPEATS)
    for r in rows:
        r['y'] = HEIGHT
    return rows


# --- check: the site's own answers, fired in the game -------------------------------------------------------------
CHECK_REL = 'rmt/bullettest-check'
CHECK_TWIN_REL = 'rmt/bullettest-check-twins'
CHECK_WINDS = 8      # random winds (2 to 20 m/s, from anywhere), each its own game run
CHECK_SHOTS = 2      # shots per round per wind
CHECK_FAR = {'7N1 (SVD)': 1000, '57N323S (PKM, UK59)': 1000, '57N323S (PKT)': 1500, 'M118 (M21)': 900, 'B32 (NSV)': 1500,
             'BZ (KPVT)': 1500, 'M792 HEI-T (M242)': 1500, 'M791 APDS-T (M242)': 2000}  # furthest shot per round (default 800)


def check_plan(seed=13):
    """Random shots (distance, height difference, wind) solved the site's way from bullets.json (rocketfit.aim: the
    round's drag fitted to its still-air flight, the wind flown from it), to fire in the game: elevation and aim-off
    bearing as the site gives them. The round flies north; the target is D m north, H m up."""
    from blasttest import prefab_name
    import rocketfit
    J = json.load(open(os.path.join(REPO, 'out', 'bullets.json')))
    rnd = random.Random(seed)
    rows = []
    for _ in range(CHECK_WINDS):
        ws, wf = round(rnd.uniform(2, 20) * 2) / 2, rnd.randrange(360)
        w = (-ws * math.cos(math.radians(wf)), ws * math.sin(math.radians(wf)))  # tailwind +, crosswind from the right
        for name, (path, coef) in BULLETS.items():
            R = dict(J['rounds'][name], bullet=True)
            n = 0
            while n < CHECK_SHOTS:
                D, H = rnd.uniform(100, CHECK_FAR.get(name, 800)), rnd.uniform(-40, 40)
                s = rocketfit.aim(R, D, H, w)
                if not s:
                    continue
                e, side, t = s
                rows.append({'id': f'T{len(rows):03d}', 'rocket': name, 'prefab': prefab_name(path), 'coef': coef, 'elev': e,
                             'az': -math.degrees(math.atan2(side, D)), 'wspeed': ws, 'wfrom': wf, 'D': D, 'H': H, 'tof': t, 'y': HEIGHT})
                n += 1
    for r, (x, z) in zip(rows, rockettest.sea_spots(len(rows), seed=seed)):
        r['x'], r['z'] = x, z
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('plan', 'run', 'score', 'check', 'check-score', 'check-twins', 'check-twins-score'))
    ap.add_argument('folder', nargs='?')
    args = ap.parse_args()
    if args.cmd == 'plan':
        for i, rows in enumerate(rockettest.blocks(plan())):
            rockettest.write_plan(rows, i, OUT_REL)
    elif args.cmd == 'run':
        rockettest.run(plan(), OUT_REL, args=ARGS)
    elif args.cmd == 'check':
        rockettest.run(check_plan(), CHECK_REL, args=ARGS)
        rockettest.check_score(rockettest.game_dir(rel=CHECK_REL))
    elif args.cmd == 'check-score':
        rockettest.check_score(args.folder or rockettest.game_dir(rel=CHECK_REL))
    elif args.cmd in ('check-twins', 'check-twins-score'):
        if args.cmd == 'check-twins':
            rockettest.run(rockettest.check_twin_rows(CHECK_REL), CHECK_TWIN_REL, args=ARGS)
        rockettest.check_twins_score(rockettest.game_dir(rel=CHECK_REL), args.folder or rockettest.game_dir(rel=CHECK_TWIN_REL),
                                     os.path.join(REPO, 'out', 'bullets.json'), bullet=True)
    else:
        F = rockettest.flights(args.folder or rockettest.game_dir(rel=OUT_REL))
        T = rocketfit.tables(F, rockettest.ELEVS, dt=DT)
        for name, R in T.items():
            far = R['calm'][rockettest.ELEVS.index(0)][-1][0]
            print(f"{name:22s} launch {R['v0']} m/s, flown {R['life']} s, level {far:.0f} m, launch spread at 2 s +-{R['spread']} m")
        out = os.path.join(REPO, 'out', 'bullets.json')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump({'about': 'Measured in the game by reforger-map-tools bullettest.py', 'rounds': T}, open(out, 'w'), separators=(',', ':'))
        print(f'-> {out} ({os.path.getsize(out) // 1024} KB): copy to arma-map everon-map/static/data/bullets.json')
