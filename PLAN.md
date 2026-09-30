# Reforger Map Tools: plan

Point it at any Arma Reforger map. It runs Arma Reforger Tools (Workbench) unattended, extracts everything a map
site needs (terrain, roads, footpaths, trees, buildings, place names, line-of-sight data, and our own satellite
images), checks the results, and bakes a site-ready data folder. The site data must stay under 2.5 GB, not counting
the satellite tiles.

Status: plan only. Nothing is built yet. Written 2026-09-29.

---

## 1. What we start from

### Proven on Everon (the old tools in `arma-map/everon-map/tools`)

| Data | Old source | Old baker | Baked size now |
|---|---|---|---|
| Terrain height, 1 m grid | `EveronLOSExportTool` "Island: terrain" (button) | `bake_los.py` | part of `los/` |
| Every object (trees, buildings, walls, rocks) | "Island: objects" (button) | `bake_los.py`, `export_plants.py` | part of `los/`, `plants/` |
| 0.5 m surface rays (roof, canopy, bullet stop) | "Island: surfaces" (button) | `bake_los.py` | `los/` 148 MB |
| Roads, dirt roads, trails | `EveronRoadExportTool` (button) | `import_game_roads.py` | `roads.json` 0.7 MB |
| Foliage see-through profiles | `EveronFoliageMeasureTool` + screenshots | `measure_foliage.py`, `foliage_model.py` | `foliage.json` |
| Light LOS | from the above | `bake_light_foliage.py` | `light/` 3.5 MB |
| Satellite tiles | **external site** (reforger.recoil.org) | none | `tile_cache/` 166 MB so far |
| Place names, POIs | **external sites** (iZurvive, recoil.org) | hand-fitted | in `everon.json` |

Today the whole baked field map is about **157 MB**, and the 3D map about 155 MB (mostly the same LOS tiles). The
2.5 GB budget is about 15 times Everon's current size, so the budget only gets tight on maps much bigger than
Everon (see section 7).

The old exporters work, but only when you click buttons. They are Everon-specific (12800 m and 26 tiles are fixed
in the code and bakers), and they depend on two external sites. The raw exports are in `everon-data/` (about 3.8 GB)
and give us a **known-good reference** to regression-test the new tool on Everon.

### What the installed Tools support (checked in the local API docs, `Workbench/docs`)

- Workbench exe is `C:\Program Files (x86)\Steam\steamapps\common\Arma Reforger Tools\Workbench\ArmaReforgerWorkbenchSteamDiag.exe`
  (Tools build 24870687).
- `WorkbenchPlugin.RunCommandline()` and `WBModuleDef.GetCmdLine()`: plugins can run from the command line with
  our own options. BI's own `WorldTestPlugin` does this: it loads a map from the command line, waits for game mode
  (`WaitForGameMode`) and tests it. This is our template.
- `WorldEditor.SetOpenedResource(world)` loads a world from script. `GetTerrainBounds(min, max)` gives the map
  size, so nothing is hardcoded. `SwitchToGameMode()` / `SwitchToEditMode()` switch between play and edit mode.
- `Workbench.Exit(code)` returns exit codes the orchestrator can read.
- **`MapDataExporter.ExportData(type, path, world, ...)`**: BI's native exporter behind `SCR_WorldMapExportTool`,
  the tool BI uses to build the in-game 2D map. It exports **roads, power lines, buildings, forest/other areas,
  water bodies and hills**. `ExportRasterization(...)` renders a shaded land/ocean image. Its output format is
  not documented, which is Spike S2.
- `BaseWorld.SetCameraType(cam, CameraType.ORTHOGRAPHIC)` and `SetCameraVerticalFOV` give a true top-down
  orthographic camera: no perspective lean, and no error from terrain height.
- `System.MakeScreenshot(path)` (BMP) and `System.MakeScreenshotRawData(callback, x, y, w, h, dw, dh)`. There is
  also BI's `Screenshot_Autotest` entity, which flies a camera along waypoints taking screenshots in game mode,
  with `SetTimeAndDate` and `SetWeatherState`. This is our template for the satellite capture.

---

## 2. Architecture

```
rmt.py  (Python orchestrator: the only thing you run)
  |
  |-- find Tools (Steam libraryfolders.vdf), game build id (appmanifest), profile dir
  |-- write a temp .gproj that depends on the game + the map's addon (so mod maps work)
  |-- launch Workbench per job:  -gproj <tmp.gproj> -wbModule=WorldEditor -plugin=RMT_ExportPlugin
  |                              -rmtJob=<job> -rmtWorld=<world.ent> -rmtOut=<dir> -rmtRun=<run id>
  |-- watchdog: tail the Workbench console log for "RMT heartbeat" lines; kill + relaunch on a stall
  |   (resume from .ok chunks); give up after N retries with a clear report
  |-- validate each job's output (section 5)
  |-- bake (Python): raw -> site data + satellite pyramid
  |-- size report against the 2.5 GB budget; fail if over
  '-- manifest.json: map, world, game build, tool version, dates, counts, sizes, checks passed

RMT addon (Workbench, Enforce script)
  RMT_ExportPlugin : WorkbenchPlugin   one command-line entry, dispatches jobs, heartbeats, exit codes
  jobs: probe, terrain, entities, roads, mapdata, surface, names, satellite, (foliage)
  RMT_CaptureEntity : GenericEntity    placed temporarily, drives the ortho camera in game mode
```

### Rules the Grok tool broke, which this design keeps

- **One launch per job, not 2 tiles per launch.** A job runs to the end. Chunks are written with `.ok` markers,
  so a crash only loses the chunk in progress.
- **The orchestrator waits for the process** (Python `subprocess` with a timeout), watches heartbeats, and never
  trusts a status file older than the launch. It deletes stale status files first.
- **Every run gets its own output folder**, `out/<map>/<game build>/`. Resume only happens inside the same run.
  A new game build means a new export, never a silent mix.
- **Probe first:** confirm the world loaded (entity count, terrain bounds) or exit 3 and write nothing.
- **Folders are created one level at a time** (the old tools did this, so it is probably required).
- **No Everon constants.** Size, origin and tile count come from `GetTerrainBounds`.
- **Engine rules, not guesses:** classification uses prefab paths, classes and materials that we observe
  and record, not keyword guessing. Anything unclassified is listed in a report so the rules file can be extended.

### Runs on your PC, not the VPS

Workbench needs Windows, a GPU and a logged-in desktop session (Steam running). The VPS (1 vCPU, 1 GB) only
receives the baked output. Unattended means you start `rmt.py run --world <world .ent>` (or a scheduled task does, for
example when Steam updates the game build) and walk away. The screen may show Workbench while it works.

---

## 3. What gets extracted (general purpose)

Each job writes 500 m chunks (the grid comes from the terrain bounds) as CSV plus `.ok`, and a `job.json`
summary.

| Job | What | How | Notes |
|---|---|---|---|
| `probe` | map size, origin, entity count, water level | `GetTerrainBounds`, entity count, 9-box query | fails fast |
| `terrain` | height, 1 m grid, integer cm | `GetSurfaceY` | same format as the old tool |
| `entities` | **every** entity: class, prefab, transform (full matrix, so we get oriented footprints, not world boxes), local bounds, scale, parent | `QueryEntitiesByAABB` per chunk, origin-owned | trees, bushes, buildings, walls and rocks all come from here, classified at bake time |
| `roads` | every `RoadEntity` (nested or not): control points, material, width, type; spline shapes with road generators: tessellated curve | old `EveronRoadExportTool` logic, which was proven complete (2370/2370 on Everon) | footpaths = trail materials; decals are dropped at bake time by material |
| `mapdata` (optional) | BI's own roads, buildings, areas (forests), water, hills, power lines | `MapDataExporter.ExportData` | S2: blocked (`NoOutputFile`); not needed for the core data |
| `names` | town and place names, map labels | `MapDescriptorComponent` / `SCR_MapDescriptorComponent` entities | replaces iZurvive |
| `surface` | 0.5 m roof, canopy and bullet-stop rays (LOS) | old "Island: surfaces" logic | the slowest job |
| `doors` (optional) | door and ladder positions for real buildings | door components on `SCR_DestructibleBuildingEntity` children | only if the site wants it |
| `satellite` | ortho top-down screenshots in a grid | game mode + `RMT_CaptureEntity` (section 4) | noon, clear weather, fixed exposure |
| `foliage` (later) | see-through profile of each tree and bush species | old `EveronFoliageMeasureTool` approach, automated | only needed for the "Visual" LOS mode on new maps |

### Classification (bake time, from a rules file with defaults learned on Everon)

- **Roads (decided 2026-09-29):** BI's own 2D-map roads from the `.topo` `ROAD` section are the source
  (`rmtlib/topo.py`, `rmtlib/bake_roads.py`). They are already merged into whole roads and typed by BI: 0 runway,
  1 main, 2 paved, 3 dirt, 5 footpath, with widths. After flipping z they match the game's road pieces to about
  3 m, and they run on across bridges. Ends are joined only where the surfaces touch (half of both widths + 1 m),
  or where carrying the end straight on for up to 12 m hits another road. Nothing else is joined. On Everon
  against the live site: same length per kind (within 1%), 0.1 km of BI road that the site lacks, 4.9 km of site
  road BI lacks (invented links), and 1,245 junctions instead of 1,885. The roads job's pieces are the fallback
  when a world has no `.topo`.
- **Roads (fallback, from the road pieces):** by material path. `Roads/Data/` plus asphalt-dashed is a main road; asphalt, cobble or concrete is a
  street; dirt, forest or gravel is a dirt road; `Trail*` is a **footpath**. `Assets/Decals/...` and `Decal_*` are
  dropped. This is the rule in `import_game_roads.py` that already works. Unknown materials go to the report.
- **Trees and bushes:** class `Tree` or prefab under `/Vegetation/`. The kind comes from the prefab name prefix
  (`t_`, `b_`, `p_`) with a height fallback; stumps and debris are excluded.
- **Buildings:** `SCR_DestructibleBuildingEntity` / `Building` class, or prefab under `Structures/Houses`,
  `Industrial`, `Military` and so on. **Walls, fences, ruins and building parts are separate classes**, not
  "buildings". On Everon the loose filter swept in 26,610 walls. The footprint is an oriented rectangle from
  local bounds and transform.
- The report lists the top unclassified prefabs and materials, with counts, after every run.

---

## 4. Our own satellite images

**Primary: rendered by the engine, orthographic.**
1. The plugin loads the world, places a temporary `RMT_CaptureEntity` through the editor API (never saved), and
   calls `SwitchToGameMode()`.
2. In game mode the entity sets noon, clear weather and no fog (`SetTimeAndDate`, `SetWeatherState`, as
   `Screenshot_Autotest` does), and switches the camera to `ORTHOGRAPHIC`, looking straight down from above the
   highest terrain.
3. For each grid cell it moves the camera and waits for streaming and LODs to settle (frame count plus a minimum
   time). It then calls `MakeScreenshot` and writes `.ok`. Because it runs frame by frame in `EOnFrame`, the
   renderer actually draws between shots, which the Grok `Sleep()` approach could not do.
4. Resume works from `.ok` files. Heartbeats go to the log.
5. The Python side crops, color-balances, stitches and cuts the pyramid in the same `z/x/y.jpg` layout the site
   already uses (`z0` is the finest, 128 tiles a side on Everon, 50 m offset, scale 12.501). This keeps the site
   code unchanged except for removing the external fetch. It uses numpy and Pillow tile by tile, not pixel by pixel.

Sizes for Everon at 0.39 m/px (the current finest zoom): about 32,800 px square. That is about 1,100 captures at
1024 px, taking roughly 1 to 2 hours, and producing about 21,800 JPEG tiles (about 350 to 500 MB). At 0.2 m/px it
is 4 times that. The satellite tiles are outside the 2.5 GB budget, but they still have to fit on the VPS disk
(25 GB).

**Fallback: synthetic "satellite" from extracted data.** Terrain hillshade, ground color from surface material
(trace surface properties on a 2 m grid), forests from tree positions, and buildings and roads drawn on top. BI's
`ExportRasterization` shaded land/ocean image can be the base layer. It is fully deterministic and needs no GPU
tricks. We use it if Spike S3 shows that game-mode capture can't run unattended.

---

## 5. Validation (every run, automatic)

- Coverage: every chunk of every job has `.ok`. Terrain has no gaps or NaNs.
- Sanity: entity count matches the probe within tolerance. Building, tree and road counts are non-zero and
  within the expected density for the map's size.
- Roads: decals are dropped, every piece has 2 or more points, and a large share of road length joins one
  connected network. Every footpath end either joins something or is reported.
- Cross-check (if S2 is ever unblocked): our roads and buildings against BI's `MapDataExporter` output.
- Satellite: no black, blank or duplicate tiles, seam-color difference under a threshold, and every land tile
  present.
- **Everon regression:** compare against `everon-data/` and the current baked site data (same terrain values,
  same object counts, roads within tolerance of `roads.json`). This is how we know the new tool is at least as
  good as the old one.
- Size: bake total at 2.5 GB or less, excluding satellite, with a breakdown per layer.

---

## 6. Phases

| # | Phase | Output | Needs you? |
|---|---|---|---|
| 0 | **Spikes** (below) | yes/no answers + small sample files | once: Steam running, watch the first launch |
| 1 | Orchestrator + plugin skeleton: launch, heartbeat, watchdog, exit codes, manifest, `probe` job | `rmt.py run --job probe` works unattended | no |
| 2 | Extraction jobs: terrain, entities, roads, names, mapdata, surface | raw export of Everon | no |
| 3 | Satellite capture + pyramid | our own tiles for Everon | no |
| 4 | Bakers, generalized from the old tools (map size from the manifest, rules file) | site data folder + size report | no |
| 5 | Validation + Everon regression | `report.html` per run | review it |
| 6 | Site data contract (`site-data.md`): the files, formats and manifest the website reads | spec for the site rebuild (other chat) | yes |
| 7 | Arland and Kolguyev runs to prove "any map" (no per-map code allowed) | exports + reports | no |
| 8 | (later) foliage profiles, doors, power lines, POIs | | |

### Spikes (do these first; each could change the design)

- **S1 Headless launch.** Does `-gproj ... -wbModule=WorldEditor -plugin=RMT_ExportPlugin` run `RunCommandline`
  unattended? Does `SetOpenedResource` load Everon, and when is it finished? Does `Workbench.Exit` return the
  code? Where is the console log? Does it need Steam running? Are there any modal dialogs?
- **S2 BI map-data export.** Run `MapDataExporter.ExportData` for each type on Everon and see what it writes
  (format, coordinates, road types, building polygons). If the building polygons and forest areas are good, they
  replace a lot of our own classification.
- **S3 Satellite capture.** From a command-line plugin, switch to game mode, drive an ortho camera, and take 4
  shots over a known spot. Check timing, streaming, the resolution we get, and whether the screenshot contains
  only the 3D view (no editor UI).
#### Spike results (2026-09-29)

**S1 passed.** The launch that works:
`ArmaReforgerWorkbenchSteamDiag.exe -gproj <addon.gproj> -addonsDir "<repo>,<game>\addons,<tools>\Workbench\addons" -wbModule=WorldEditor -plugin=RMT_ExportPlugin -rmtJob=... -rmtOut=$profile:... -rmtWorld=...`
- The working directory **must** be the Workbench folder. Otherwise `./addons` resolves wrongly and a modal
  "Missing Addon" dialog blocks forever.
- `SetOpenedResource(world)` loads synchronously. `GetTerrainBounds` works. `Workbench.Exit(code)` reaches the
  process exit code. Steam was running.
- Load times and sizes (bounds in metres, heights min..max):

| World | Map | Load | Bounds | Heights | Editor entities |
|---|---|---|---|---|---|
| `worlds/Arland/Arland.ent` | Arland | 2.8 s | 4096 | −163..148 | 173,226 |
| `worlds/Eden/Eden.ent` | Everon | 9.8 s | 12800 | −205..376 | 1,235,821 (matches the old export) |
| `worlds/Cain/Cain.ent` | Kolguyev (internal name "Cain") | 10.0 s | 12800 | −205..699 | 1,427,512 |

- The `worlds` job (`Workbench.SearchResources(cb, {"ent"})`) lists every world Workbench can see: 103 in the
  base game. That can back a `rmt.py worlds` command.
- Each launch writes its own `logs/logs_<date>/console.log`. Our `RMT|` lines are in it.
- **Hard rule found:** script file writes outside the `$profile:` alias (into the addon folder, or by an
  absolute path even into the profile) pop a modal "Script Authorization Required" dialog that stalls the run.
  All output goes through `$profile:` only, and the orchestrator copies it out afterwards. The watchdog must also
  kill Workbench when a dialog appears (no log progress).

**S2 solved (later the same day).** The destination is a **folder given as an OS path**, not a file.
BI's own source (read from the game paks with `python -m rmtlib.pak cat scripts/WorkbenchGame/WorldEditor/SCR_WorldDataExportTool.c`)
shows the recipe: `Workbench.OpenModule(WorldEditor)`, `Sleep(300)`, then
`ExportData(Geometry2D, <dir>, <world>, 50, true)` and `SetupColors` + `ExportRasterization(<dir>, ...)`.
The `mapdata` job does this. On Arland it writes `Arland.topo` (1.2 MB) and `Arland.tga` (4096², a shaded
topographic map image) in 12 s. The `.topo` layout, as far as it is decoded:
- File: `TOPO` <u32 ver> <u32 size> <u32 end> <u32 0>, then sections with the same 20-byte header:
  `ROAD`, `PWLN`, `BULD`, `AREA`, `WATR`, `HILL`.
- `BULD` is decoded: <u32 5> <u32 n> then n × (<u32 k> k × (f32 x, f32 z)) footprint polygons, then
  <u32 m> m × (<u32 0> f32 x, f32 z, f32 dirx, f32 dirz) point symbols, then 32 zero bytes.
  Arland has 345 polygons and 178 point symbols.
- `HILL` is decoded: <u32 n> n × (u32, f32 height, f32 x, f32 z, u32, u32).
- `AREA` holds about 66k (x, z) points (forest outlines). How it splits into polygons is not decoded yet.
- `ROAD` and `WATR` are not decoded. Our own `roads` job already gives exact roads.

**S3 solved.** The pictures are taken in the **game itself** (`ArmaReforgerSteamDiag.exe -addonsDir ... -addons
<our GUID> -world <world> -rmtSat 1 -rmtOut=$profile:... -window`). A `modded class ArmaReforgerScripted`
(`OnWorldPostProcess`) spawns `RMT_SatCaptureEntity` when `-rmtSat` is given. Modelled on BI's `Screenshot_Autotest`,
the entity moves a `CameraBase` to each square, calls `BeginPreload` and waits for `IsPreloadFinished`, sets noon
and clear weather, calls `System.MakeScreenshot` (1920×1080 BMP) and writes a `.txt` with the camera. When done it
writes `satellite.status.json` and calls `RequestClose()`. On Arland, 9 shots took 56 s, unattended.
- **Orthographic renders black** in this build, so shots are perspective with a narrow lens (15°), from high
  enough that each 400 m square fills the frame over the highest ground. `rmtlib/satellite.py` corrects every map
  pixel using the exported terrain height and the exact pinhole camera, taking the nearest shot's centre. A 1 m/px
  test mosaic of a 1.2 km block with the exported roads drawn on top lines up exactly, with no visible seams.
- To tune: some blue haze from about 1.8 km up (fog off, a lower camera with a wider lens, or a colour
  correction).

Earlier S3 attempts, all black: command-line Workbench never draws the world (no window), in edit mode or in game mode.
- A plugin can drive frames with `Sleep()` (BI's WorldTestPlugin does this), and `SwitchToGameMode(false, true)`
  enters game mode in 0.2 s from the command line.
- In command-line Workbench, both edit mode and game mode give **black** `MakeScreenshotRawData` pictures, and
  `System.MakeScreenshot` writes no file. Workbench also crashed on exit after leaving game mode, though the job
  status had already been written.
- World entities must be defined in the Game script module, not WorkbenchGame. The editor never called
  `_WB_AfterWorldUpdate` in command-line mode.
- Next options: (a) run the real game client (`ArmaReforgerSteamDiag.exe`) with our addon, `-world <world>` and a
  game-side capture script that exits with `RequestClose`; (b) the synthetic fallback built from terrain,
  surface and BI's `.tga` raster.

**S2 first attempt (superseded):** `MapDataExporter.ExportData(Geometry2D, ...)` and `ExportRasterization(...)` return
`DataExportErrorNoOutputFile` instantly for every path and extension tried, even with the file already created.
The destination contract is undocumented. Our own extraction covers roads, buildings and trees, so this is
optional. We can revisit it later (for example with `SCR_WorldMapExportTool` from the GUI to see what it expects).

- **S4 Performance.** Time the terrain, entities and surface jobs on a few chunks and project them to the whole
  map, so we know how long a full run takes.

---

## 7. Size budget (2.5 GB, excluding satellite)

On Everon (164 km²) the baked data is about 0.16 GB for the field map, plus 3D extras. Data grows with map area,
so at the same detail:

| Map | Size | Area | Projected site data |
|---|---|---|---|
| Arland | ~4 km | 16 km² | ~0.02 GB |
| Everon | 12.8 km | 164 km² | ~0.2 GB |
| Kolguyev | ~12.8 km | ~164 km² | ~0.2 GB |
| Big community map | 20 km | 400 km² | ~0.5 GB |
| Budget limit | ~40 km | ~1,600 km² | 2.5 GB |

The baker still enforces it. If a map would go over, it lowers the Full-LOS resolution for that map (0.5 m to
1 m, a quarter of the size) and says so in the report. Raw exports (GBs) stay on your PC and are never uploaded.

---

## 7b. Foliage (reviewed and automated 2026-09-29)

- **Rays can't replace the photos.** The `foliagetrace` job fired level rays through 280 plants of all 70 Everon kinds
  with every ray setting: all layers, `TraceFlags.VISIBILITY`, and the `Foliage`, `ViewGeometry` and `Vegetation`
  layers. They only ever hit trunks and branches: about 18% of the plant's box, correlation 0.37 with photo cover.
  `ViewGeometry` and `Vegetation` hit nothing. Prefabs have no density setting either. (Rays are probably what the AI
  uses, so ray line of sight is closer to what the AI sees and photo line of sight to what a player sees.)
- **Review of the old photos:** 16 sides was more than needed (side-to-side spread 0.06; 8 sides lands within
  0.008). The resolution was fine. The low slices were partly shot against distant land (about 70% sky behind the
  plant), which under-counted cover a little.
- **New capture** (`Scripts/Game/RMT/RMT_FoliageCapture.c`, the `foliage` job): in the game, on `EmptyArland`, with
  the plant 60 m up and the camera low enough that the plant's base is 5° above the horizon, so 100% of what is behind
  the plant is sky. Per plant: 8 sides close up, 1 view straight up from below (crown against the sky), and 8 sides
  at each of 25, 50, 100, 200 and 300 m (500 m and 150 m dropped to save time; the profile interpolates between the distances kept). That is 49 views, each a with/without pair, about 100 s per plant.
  The photos are converted to lossless PNG as they arrive (about 1 MB instead of 6.2 MB).
- **Distance matters:** the game swaps in simpler, denser models at range. A tall spruce reads 0.56 close up,
  0.79 at 150 m and 0.84 at 300 m; a hazel reads 0.59 close up, 0.68 at 200 m and 0.78 at 500 m. `foliage_profiles.json`
  therefore has `bands` (cover and k per 0.5 m slice at each distance, plus a pixel count as a confidence measure) for
  the line-of-sight tool to interpolate by viewer distance. Beyond about 200 m small bushes cover only a few pixels,
  so their numbers are rough there (see `px`).
- Plant lists come from each map's own entities export, so Kolguyev's seasonal variants (snowy spruce, autumn birch)
  get measured.

## 8. Risks and open questions

- **S1/S3 unknowns.** Workbench might show a dialog, or need focus to render, in which case the satellite job needs
  the fallback. That is why the spikes come first.
- **Game updates** can rename classes or materials. The run manifest records the game build, and the
  unclassified report shows what changed.
- **Mod maps:** they need the map's addon available locally (Workshop download). The temp `.gproj` adds its GUID.
- **Content rules:** everything is derived from Bohemia's game data, including the rendered satellite images.
  Check BI's content and licensing rules before hosting publicly (the site README already notes this).
- The website itself has to be rebuilt to read the new data. Phase 6 produces the spec for that.

## 9. Decisions (2026-09-29)

1. Satellite resolution: about 0.39 m/px, the same as today's finest zoom.
2. The user points the program at any world file (`--world <resource or .ent path>`); there is no built-in map
   list. Test maps are Everon, Arland and Kolguyev, but nothing may depend on them.
3. `everon-3d` is out of scope for now. Don't read from it or write to it.
4. Doors, power lines and POIs: later (phase 8).
