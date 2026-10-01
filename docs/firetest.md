# Mortar tools: `firetest.py` and the `ballistics` job

Two tools check the field map's mortar calculator against the engine itself. They produce the data in
`everon-data/mortar/`.

| Tool | Runs in | What it gives you |
|---|---|---|
| `firetest.py` (with `RMT_FireTest.c`) | the game | Real shells fired and where they landed, scored against the site's firing solution |
| `ballistics` job (`RMT_BallisticsJob.c`) | Workbench | The engine's own predicted shell flight for a grid of aims (a reference table, nothing is fired) |

---

## `firetest.py`: live mortar firing test

```bash
python firetest.py plan                 # write the plan into the game profile (nothing runs)
python firetest.py run                  # plan, then run the game and fire it all; about 25 minutes
python firetest.py score [folder]       # report on the last run, or on a copy of one
        --site <path>                   # the field map's static/data folder
```

### Requirements
- Steam running and the game **closed**; Python with the standard library only (no numpy needed).
- The field map checked out, because the test uses the site's own firing tables and terrain. The default is
  `~/Documents/GitHub/arma-map/everon-map/static/data`; `--site` changes it. It reads
  `mortar-tables.json` and `maps/everon/los/` (the baked `index.json` and tiles) from there.
- **Everon only.** The world is fixed in the script (`worlds/Eden/Eden.ent`) and aims are chosen between 1,000 and
  11,800 m. The test is about the physics, so one map is enough.

### What it does
1. **Plan.** `firetest.py` carries a line-for-line Python copy of the site's firing solution (`solve`, `flight`,
   `highAngleFor`, `windParts`, `spreadOf`, `groundFine` from `static/app.js`) and the same 1 m terrain. It picks
   aims for both mortars (`M252` with `HE M821`, `2B14` with `HE O-832DU`) over open ground with a fixed random seed
   (so the plan is repeatable) and writes `plan.csv` and `plan.json` into
   `<game profile>\rmt\firetest\firetest\`. Aims come in five groups, named by the first letter of the id:

   | Group | What | Rounds per aim |
   |---|---|---|
   | `H` | target well below, level, and well above the mortar (5 height bands), no wind | 6 |
   | `T` | big drops, big climbs and level; every frame of each round's flight is recorded in `traj.csv` | 3 |
   | `W` | 8 m/s wind from three directions, solved with the wind | 6 |
   | `P` | the wind probe: one aim fired with no wind, then 10 m/s from four sides, with no wind correction | 6 |
   | `S` | spread groups at short, middle and long range, no wind | 20 |

2. **Run.** `run` writes the plan, starts the real game on Everon with `-rmtFire 1` (`RMT_GameHook` spawns
   `RMT_FireTestEntity`) and waits up to an hour. The entity spawns each shell prefab 1.3 m above the ground at the
   mortar (where the M252's muzzle is), points it, launches it through `ProjectileMoveComponent.Launch` (the way
   BI's Game Master artillery module does), and follows it until it lands. Wind is set with the weather manager's
   overrides and given time to settle (`-rmtFireSettle`, default 60 s) before firing; the plan is sorted so the wind
   only changes while no shell is in the air. It writes `shots.csv`, `traj.csv`, then `firetest.status.json`, and
   closes the game.
3. **Score.** Compares what happened with the site's model, in four parts:
   1. *Physics:* every round flown by the site's model from its real launch velocity to the height it landed at,
      against where it landed. Randomness is taken out, so this tests the equations alone. Rounds off by more than
      10 m are reported (they hit something on the way).
   2. *Aims:* where each aim's rounds centred against the target, as fired and with each round's own speed error
      taken out. The game gives each round a random launch speed (about 1.07 m/s standard deviation) that drifts
      with time, so 6 rounds are noisy.
   3. *Spread groups:* the long/short spread against the site's prediction for the speed part. A direct launch does
      not use the mortar's barrel, so the barrel's sideways spread is not tested.
   4. *Wind probe:* how far the game's wind pushes the same aim from each side.
   It also reports the terrain agreement (site ground height against the game's at every mortar and target).

Keep `SHELLS`, `MUZZLE_H`, `SPEED_SD`, `BARREL` and `P90` at the top of `firetest.py` in step with `app.js`.

### Output (`<game profile>\rmt\firetest\firetest\`)
- `plan.csv`: `id,prefab,coef,x,z,az,elev,wspeed,wdir,count,tx,tz`
- `plan.json`: the same plus what the site's solver gave (weapon, shell, ring, distance, height difference, map
  azimuth, wind-from, time of flight, predicted spread, probe flag).
- `shots.csv`: `id,round,x0,y0,z0,x,y,z,tof,ground_mortar,ground_target,wind_speed,wind_dir,v0x,v0y,v0z`
- `traj.csv` (`T` aims only): `id,round,t,x,y,z,vx,vy,vz`
- `..\firetest.status.json`

Wind directions: the game's override takes the direction the wind blows **toward**; the in-game map shows that plus
180 degrees, as "from". The plan stores `wind_from` (what a crew types into the site) and converts.

---

## The `ballistics` job

The engine's own mortar shell flight, from `ProjectileMoveComponent.GetProjectileSimulationResult`, the call BI's
wind-table generator uses. No shell is fired and nothing in the world is used (a world is still loaded because the
plugin needs one). Use it as a reference to test other ballistics against.

**What it covers.** Every mortar shell (81 mm HE M821, practice M879, smoke M819, illum M853A1; 82 mm HE O-832DU,
smoke D832DU, illum S832S), every charge ring, elevations 40 to 88 degrees in 1 degree steps, nine target heights
(-200 to 200 m relative to the mortar) and four winds (none, and 10 m/s cross, head, tail).

**Output:** `ballistics/sim.csv`, columns `shell,ring,coef,v0,angle,dh,wind,x,y,z`: `x` right, `y` up, `z` downrange,
where the shell ended. When it never climbs to the target height, `y` ends below it. The log also prints each
muzzle's dispersion settings (`DispersionDiameter`, `DispersionRange`) for the two mortars and an M16A2 as a check.

**How to run it.** `rmt.py export` does not list this job (it is not in `ALL_JOBS` in `rmtlib/export.py`), so call
the runner directly. This is a single real Workbench launch, so close Workbench first:

```bash
python -c "from rmtlib.steam import Install; from rmtlib.workbench import Runner; print(Runner(Install(None)).run('ballistics', 'rmt/ballistics', '{A9806AF617972E97}worlds/Arland/Arland.ent'))"
```
The result lands in `<Workbench profile>\rmt\ballistics\ballistics\sim.csv`. (This exact line has not been run for
this document; `Runner.run` takes any job name the plugin accepts. To make `rmt.py export --jobs ballistics` work,
add `"ballistics"` to `ALL_JOBS` in `rmtlib/export.py`.)
