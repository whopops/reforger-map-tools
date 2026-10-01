# The game-side jobs: `satellite` and `foliage`

Both jobs run in the **real game** (`ArmaReforgerSteamDiag.exe`), not Workbench. Command-line Workbench never draws
the world, so every screenshot it takes is black (PLAN.md, spike S3). The game is started with our addon, the world,
`-rmtSat 1` or `-rmtFoliage 1`, and `-rmtOut=$profile:...`. `RMT_GameHook.c` notices the flag and spawns the capture
entity. The entity moves a camera frame by frame, so the renderer really draws between shots. When done it writes
`satellite.status.json` or `foliage.status.json` and asks the game to close. `rmt.py` also closes it if it does not.

What this means for you:
- The game window appears and runs on your screen for the whole job. Do not use the PC for other 3D work meanwhile.
- Close the game first (`rmt.py` refuses if `ArmaReforgerSteam` is running). Steam must be running.
- Output is in the **game's** profile: `<Documents>\My Games\ArmaReforger\profile\rmt\<slug>\<build>\satellite` or
  `...\foliage`. `rmt.py bake` looks there.
- Both resume. Re-running the same command continues after the last finished shot or plant.

---

## `satellite`

```bash
python rmt.py export <world> --jobs probe,satellite
```
(`probe` must have run on this export at some point: the grid is computed from its map bounds.)

### How it works
1. `rmt.py` computes a grid of ground squares covering the terrain bounds: `SatSpan` metres a side (default 400).
2. The camera sits high above each square looking straight down with a narrow lens (`SatFov`, default 15 degrees).
   Height is the highest ground plus the height at which one square fills the frame's height, plus 10%.
3. For each square the entity moves the camera, calls `BeginPreload` and waits for `IsPreloadFinished`, sets noon and
   clear weather, waits `SatWait` seconds (default 1.5), and takes the screenshot (1920x1080). Alongside each picture
   it writes `s_<col>_<row>.txt` holding the exact camera (position, span, height, lens). Squares whose `.txt`
   already exists are skipped.
4. Orthographic cameras render black in this build, which is why the shots are perspective.
5. `bake --parts satellite` then corrects every map pixel exactly: it knows the camera, so a ground point (x, z) at
   terrain height h appears at a known pixel; it takes the height from the terrain export and samples the nearest
   shot's centre (the least lean for tall objects). That removes the scale changes hills cause. Trees and buildings
   still lean slightly away from each shot's centre, less so with a narrower lens.

### Tuning (`--set`)
`SatSpan`, `SatFov`, `SatHeight`, `SatWait`, `SatGrid`, `SatCenters`: see the settings table in
[export-jobs.md](export-jobs.md). To try it, shoot a few spots first:

```bash
python rmt.py export Arland --jobs probe,satellite --set SatCenters=2048,2048;1800,2000
```
(In PowerShell, quote the whole `--set` value: `--set "SatCenters=2048,2048;1800,2000"`.)

Known issues: a blue haze shows from about 1.8 km up. Options are fog off, a lower camera with a wider lens, or colour
correction. On Arland, 9 shots took 56 s; Everon needs about 1,100 shots (1 to 2 hours) and gives about 21,800
tiles (350 to 500 MB) at the finest zoom. Satellite tiles are outside the 2.5 GB data budget, but they must fit on the
site's disk.

### Output files
Per shot: `s_<col>_<row>` picture (`.bmp` or `.png`, depending on the build; the baker reads either, and `.jpg`) and
`s_<col>_<row>.txt`. Then `satellite.status.json`.

---

## `foliage`

```bash
python rmt.py export <world> --jobs probe,entities,foliage
```
(`entities` must be exported: the list of plants to photograph comes from this map's own entities.)

### How it works
1. `rmt.py` builds `plants.csv` (`prefab,kind,count,mean_scale`): every standing tree and bush prefab on the map, most
   common first. Seasonal variants on a map (snowy spruce, autumn birch) get their own kind.
2. It starts the game on an **empty world** (`EmptyArland` by default, `FoliageWorld` to change), so nothing stands
   behind the plant.
3. For each plant, the entity spawns one plant `FoliageLift` metres (default 60) above the ground, with the camera low
   enough that the plant's base is 5 degrees above the horizon, so everything behind it is sky. It takes these views,
   each twice, once with the plant shown (`<id>_a`) and once hidden (`<id>_b`):
   - `<key>_0_<s>`: `FoliageSides` sides (default 8) close up, backed off until the plant fits the frame,
   - `<key>_top`: straight up from below, the crown against the sky,
   - `<key>_d<m>_<s>`: the same sides again at each distance in `FoliageLod` (default 25, 50, 100, 200, 300 m).
4. That is 49 views (98 screenshots) per plant, about 100 s per plant. Everon has about 70 kinds.
5. While the game runs, `rmt.py` converts the 6.2 MB BMP screenshots to lossless PNG (about 1 MB each) in the
   background and removes a BMP only after the PNG is verified.
6. Each view adds a row to `shots.csv` (the old tool's columns plus `view`). A plant whose last view is on disk is
   skipped on a rerun.
7. `bake --parts foliage` measures the pairs, then `--parts plants` joins the result to every plant on the map.

### Why photographs
Physics rays go through leaves: every ray setting the engine has (including the visibility flag and the Foliage,
ViewGeometry and Vegetation layers) only hits trunks and branches, about 18% of a plant's box with a correlation of
0.37 against the photos. And distance matters: the game swaps in simpler, denser models far away (a tall spruce reads
0.56 close up, 0.79 at 150 m and 0.84 at 300 m), so the profile has cover per distance band and the line of sight
interpolates by viewer distance. Beyond about 200 m small bushes cover only a few pixels, so their numbers are rough
there (the `px` value is the confidence). Rays are probably closer to what the AI sees; photographs are closer to
what a player sees.

### Tuning (`--set`)
`FoliageWorld`, `FoliageLimit` (try `--set FoliageLimit=3` first), `FoliageSides`, `FoliageFov`, `FoliageLift`,
`FoliageTop`, `FoliageLod`, `FoliageSpot`, `FoliageWidth`, `FoliageHeight`, `FoliageMode`: see
[export-jobs.md](export-jobs.md). The game's video settings are changed for the run (to the given size and mode) and
the original settings file is put back afterwards, even after a failure.

### Output
`foliage/plants.csv`, `foliage/shots.csv`, `foliage/<id>_a.png` and `<id>_b.png`, then `foliage.status.json`.
After baking: `foliage_shots.csv` and `foliage_profiles.json` (see [bakers.md](bakers.md)).
