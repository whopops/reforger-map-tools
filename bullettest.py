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
"""
import argparse, json, os, sys

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


def plan():
    rows = rockettest.make_plan(BULLETS, repeats=CALM_REPEATS)
    for r in rows:
        r['y'] = HEIGHT
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('plan', 'run', 'score'))
    ap.add_argument('folder', nargs='?')
    args = ap.parse_args()
    if args.cmd == 'plan':
        for i, rows in enumerate(rockettest.blocks(plan())):
            rockettest.write_plan(rows, i, OUT_REL)
    elif args.cmd == 'run':
        rockettest.run(plan(), OUT_REL, args=ARGS)
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
