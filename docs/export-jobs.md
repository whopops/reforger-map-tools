# `rmt.py export`: jobs, settings and raw output

```bash
python rmt.py export <world> [--jobs a,b,c] [--tile 500] [--region tx0,tz0,tx1,tz1] [--max-chunks N]
                              [--set NAME=VALUE ...] [--retries 3] [--stall 600]
```

## What a run does

1. **Resolve the world.** A `.ent` file on disk is mapped to its addon (the nearest `.gproj` above it gives the
   addon GUID and parent folder, which are added to the launch). A resource path or a bare name is looked up in
   `out/worlds.txt` (made by `rmt.py worlds`). The run's name is `<slug>/<build>`.
2. **Open the run record**, `out/<slug>/<build>/manifest.json`. If it exists the run resumes inside it.
3. **Run the Workbench jobs** (`probe`, `mapdata`, `roads`, `names`, `entities`, `terrain`, `surface`,
   `foliagetrace`) in **one Workbench launch**, one load of the world, in the order given.
4. After each launch, read every job's `<job>.status.json`. Jobs whose status is `done` or `partial` are recorded;
   the rest are relaunched together (up to `--retries` launches). Chunk jobs skip chunks that already have an `.ok`
   marker, so only the chunk in progress is lost after a crash.
5. **Run `satellite`** and **`foliage`**, if asked for, in the game itself (separate launches; see
   [satellite-and-foliage.md](satellite-and-foliage.md)).
6. Print `done`, or `FAILED: <jobs>  (rerun the same command to resume)` and exit 1.

Default jobs: `probe,mapdata,roads,names,entities,terrain,surface`. `satellite`, `foliage` and `foliagetrace` are
accepted by `--jobs` but are not in the default list.

### Supervision

`workbench.py` reads the launch's `console.log` and watches for lines containing `RMT|`. Every such line is a
heartbeat; chunk progress is shown one in 25. If no heartbeat arrives for `--stall` seconds (a modal dialog, a hang)
the process tree is killed and the attempt counts as failed. An attempt also fails if the log shows a script
compile error (not retried: fix the script), if the process writes no log, or after 24 hours. Crash reporter windows
that appear during a run are closed. The status file of each job is deleted before every launch so a stale one is
never mistaken for success.

### Exit codes of the plugin (what the log says)

| Code | Meaning |
|---|---|
| 0 | all requested jobs finished |
| 1 | a job failed |
| 2 | bad arguments (no `-rmtJob`/`-rmtOut`, tile under 10, unknown job) or no WorldEditor module |
| 3 | the world did not load. `export` stops at once and writes nothing |

## Jobs

All Workbench jobs write under the Workbench profile: `...\profile\rmt\<slug>\<build>\` (the "raw folder").

### `probe`
Loads the world and records map bounds, the chunk grid and the editor entity count. Fails fast (exit 3) if the world
does not load. Everything else depends on it: it is how no map size is hardcoded.
Output: `probe.json`, `{"world", "min": [x,y,z], "max": [x,y,z], "tile", "cols", "rows", "editorEntities"}`.
Arland: 4096 m, 9x9 chunks, about 173k entities, loads in about 3 s. Everon (`Eden`): 12800 m, about 1.2M entities.

### `mapdata`
BI's own 2D-map export (`MapDataExporter`, the same calls as BI's `WorldDataExport` plugin): roads, power lines,
buildings, forest areas, water bodies and hills, plus a shaded land/ocean raster.
Output: `mapdata/<World>.topo` (binary geometry, read by `rmtlib/topo.py`) and `mapdata/<World>.tga` (square raster).
The `.topo` is the primary source for roads; see [bakers.md](bakers.md).

### `roads`
Every road piece exactly as the world stores it, whether nested under a road generator or not, with spline shapes.
Output in `roads/`:
- `roadentities.csv`: `road,which,material,width,type,point,x,y,z` (`which` is `ctrl` for a spline point or `curve`
  for a tessellated shape curve)
- `roadboxes.csv`: `road,prefab,parent,x,y,z,minx,miny,minz,maxx,maxy,maxz`
- `splines.csv`: `road,shape,generator,point,x,y,z`

Decals painted by the road system (beach debris, flower beds, runway marks) are kept here and dropped by material
when baking. This is the fallback source for roads when a world has no `.topo`.

### `names`
Every entity carrying a map-descriptor component: town names, map labels and icons, with every setting of the
component. Output: `names/descriptors.csv`: `entity,class,prefab,name,x,y,z,component,var,value`. Display names are
string-table keys (`#AR-MapLocation_...`); `bake places` resolves them with the game's own English text.

### `entities`
Every entity in the world, chunk by chunk, except engine helpers. Each entity appears once, in the chunk containing
its origin. Output: `objects/o_<tx>_<tz>.csv` plus `.ok`:
`class,prefab,x,y,z,yaw,pitch,roll,scale,minx,miny,minz,maxx,maxy,maxz,parent,lminx,lminy,lminz,lmaxx,lmaxy,lmaxz`
(`min/max` is the world-aligned box, `lmin/lmax` the entity's own box before rotation, for oriented footprints;
`parent` is the parent's prefab or class). Trees, buildings, walls and rocks all come from here; classification
happens at bake time.

### `terrain`
Ground height by chunk, from `GetSurfaceY` (the ground without objects). Output: `terrain/t_<tx>_<tz>.csv` plus
`.ok`. Header `x0,z0,step,cols,rows`, then one line per row, south to north, west to east. Values are integer
centimetres. The last row and column repeat the next chunk's first, so chunks overlap by one sample.
Default step 1 m (501 x 501 per 500 m chunk). Arland yields about 20 million samples.

### `surface`
Rays over every spot an object covers, for roofs, canopy and bullet stops (the slowest job). Output:
`surface/s_<tx>_<tz>.csv` plus `.ok`. Header `x0,z0,step,cols,rows`, then sparse lines `col,row,top,bottom,kind,cover`
with heights in decimetres above the ground; `kind` 1 building, 2 other solid, 3 vegetation. Cells not listed are
open ground or water. Default step 0.5 m.

### `foliagetrace` (experiment)
Fires level rays through a sample of plants of each kind with every ray setting the engine has, to test whether rays
could replace the foliage photographs. They cannot (see PLAN.md section 7b). Output: `foliagetrace/rays.csv`
(`prefab,kind,height,band,config,rays,hits`). Not part of the pipeline.

### `satellite` and `foliage`
Run in the game, not Workbench: [satellite-and-foliage.md](satellite-and-foliage.md).

### `ballistics`
Accepted by the plugin but not by `--jobs`; see [firetest.md](firetest.md).

### `worlds`
Not an `export` job. It backs `rmt.py worlds`: one launch that writes `worlds.txt` (every `.ent` Workbench can see)
into `...\profile\rmt\_worlds\`, copied to `out/worlds.txt`.

## Settings (`--set NAME=VALUE`)

Passed to the plugin as `-rmtNAME=VALUE`. Only the first group is read by Workbench jobs.

| Setting | Job | Default | Meaning |
|---|---|---|---|
| `Step` | `terrain`, `surface` | 1 and 0.5 | Sample spacing in metres (minimum 0.25). Smaller means larger files and longer runs. |
| `FtPerKind` | `foliagetrace` | 4 | Plants tested per kind. |
| `SatSpan` | `satellite` | 400 | Ground square covered per shot, metres. |
| `SatFov` | `satellite` | 15 | Lens angle in degrees. |
| `SatHeight` | `satellite` | computed | Camera height in metres. Default is the highest ground plus the height at which a square fills the frame, with 10% spare. |
| `SatWait` | `satellite` | 1.5 | Seconds to wait after streaming finishes before each shot. |
| `SatGrid` | `satellite` | computed | `x0,z0,cols,rows,span`: the grid of squares. Default covers the terrain bounds. |
| `SatCenters` | `satellite` | none | `x,z;x,z`: shoot only these spots (tests). Replaces the grid. |
| `FoliageWorld` | `foliage` | `EmptyArland` | World the plants are photographed on (empty, so nothing is in the way). |
| `FoliageLimit` | `foliage` | all | Photograph only the N most common kinds. |
| `FoliageSides` | `foliage` | 8 | Sides photographed at each distance. |
| `FoliageFov` | `foliage` | 40 | Lens angle in degrees. |
| `FoliageLift` | `foliage` | 60 | Metres above the ground the plant is placed. |
| `FoliageTop` | `foliage` | 1 | Take the view from below (0 turns it off). |
| `FoliageLod` | `foliage` | `25,50,100,200,300` | Distances in metres for the far views. |
| `FoliageSpot` | `foliage` | `2048,2048` | Where on the empty world the photographs are taken. |
| `FoliageWidth`, `FoliageHeight`, `FoliageMode` | `foliage` | 2560, 1440, `BORDERLESS` | Game window size and mode (`FULLSCREEN` or `BORDERLESS`). Changed for the run only; your settings file is put back. |

`--tile`, `--region` and `--max-chunks` are separate options (they go to every Workbench job). `--region` is in chunk
indices, inclusive.

## The manifest

`out/<slug>/<build>/manifest.json` records the world, game and Tools build, raw folder, chunk size, addon GUIDs, the
probe result, and for each job when it finished, how many seconds it took and its status
(`result`: `done`, `partial` or `failed`; `made`, `skipped`, `remaining` chunks; `items`; `ms`).
`bake` finds the newest manifest that matches the world you name.

## Examples

```bash
# the smallest useful test: 2 chunks of terrain and entities
python rmt.py export Arland --jobs probe,terrain,entities --max-chunks 2

# a region only: chunks (1,1) to (2,2)
python rmt.py export Arland --jobs probe,terrain --region 1,1,2,2

# a mod map from disk
python rmt.py export "C:\Users\me\Documents\My Games\ArmaReforger\addons\MyMap\worlds\MyMap.ent"

# satellite at a closer lens, test spot only
python rmt.py export Arland --jobs probe,satellite --set SatCenters=2048,2048 --set SatSpan=200
```

Estimated time on Everon (from PLAN.md): the satellite capture is about 1,100 shots, roughly 1 to 2 hours;
`surface` is the slowest Workbench job. Always time Arland first.
