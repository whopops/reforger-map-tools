"""rocketfit.py's copy of the field map's shot calculator against the real one (static/shot-core.js, run in Node).

rockettest.py check, bullettest.py check and launchertest.py fire the site's answers, worked out by rocketfit.aim; this
makes sure that is what the site would say. Random shots solved by both: every rocket (30 m to past its range, 60 m
below to 40 m above, winds of 0 to 25 m/s from every side) and every gun's round (50 to 1200 m); elevation, side
drift and flight time must agree, and both must call the same shots out of range.

  python test_sitesolver.py [--site <field map folder>] [--rockets <rockets.json>] [--bullets <bullets.json>] [--shots N]

--site: the folder holding server.py (default: $RMT_SITE, else ../arma-map/everon-map next to this repo's parent);
--rockets and --bullets: default the site's own static/data files. Needs Node.js. Skipped (exit 0) when Node or the
site isn't there. Under `python -m unittest` (the GUI's Self-test) it runs only with RMT_SITE set, since the copy has to
match the site it is compared with: a site older than this copy fails.
"""
import argparse, copy, json, math, os, random, shutil, subprocess, sys, tempfile, unittest

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
import rocketfit

NODE_SOLVE = r"""
const fs = require('fs'), vm = require('vm');
const [core, rockets, bullets, cases] = process.argv.slice(2).map(f => fs.readFileSync(f, 'utf8'));
const ctx = vm.createContext({ window: {}, Math });
vm.runInContext(core, ctx);
const SC = ctx.window.ShotCore({ ground: () => 0, hasGround: () => true, windParts: () => ({ along: 0, across: 0 }),
  fmtDist: m => `${m} m`, dist: () => 0, bearing: () => 0 });
SC.setRockets(JSON.parse(rockets));
SC.setBullets(JSON.parse(bullets));
const out = JSON.parse(cases).map(c => {
  const R = c.bullet ? SC.bullets.rounds[c.rocket] : SC.rockets.rockets[c.rocket];
  const s = SC.rocketAim(R, c.D, c.H, { along: c.along, fromRight: c.right });
  return s.err ? null : [s.e, s.side, s.t];
});
process.stdout.write(JSON.stringify(out));
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--site', default=os.environ.get('RMT_SITE') or os.path.join(os.path.dirname(os.path.dirname(REPO)), 'arma-map', 'everon-map'))
    ap.add_argument('--rockets')
    ap.add_argument('--bullets')
    ap.add_argument('--shots', type=int, default=600)
    a = ap.parse_args(argv)
    core = os.path.join(a.site, 'static', 'shot-core.js')
    rockets = a.rockets or os.path.join(a.site, 'static', 'data', 'rockets.json')
    bullets = a.bullets or os.path.join(a.site, 'static', 'data', 'bullets.json')
    node = shutil.which('node')
    if not (node and os.path.exists(core) and os.path.exists(rockets) and os.path.exists(bullets)):
        print(f'skipped: needs node and {core}, {rockets} and {bullets}')
        return 0
    J, B = json.load(open(rockets)), json.load(open(bullets))
    rnd = random.Random(5)
    cases = []
    for _ in range(a.shots):
        name = rnd.choice(list(J['rockets']))
        reach = rocketfit.prepare(copy.deepcopy(J['rockets'][name]))['reach']
        ws, wf = rnd.choice([0, rnd.uniform(0, 25)]), rnd.uniform(0, 360)
        cases.append({'rocket': name, 'D': rnd.uniform(30, reach * 1.05), 'H': rnd.uniform(-60, 40),
                      'along': -ws * math.cos(math.radians(wf)), 'right': ws * math.sin(math.radians(wf))})
    for _ in range(a.shots // 5):
        ws, wf = rnd.choice([0, rnd.uniform(0, 25)]), rnd.uniform(0, 360)
        cases.append({'rocket': rnd.choice(list(B['rounds'])), 'bullet': True, 'D': rnd.uniform(50, 1200), 'H': rnd.uniform(-60, 40),
                      'along': -ws * math.cos(math.radians(wf)), 'right': ws * math.sin(math.radians(wf))})
    with tempfile.TemporaryDirectory() as d:
        js, cf = os.path.join(d, 'solve.cjs'), os.path.join(d, 'cases.json')
        open(js, 'w').write(NODE_SOLVE)
        json.dump(cases, open(cf, 'w'))
        site = json.loads(subprocess.run([node, js, core, rockets, bullets, cf], capture_output=True, text=True, check=True).stdout)
    Rs = {n: rocketfit.prepare(copy.deepcopy(R)) for n, R in J['rockets'].items()}
    Bs = {n: dict(copy.deepcopy(R), bullet=True) for n, R in B['rounds'].items()}
    bad = solved = 0
    for c, s in zip(cases, site):
        R = Bs[c['rocket']] if c.get('bullet') else Rs[c['rocket']]
        p = rocketfit.aim(R, c['D'], c['H'], (c['along'], c['right']))
        # the same answer: 0.0001 deg (about a millimetre at 700 m), a millimetre aside, 0.1 ms (the two languages
        # round the blending's sums differently, which moves the last halvings of the elevation search)
        if (p is None) != (s is None) or (p and (abs(p[0] - s[0]) > 1e-4 or abs(p[1] - s[1]) > 1e-3 or abs(p[2] - s[2]) > 1e-4)):
            bad += 1
            if bad <= 10:
                print(f"  differs: {c['rocket']} {c['D']:.0f} m, {c['H']:+.0f} m, wind {c['along']:+.1f}/{c['right']:+.1f}: site {s} copy {p}")
        solved += s is not None
    print(f'{len(cases)} shots ({solved} in range): {bad} differ')
    return 1 if bad else 0


@unittest.skipUnless(os.environ.get('RMT_SITE'), 'set RMT_SITE to the field map folder to compare with its calculator')
class SiteSolver(unittest.TestCase):
    def test_copy_matches_site(self):
        self.assertEqual(main(['--shots', '300']), 0)


if __name__ == '__main__':
    sys.exit(main())
