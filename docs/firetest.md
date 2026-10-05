# Mortar and rocket tools: `firetest.py`, `blasttest.py`, `rockettest.py` and the `ballistics` job

These tools check the field map's mortar and rocket calculators against the engine itself. They produce the data in
`everon-data/mortar/` and `everon-data/rockets/`.

| Tool | Runs in | What it gives you |
|---|---|---|
| `firetest.py` (with `RMT_FireTest.c`) | the game | Real shells fired and where they landed, scored against the site's firing solution |
| `blasttest.py` (with `RMT_BlastTest.c`) | the game | Real shells dropped among soldiers: who goes down or is hurt at each distance (the site's kill and danger zones) |
| `rockettest.py` (with `RMT_FireTest.c`) and `rocketfit.py` | the game | The game's shoulder-fired rockets flown in still air and wind, every frame recorded: the site's rocket calculator (`rockets.json`) |
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
   `<game profile>\rmt\firetest\firetest\`. The solver's flattest elevation is `MIN_ELEV`, 45 degrees (the tube's
   `LimitsVert 45 85`, from `Mortar_Base.et`); aims shorter than the firing table's shortest distance are skipped, and
   the longest reach comes from the model rather than the table's last row. Aims come in five groups, named by the
   first letter of the id:

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
- `plan.csv`: `id,prefab,coef,x,z,az,elev,wspeed,wdir,count,tx,tz`, and optionally `y`: launch from that height
  above the sea instead of the muzzle on the ground (`rockettest.py` uses it)
- `plan.json`: the same plus what the site's solver gave (weapon, shell, ring, distance, height difference, map
  azimuth, wind-from, time of flight, predicted spread, probe flag).
- `shots.csv`: `id,round,x0,y0,z0,x,y,z,tof,ground_mortar,ground_target,wind_speed,wind_dir,v0x,v0y,v0z`
- `traj.csv` (`T` aims only): `id,round,t,x,y,z,vx,vy,vz`
- `..\firetest.status.json`

Wind directions: the game's override takes the direction the wind blows **toward**; the in-game map shows that plus
180 degrees, as "from". The plan stores `wind_from` (what a crew types into the site) and converts.

### `group` and `gun`: one aim, fired again and again

```bash
python firetest.py group [folder]       # direct launches (as above), a pause between rounds
python firetest.py gun [folder]         # through a real mortar, laid on the numbers before every round
        --distance 1200 --ring 3 --rounds 10 --gap 15
```
Both pick one M252 HE aim over level, open ground with no wind. Each round is fired with exactly the same elevation and
azimuth, with `--gap` seconds between rounds (a crew re-laying and loading), so every round gets its own launch-speed
error. Both report where each round landed, the group's centre and size, and the site's 90% ellipse for that shot.
With a folder, they only report on it.

- **`group`** launches the shell directly, like the main test. Its results go to
  `<game profile>\rmt\firetest-group\firetest\`.
- **`gun`** fires through the weapon itself, so the barrel's dispersion is in it (`RMT_GunTest.c`, flag `-rmtGun`):
  1. Places a real M252.
  2. Lays it: with no player or AI on the gun the tube stays at rest (a gunner put in the seat doesn't move it either),
     so the whole mortar is turned and tilted until the barrel reads the planned bearing and elevation to within
     about 0.05 mil. The game applies dispersion relative to the barrel, so tilting the gun changes nothing measured.
  3. Puts a shell with the planned charge ring into the barrel's storage (where a crew's drop puts it) and fires.
  4. Follows the round from the weapon's own fired callback to impact.

  It also reports how far each round left the barrel's direction (up/down and sideways, in mils), which is the
  barrel's dispersion measured directly. Output in `<game profile>\rmt\guntest\gun\`:
  - `shots.csv`: `id,round,lay_az,lay_el,lay_tries,mx,my,mz,bx,by,bz,v0x,v0y,v0z,v0dt,x,y,z,tof,ground_target`.
    `m` is the muzzle; `b` is the barrel's direction; `v0` is the round's velocity when first seen, `v0dt` s after it
    was fired.
  - `plan.csv`, `plan.json`, `..\guntest.status.json`.
  - `traj.csv`: every frame of every round followed down (`id,round,t,x,y,z,vx,vy,vz`).

  It holds the wind at nothing (and gives it 60 s to settle) before firing, as the main test does. Without that,
  Everon's own weather pushes the rounds: a first version left it out, and its rounds landed 1-2% long and up to 55 m
  sideways.

### `barrel`: the muzzle study (where the site's spread comes from)

```bash
python firetest.py barrel                       # 40 rounds on every charge ring of both mortars; about an hour
python firetest.py barrel --per-ring 2          # a quick check
python firetest.py barrel --resume <folder> --out rmt/barreltest-b   # a run that stopped: fire only what it lacks
python firetest.py barrel <folder> --also <folder>                    # report on runs (pooled)
```
How a round leaves the muzzle (its speed, and its direction against the barrel) is all its spread depends on: from
there the model flies it to within 0.25 m. So this fires through the real mortars (`RMT_GunTest.c`, as `gun` does)
and measures every round at the muzzle, then removes it. It covers every charge ring of the M252 (HE M821) and the
2B14 (HE O-832DU), 40 rounds each by default.
- Each mortar stands at its own level spot and aims at the middle of each ring's reach.
- The rings come in a fresh random order every cycle, so the game's slowly drifting launch speed falls on all of
  them alike.
- 1 round in 8 is followed down, as a check on the physics.
- A fresh gun is placed every 20 rounds (`FRESH_GUN`).

The report has five parts:
1. **Launch speed** per ring: against the shell's speed times the ring's multiplier, and per base speed.
2. **Direction off the barrel** in mils, up/down and sideways, per mortar and per ring. It's compared with the game's
   10.4 mil circle under two assumptions (evenly over its area, or evenly by distance from the middle).
3. **Physics:** the followed rounds, flown by the model from their own launch, against where they landed.
4. **The constants** this gives (`SPEED_SD`, `SPEED_BIAS`, `BARREL_SD`).
5. **The ellipse check:** the site's ellipse (`spread_of`, `P90`), against the measured rounds themselves. Each
   round's speed error and barrel throw is drawn at random and flown by the model, for every ring at short, middle and
   long range, and the report counts the share inside.

**What it found (October 2026; 400 rounds, two sessions):**
- **Physics:** the model lands rounds within a median 0.25 m of the game, worst 0.43 m.
- **Launch speed** varies 1.06 (M252) and 1.08 m/s (2B14) on the base speed, scaling with the ring (the site's
  `SPEED_SD` 1.07). It averages +0.11 / +0.17 m/s, and the direct-launch runs gave the same sign. Pooled over 1,080
  rounds that's +0.13 m/s, now `SPEED_BIAS`, so the aim lands on the target instead of up to 8 m long.
- **The barrel's throw** is not spread evenly over its 10.4 mil circle (the old model: 5.3 mil sd each way). It's
  bell-shaped and tight, and differs by mortar and axis:

  | Mortar | Up/down sd | Sideways sd | Largest seen |
  |---|---|---|---|
  | M252 | 3.09 mil | 4.19 mil | 10.5 mil |
  | 2B14 | 3.90 mil | 2.94 mil | 8.7 mil |

  These are `BARREL_SD`. It's the same at every ring.
- **Ellipse:** with these constants it held 87-90% of M252 and 91-93% of 2B14 rounds at every ring and range. Pooled,
  the size that holds 90% is 2.15 sd: the theoretical 2.146 the site uses. The per-mortar sizes (2.22 and 2.04) are
  within the noise of 200 rounds (±0.10), so the site keeps one size.

**Things to know:**
- **Overflow:** one gun fired about 140 times stopped the game with an engine assertion ("BitBuffer memory overflow",
  in `crash.log`; the run then stalls on the dialog). Turning the gun only when its lay changes, and a fresh gun every
  20 rounds, avoided it.
- **Repeating randomness:** the game's random numbers start the same way every session. The first round of every
  session left the barrel at the same direction, and later rounds differ as other things use the generator. A run
  resumed in a new session (`--resume`) can repeat a few early draws, so check before pooling. In the October runs only the
  first draw repeated (each session's first round, 1 of 400). The second session's later draws followed the same
  sequence as an earlier session's `gun` run, but none of the first session's.

---

## `blasttest.py`: live mortar blast test

What a round does to soldiers around where it lands. The field map's kill and danger zones come from this.

```bash
python blasttest.py plan                 # write the plan into the game profile (nothing runs)
python blasttest.py run                  # plan, then run the game; about 20 minutes for the default shells
python blasttest.py score [folder]       # report on the last run, or on a copy of one; writes summary.json
        --shells "HE M821,HE O-832DU"     # which shells (default: the two HE and the practice round)
        --out rmt/blasttest-smoke         # run folder under the game profile, so runs don't overwrite each other
        --trials 3                        # run: only the first few trials (a quick check that it works)
        --site <path>                     # the field map's static/data folder (for the terrain)
```

### Requirements
Steam running and the game closed, as for `firetest.py`. It uses the site's Everon terrain to find even ground.

### What it does
1. **Plan.** Finds the 12 evenest open spots on Everon. It measures how far the ground within 60 m strays from a flat
   plane, so a steady slope is fine but bumps and hollows are not. Trials take turns using them. Every trial:
   - drops one shell at 50, 65 or 80 degrees below the horizon;
   - targets 63 riflemen (the game's `Character_US_Rifleman`, no AI), all standing or all prone, three at each
     distance from 3 to 70 m, at angles turned by the golden angle so nobody stands right behind another;
   - either lets them be knocked unconscious (as most servers have it) or not.
   By default there are 4 trials of every combination, 144 in all.
2. **Run.** The game starts on `worlds/Eden/EmptyEden.ent`: Everon's terrain with nothing standing on it, so no
   tree, wall or building blocks a fragment. `RMT_BlastTestEntity` (`Scripts/Game/RMT/RMT_BlastTest.c`) then works
   through the trials:
   - stands the soldiers up (or lays them down) and gives them 4 s;
   - spawns the shell 60 m back along its path and launches it at the aim point. It must start more than 30 m away:
     the fuze only arms after `SafetyDistance 30` (`Ammo_MortarShell_Base.et`), and a shell that hits sooner is a dud;
   - waits 2 s after the burst, then records each soldier;
   - removes the soldiers and anything they dropped.
3. **Score.** For each shell, stance and unconsciousness setting:
   - the share of soldiers dead, down (dead or unconscious) and hurt (any wound or bleeding), by distance from the
     burst;
   - an S-curve fitted to that, giving the distances where 90%, 50% and 10% go down and where 50% and 10% are hurt,
     with the 50% distance also split by descent angle and by side of the burst (ahead, side, behind);
   - all of it saved to `summary.json`.

### What the game's files say
The shells' damage lives in `Prefabs/Weapons/Warheads/Warhead_Shell_*.et` and `Prefabs/Weapons/Core/Damage/`. The
engine's own help text (in the game's executable) gives the scaling:
- **Blast:** 1000 damage out to 10 m, plus 333 out to 3 m through cover, scaled by
  `(ChargeWeight x TntEquivalent) ^ ExplosionDamagePower`.
- **Fragments:** `DamageFragmentCount` fragments of 16 damage, reaching 25 m scaled by their mass and speed:
  - speed (Gurney) = `0.8 x GurneyConstant x (CaseWeight / (ChargeWeight x TntEquivalent) + 0.5) ^ -0.5`;
  - mass = `FragMassScale% x CaseWeight / count`.

| Shell | Charge | Fragments | Case | Fragment speed |
|---|---|---|---|---|
| HE M821 | 680 g, TNT x1.456 | 2800 | 3330 g | about 1060 m/s |
| HE O-832DU | 400 g | 2700 | 2400 g | about 740 m/s |
| Smoke M819, D-832DU | 100 g (the HE warhead) | default 300 | default | |
| Practice M879 | 100 g, no fragments | | | |

How a character's armour and hit zones take that isn't in the files, hence the test.

### Output (`<game profile>\rmt\blasttest\blast\`)
- `plan.csv`: `id,prefab,soldier,x,z,az,descent,stance,uncon`, and `layout.csv`: `along,across` per soldier
- `plan.json`: the same, with each trial's shell name
- `bursts.csv`: `id,x,y,z,ground`: where each shell went off
- `hits.csv`: `id,n,x,y,z,stance,life,state,health,bleeding,min_zone`. `life` is 0 alive, 1 unconscious, 10 dead (the engine's values, as `RMT_BlastTest.c` and `score` use them; `state` 2 is also counted as dead);
  `health` and `min_zone` (the worst hit zone) run from 0 to 1.
- `summary.json` (from `score`): per shell, stance and setting, the fitted distances in metres
- `..\blasttest.status.json`

---

## `rockettest.py`: live rocket flight test

How the game's rockets fly, wind included. The field map's **Rocket launcher shot** (sight mark, hold and aim bearing)
reads these flights; it doesn't model the rockets, because the engine's `MissileMoveComponent` physics are native.

```bash
python rockettest.py plan                # write the plans (one per wind) into the game profile
python rockettest.py run                 # plan, then one game run per wind; about 80 minutes. Rerun to finish a broken run
python rockettest.py score [folder]      # report, and write out/rockets.json for the site
python rockettest.py check               # the site's own answers fired in the game; about 50 minutes
python rockettest.py check-score [dir]   # that report again
python rockettest.py check-twins         # after a check: its shots again in still air, the wind's part of each miss; ~50 min
python rockettest.py check-twins-score [dir]  # that report again
python test_sitesolver.py --site <field map folder>   # rocketfit's copy of the site's calculator against the real one
```

### Requirements
Steam running and the game closed, as for `firetest.py`. It uses the site's Everon terrain to find open sea.
`test_sitesolver.py` needs Node.js and the field map's folder.

### What it does
1. **Plan.** Six rockets (`ROCKETS`: PG-7VM, PG-7VL, PG-7VR, M72A3, PG-22, RPG-75), each at 11 elevations (`ELEVS`,
   -12° to 20°), in fifteen winds (`WINDS`): still air three times over; from the right (east) at 3, 5, 10, 15 and
   20 m/s; from the left (west) at 5, 10 and 20; head and tail at 5, 10 and 20; then still air once more, laid out
   like a wind run (`SAME_LAYOUT`). The first five are the original set; the rest show how the wind's effect grows with
   its speed and whether left is the mirror of right, so nothing has to be assumed about either. Every rocket gets its
   own launch point 300 m above open sea, 120 m from any other, with 1.5 km of sea ahead (north), so it flies its whole
   life and blows up at its `TimeToLive` in the air.

   **The game's scatter repeats.** Two rockets launched alike don't fly alike: the still-air repeats end up to 11 m
   apart in height (M72A3; PG-22 7 m, the PG-7s 1 to 2 m). But the draws come from a sequence that starts afresh every
   run, so the shot in the same place in two runs gets the same draw: today's still-air run matched the one flown two
   days earlier to the centimetre, and a 1 m/s and a 3 m/s crosswind run matched each other exactly. So every wind
   run's shot is measured against its twin in `SAME_LAYOUT` (the same place in its run), and the scatter cancels.
   Measured against the still-air average instead, every wind seemed to move the M72A3 0.4 m and the PG-22 0.25 m at
   300 m whatever its speed (the twins' own draw against the average of three others), and the wind tables looked noisy
   enough to need smoothing. They don't: like against like, a crosswind moves those rockets' height by under 1 cm.
2. **Run.** One game run per wind (`<game profile>\rmt\rockettest\w0` to `w15`, in `WINDS` order, so new winds added
   at the end leave the runs already flown alone), with `-rmtFire -rmtFireGap=1`:
   `RMT_FireTestEntity` launches each rocket with `MissileMoveComponent.Launch` from the plan's 13th column (`y`,
   the launch height) and, because every id starts with `T`, writes every frame to `traj.csv`. A wind is set with the
   weather override and given 60 s to settle. The game keeps its output files open until the run ends, so a run that
   hangs leaves nothing: one run per wind loses at most that wind, and `run` skips winds whose
   `firetest.status.json` says done. (A single run of all winds once hung for good on a wind change.) Scoring reads
   only runs marked done: one still going has a half-written `traj.csv` whose flights stop in mid-air.
3. **Score** (`rocketfit.py`):
   - **Flight time.** Every frame's time is rebuilt from the flight itself (`rockettest.flight_time`): the path walked
     over the speed the game reports, from the launch point. The recordings' own time stamps aren't the projectile's:
     it sits still for 2 to 34 ms after it is spawned (different for every shot and on average for every run), and a
     hitch in the game shifts the stamps of everything in the air by up to 0.2 s. By the stamps, a run whose shots
     started 18 ms later looked like a flight held back by 17 m (for a 900 m/s bullet), which the old tables turned
     into metres of lift or drop per m/s of crosswind; twin flights differed by up to 0.15 s at the same distance,
     rebuilt by under 1 ms for most rockets. The launch velocity is the one the game reports while the projectile
     still sits at the launch point.
   - per rocket and elevation, the still-air flight every 0.05 s (along the ground, height), averaged over all the
     still-air flights (four of the game's scatter draws). A recording that stops up to 0.35 s short of the others (a
     game hitch drops the last frames of a few shots in a row, in mid-air) is carried on to the self-destruct time at
     its last velocity; more and it is left out. Every table then stops where the rocket's first flight ends, so no
     average switches to fewer flights at the end (that made the last frames jump by metres). `life` is the median
     flight, the self-destruct time;
   - `winds`: every test wind on its own, per elevation, every 0.1 s (`by: 'distance'`): where the still-air flight
     is at that moment, D m along the ground, how much later, higher and further right the wind's shot is when it
     has come the same D m than its twin in `SAME_LAYOUT`. Measured at the same distance and against the twin, neither
     the time stamps nor the scatter get into it. The site blends between the winds and elevations flown (see below);
     nothing is assumed about how the effect grows with speed, which side it comes from or how it changes with
     elevation. (Also still written, for older readers: `head`, `tail`, `cross`, per m/s, averaged over the
     elevations.)
   - a report: each test wind's effect per m/s where the rocket is 100 to 500 m out at level: sideways drift (+ =
     into the wind), change in height and delay, so it shows whether the effect grows in step with the wind and
     whether left mirrors right; then the elevation each rocket needs on level ground, against each launcher's sight
     marks.

   What the runs showed (per m/s of wind, 500 m out, level): crosswinds are mirror images, left against right within
   0.002 m sideways; the drift grows in step with the wind for the M72A3, PG-22 and RPG-75 (within 1%), less than in
   step for the PG-7VM (1.48 m per m/s at 3 m/s, 1.34 at 20) and more for the PG-7VL (1.41 to 1.76); the PG-7VR swings
   back past 200 m, differently at every speed. A crosswind barely changes height (under 1 cm, but the PG-7VM and VL
   lose 1.9 and 2.2 m at 500 m in 20 m/s, turning into it). Head and tail winds change height nearly in step with
   their speed (M72A3, headwind: -0.35, -0.36, -0.40 m per m/s at 5, 10, 20 m/s), except near the end of a rocket's
   range (RPG-75 at 500 m: -3.3 to -7.1).

How the wind is used (the site's `shot-core.js` `rocketWind`, copied in `rocketfit.wind_offset`): the crosswind part
from the runs from that side, the head or tail part from those runs, each blended between the two wind speeds flown
around the wanted one (still air counting as 0 m/s) and between the two elevations around the shot's; past 20 m/s it
grows in step with the speed; the two parts are added. A launcher's range is how far its rocket gets before it blows
up, at the target's height.

4. **Check** (`check`): random shots solved the site's way (`rocketfit.aim`, the site's solver copied:
   `test_sitesolver.py` runs both on the same shots and they must agree), fired in the game: ten random winds of 2
   to 20 m/s from anywhere (each its own run, `<game profile>\rmt\rockettest-check\w<n>`), four shots per rocket per
   wind, from 80 m out to the launcher's range at that height, 30 m below to 30 m above. The report gives each
   rocket's miss where it reaches the target's distance: height and side, mean and rms, and its worst shots. That miss
   is the calculator's error plus the game's own scatter (up to 11 m in height for an M72A3 far out), which no
   calculator can foresee.
5. **Twins** (`check-twins`, after a check): every check run replayed in still air in a run of its own, laid out the
   same, so each shot has its twin with the same draw of the scatter (`<game profile>\rmt\rockettest-check-twins`).
   Per shot, the wind's real part (the shot minus its twin, at the target's distance) against the calculator's (its
   flight at the shot's elevation with the wind and without): the wind model's own error, scatter taken out. And the
   twins against the calculator's still-air flight: its still-air error plus the scatter.

Results (4 October 2026; 236 shots, ten winds of 3 to 17 m/s from every side, 80 m out to each launcher's range):

| Rocket | Miss, height rms | Miss, side rms | Worst | Wind's part off: height / side rms | Still-air twins: height mean / rms |
|---|---|---|---|---|---|
| PG-7VM | 0.58 m | 0.56 m | 2.48 m | 0.13 / 0.55 m | -0.05 / 0.51 m |
| PG-7VL | 0.35 | 0.62 | 2.37 | 0.40 / 0.62 | -0.04 / 0.12 |
| PG-7VR | 0.69 | 0.80 | 3.44 | 0.55 / 0.79 | -0.07 / 0.67 |
| M72A3 | 0.94 | 0.22 | 4.45 | 0.11 / 0.22 | +0.00 / 0.99 |
| PG-22 | 1.10 | 0.08 | 2.61 | 0.04 / 0.08 | -0.42 / 1.11 |
| RPG-75 | 0.57 | 0.38 | 2.89 | 0.07 / 0.38 | -0.13 / 0.62 |

The M72A3's, PG-22's and RPG-75's misses are almost all the game's scatter (their twins miss as much in still air);
their wind is right to a few cm in height. The PG-7s' wind is the least exact (up to 0.8 m rms sideways, worst 3 m far
out in 14-17 m/s): their drift grows unevenly with the wind's speed and elevation, and is blended between the ones
flown. The previous calculator (one averaged wind table scaled with the speed), checked in milder winds (2 to 12 m/s)
and shorter shots, missed by 0.5 to 1.6 m rms in height, worst 6.3 m.

Elevations between the tested ones are blended in each flight's own launch frame (distance along the launch line,
drop below it), then turned to the wanted elevation: leaving every other elevation out, that predicts the missing
flights to well under a metre for most rockets (blending heights directly was off by up to 4 m). Past the end
elevations the end flight is turned, not extrapolated.

### What the game's files say
- **Rockets** (`Prefabs/Weapons/Ammo/Ammo_Rocket_*.et`, `MissileMoveComponent`): `InitSpeed` (PG-7VM 140, PG-7VL
  112, PG-7VR 66, M72A3 150, PG-22 133, RPG-75 189 m/s), a motor (`ThrustForce` for `ThrustTime` after
  `ThrustInitTime`; the M72A3, PG-22 and RPG-75 have practically none), `Mass`, `ForwardAirFriction`,
  `SideAirFriction`, `AlignTorque` and `TimeToLive` (5 s; M72A3 6.1, RPG-75 6).
- **Launchers** (`Prefabs/Weapons/Launchers/*/..._base.et`): no muzzle speed factor. `SightsRanges` give each
  zeroing mark's `Angles` (the bore above the line of sight, in degrees). The M72A3's `ProjectileSpawnPositions` turn
  the rocket 0.5° up from the bore.
- **PGO-7V3** (`Optic_PGO7V3_base.et`): no zeroing; the range lines are drawn on its reticle,
  `UI/Textures/Sights/PGO7/PGO7_white_solid_UI.edds` (2048 px, BC7, LZ4-chunked). `m_fReticleAngularSize 6` degrees
  spans `m_fReticlePortion 0.65234` of the texture, which is the lateral scale's ±5 units: 222.7 px per degree, 0.6°
  per lateral unit. Measured from the cross at the top (the bore): PG-7VM lines 200-500 m at 1.62, 2.05, 2.52 and
  3.12°; PG-7VL (the right-hand scale) 100, 150, 200 and 300 m on the same lines; PG-7VR 100, 150 and 200 m at 3.71,
  4.77 and 5.86°. Those, and the iron-sight marks, sit close to what the measured flights need, which is how the cross
  is known to be the bore.

### `bullettest.py`: the guns' rounds

```bash
python bullettest.py plan               # write the plans (one per wind) into the game profile
python bullettest.py run                # one game run per wind; about 15 minutes
python bullettest.py score [folder]     # tables -> out/bullets.json (copy to the site's static/data/bullets.json)
python bullettest.py check              # the site's own answers fired in the game; about 30 minutes
python bullettest.py check-score [dir]  # that report again
python bullettest.py check-twins        # after a check: its shots again in still air, the wind's part of each miss; ~30 min
python bullettest.py check-twins-score [dir]  # that report again
```

The bullets keep the original five winds (`bullettest.WINDS`). The site doesn't read their wind tables: it flies a
round's wind itself, from the round's drag (proportional to airspeed squared) fitted to its still-air flight, flown with
and without the wind, the difference added to the measured flight (`shot-core.js` `bulletWind`, copied in
`rocketfit.bullet_wind`). Fitted only to still air, that drag predicts the crosswind drift the runs measured for all 14
rounds to within 1.5%. Before the flight-time fix (see `rockettest.py` above) the measured wind tables were useless for
this: the 7N6's crosswind runs started 18 ms after its still-air ones, which read as 1.7 m along and 0.14 m up per m/s
of wind, so a crosswind from one side lifted a downhill shot by metres and from the other dropped it.

`check`: random shots solved the site's way (`rocketfit.aim`), fired in the game: eight random winds of 2 to 20 m/s
from anywhere (each its own run, `<game profile>\rmt\bullettest-check\w<n>`), two shots per round per wind, 100 m out
to 800 m (the long-range rounds further: `CHECK_FAR`), 40 m below to 40 m above. The same report as the rockets'.

Results (4 October 2026; 224 shots, eight winds of 4.5 to 19.5 m/s, out to 1.8 km): every round's miss 0.02 to 0.13 m
rms in height and 0.02 to 0.11 m sideways, worst 0.40 m (a PKT 969 m out in 19 m/s). The twins (`check-twins`) put the
wind's part within 0.01 m in height and 0.02 to 0.11 m sideways: the drag-flown wind is right.

The same flights as the rockets, for the rounds of the site's scoped weapons: 7N1 (SVD), 57N323S (PKM, UK59, and the
PKT at its 1.036 speed), M118 (M21), M80 (M240), M855 (M16A2, and the carbine at 0.93), 7N6 (AK-74, AKS-74U at 0.835,
RPK-74 at 1.06), B32 (NSV), BZ (KPVT), and the M242's M792 HEI-T and M791 APDS-T. Each is launched at its weapon's speed
(the ammo's `InitSpeed` times the weapon's `BulletInitSpeedCoef`, found by `rmtlib/prefab.py` up the prefab
inheritance), 1500 m above the sea so even 12° down flies its full 10 s, every 0.02 s recorded
(`-rmtFireTraceDt=0.02 -rmtFireMaxT=10 -rmtFireGap=0.3`), and tabled every 0.1 s.

Why not the mortar model? Bullets use the same `ShellMoveComponent` (`AirDrag` / `Mass`), but drag that goes with the
square of speed doesn't match the engine's own tables for them (`Configs/Weapons/AIBallisticTables/AIBT_*.conf`: per
launch speed, a level shot's distance, drop and time): the 7N1 loses speed faster early and slower late than any single
drag factor gives, as if drag changes with speed. Mortar shells are slow enough not to show it.

Scopes: the turret scopes' `SightRangeInfo` lists only ranges (its first number is the turret's position, 0 to 1, not an
angle), so the game zeroes the centre for the range set; the site takes the angle that puts a level shot there from
the flights. The range-line sights (BTR-70 and BRDM-2 PP-61, LAV-25) were measured off their reticle textures like the
PGO-7: rows of each range line, the texture's scale from `m_fReticleAngularSize` over `m_fReticlePortion`; the row the
bore points at is fitted to the flights.

### `launchertest.py`: through a soldier's real launcher (written, not yet run)

```bash
python launchertest.py plan              # write the plan into the game profile (nothing runs)
python launchertest.py run               # plan, then run the game; about 30 minutes
python launchertest.py score [folder]    # the three reports below
```

`rockettest.py` launches rockets directly. This one fires them the way a player does, to check what the site's
calculator assumes but `rockettest.py` can't show. The game's own AT soldiers carry the launchers: FIA AT (RPG-7, iron
sight), USSR AT (RPG-7 with PGO-7), US LAT (M72A3), USSR LAT (RPG-22), FIA LAT (RPG-75). Each stands on a cliff 8 to
60 m above the sea on `EmptyEden`, facing open sea. `RMT_LauncherTestEntity` (`Scripts/Game/RMT/RMT_LauncherTest.c`,
flag `-rmtLauncher`) spawns a fresh soldier for every round, selects the launcher, takes the safety off, sets the
zeroing (`SetSightsRange`), raises and aims down the sights. It then turns the soldier's aiming angles (the input
context's `SetAimingAngles`, as the game's cinematics drive a character) until the **bore**, read from the weapon
manager's muzzle transform, holds the planned bearing and elevation to 0.02° for four checks in a row. Then it pulls
the trigger. At that moment it records the bore and every way the engine reports the sights:
`GetSightsDirection`, `GetSightsTransform`, the rear and front sight points, and the weapon's zeroing transform. It
then follows the rocket frame by frame.

1. **Sights:** sights-only lines at every zeroing mark of every launcher measure the angle between the sight line and
   the bore. The site takes it from the prefabs' `SightRangeInfo` `Angles`, and takes the PGO-7's cross as the bore.
2. **Launch:** each fired rocket's first velocity against the bore: a fixed offset (the M72's 0.5° spawn angle), the
   weapon's own scatter (`DispersionRange`, measured nowhere else) and the launch speed.
3. **Hits:** each launcher fires 4 rounds at each of its marks (a level target in still air, the elevation from the
   site's solver), plus 4 rounds in an 8 m/s crosswind with the site's aim-off. The miss is read where each rocket is
   the target's distance out.

Output in `<game profile>\rmt\launchertest\launcher\`: `plan.csv`
(`id,soldier,launcher,x,z,az,el,zero,count,wspeed,wdir,stance`), `plan.json`, `shots.csv` (see the header of
`RMT_LauncherTest.c`) and `traj.csv`.

Untried: whether a character without a player or AI takes `SetAimingAngles` and `SetFireWeaponWanted` every frame as
the cinematics suggest. If it doesn't, the aim gives up after 60 corrections and says so in the log (the shot still
fires, with its real bore recorded).

### Output (`<game profile>\rmt\rockettest\w<n>\firetest\`)
- `plan.csv` (`firetest.py`'s columns plus `y`) and `plan.json` (with rocket, elevation, wind and repeat)
- `traj.csv`: `id,round,t,x,y,z,vx,vy,vz`, every frame; `shots.csv`: one line per rocket (where it ended)
- `..\firetest.status.json`
- `out/rockets.json` (from `score`): copy to the site's `static/data/rockets.json`. Each rocket has `format: 2` and
  its `winds` (see Score); a site older than that reads the per m/s `head`, `tail` and `cross` instead.

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


## Choosing targets in the desktop app

Labs now provides baseline/mod target checklists for fire, blast, bullet, rocket and launcher tests.
Use **Scan installed targets**, choose an addon, tick targets and inspect resolved ammunition pairings.
The selected CLI is `labtest.py`; the standalone commands in this document retain baseline presets.
Read [labs-selection.md](labs-selection.md) for native mortar planning, measured dataset requirements,
saved-run reporting and resume verification.
