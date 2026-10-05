# `addon/`: Enforce scripts for Workbench and the game

Everything here is Enforce Script that runs **inside** Arma Reforger Workbench or the game. You do not start it by
hand: `rmt.py` copies `Scripts/` into `.build/ReforgerMapTools/`, writes a `.gproj` for it, and launches the engine.
Edit the files here, never the copy in `.build/`. The user-level explanation of the command line, status files and
heartbeat is in [../docs/addon.md](../docs/addon.md); this file is a reading guide to the code.

Only `Scripts/` is copied into the build; the runner generates its own `addon.gproj`. The checked-in
`addon.gproj` is not used for automated launches. For the Python side of the contract, see
[../docs/code-guide.md](../docs/code-guide.md).

## Two script modules, on purpose

| Folder | Module | Why |
|---|---|---|
| `Scripts/WorkbenchGame/RMT/` | WorkbenchGame | Runs in Workbench only: the plugin and the export jobs |
| `Scripts/Game/RMT/` | Game | Runs in the real game: the capture and test entities |

World entities (things placed in a world, with frame events) must be defined in the **Game** module. Entities in
WorkbenchGame were not found, and the editor never ran `_WB_AfterWorldUpdate` in command-line mode.

## `Scripts/WorkbenchGame/RMT/`

| File | Classes | What it does |
|---|---|---|
| `RMT_ExportPlugin.c` | `RMT_ExportPlugin` (a `WorkbenchPlugin`) | Entry point `RunCommandline`. Reads `-rmtJob`, loads the world, runs each job in order with `begin\|` / `end\|` heartbeats, and calls `Workbench.Exit(code)`. Also implements `probe` (writes `probe.json`), `mapdata` (BI's `MapDataExporter`: geometry plus raster into a folder given as an OS path) and `worlds` (lists every `.ent`). `RunJob` is the dispatch table: add new jobs there. |
| `RMT_Context.c` | `RMT_Context`, `RMT_ChunkJob` | Shared state and helpers. `Init` reads the arguments, `OpenWorld` loads the world and the terrain bounds and computes the chunk grid, `MakeDirs` creates folders one level at a time, `ChunkDone` / `MarkOk` handle `.ok` markers, `WriteStatus` writes `<job>.status.json`, `Say` prints an `RMT\|` line. `RMT_ChunkJob` is the base class of the per-chunk jobs: it walks the chunk grid (honouring `-rmtRegion` and `-rmtMaxChunks`), skips finished chunks and reports `done`, `partial` or `failed`. |
| `RMT_GridJobs.c` | `RMT_TerrainJob`, `RMT_EntitiesJob`, `RMT_SurfaceJob` | The chunk jobs. Terrain: `GetSurfaceY` on a grid. Entities: `QueryEntitiesByAABB`, entities owned by the chunk containing their origin. Surface: rays over every spot an object covers. The file header documents each CSV format. |
| `RMT_WorldJobs.c` | `RMT_RoadsJob`, `RMT_SightLinesJob`, `RMT_NamesJob`, `RMT_ConflictJob` | Whole-world jobs. Roads: every `RoadEntity` plus spline shapes. Sight lines: random engine rays for `rmt.py check`. Names: map-descriptor settings. Conflict: scenario entities and game-mode component settings for `conflict.py`. |
| `RMT_FoliageTrace.c` | `RMT_FoliageTraceJob` | The `foliagetrace` experiment (rays through plants). Not part of the pipeline. |
| `RMT_BallisticsJob.c` | `RMT_BallisticsJob` | The `ballistics` job: engine shell-flight table into `ballistics/sim.csv`. See [../docs/firetest.md](../docs/firetest.md). |

### Job pattern
A job is a class with `Run()` returning 0 on success. A chunk job subclasses `RMT_ChunkJob` and overrides
`WriteChunk(tx, tz, path)` to write one chunk's file. Every job writes only under `m_Ctx.m_sOut` (a `$profile:` path), ends with `m_Ctx.WriteStatus(...)`,
and prints `RMT|` lines often enough that `rmt.py` can see it is alive.

## `Scripts/Game/RMT/`

| File | Classes | What it does |
|---|---|---|
| `RMT_GameHook.c` | `modded class ArmaReforgerScripted` (overrides `OnWorldPostProcess`) | Checks the command line for `-rmtSat`, `-rmtFoliage`, `-rmtFire`, `-rmtGun`, `-rmtBlast` or `-rmtLauncher` and spawns the matching entity. Without the flag it does nothing, so the addon is harmless in a normal game. |
| `RMT_SatCapture.c` | `RMT_SatCaptureEntity` | Moves a `CameraBase` to each grid square, preloads, waits, sets noon and clear weather, takes the screenshot and writes `s_<col>_<row>.txt`. Frame-driven (`EOnFrame`), never blocks. Writes `satellite.status.json` and requests close. |
| `RMT_FoliageCapture.c` | `RMT_FoliageCaptureEntity` | Reads `plants.csv`, photographs each plant (shown and hidden) from sides, below and several distances, appends `shots.csv`, skips plants already done, writes `foliage.status.json`. |
| `RMT_FireTest.c` | `RMT_FireTestEntity` | Reads `plan.csv`, fires real mortar shells with `ProjectileMoveComponent.Launch`, follows each to impact, sets and settles the wind, writes `shots.csv` and `traj.csv` and `firetest.status.json`. Driven by `../firetest.py`. |
| `RMT_GunTest.c` | `RMT_GunTestEntity` | Reads `plan.csv`, places a real mortar, lays it by turning and tilting the gun until the barrel reads the planned numbers, loads a shell with the planned charge into the barrel and fires it through the weapon, follows it to impact, writes `shots.csv` and `guntest.status.json`. Driven by `../firetest.py gun`. |
| `RMT_BlastTest.c` | `RMT_BlastTestEntity` | Reads `plan.csv` and `layout.csv`, stands riflemen around each aim point, drops a real shell on it, records every soldier into `hits.csv` and the burst into `bursts.csv`, clears up, writes `blasttest.status.json`. Driven by `../blasttest.py`. |
| `RMT_LauncherTest.c` | `RMT_LauncherTestEntity` | Reads `plan.csv`, spawns the game's AT soldiers on cliffs, zeroes, raises and aims the launcher (aiming angles corrected until the bore holds the planned numbers), records bore and sights, fires, follows the rocket, writes `shots.csv`, `traj.csv` and `launchertest.status.json`. Driven by `../launchertest.py`. |

## Rules that bite

Python's regression suite does not compile Enforce Script. After changing these scripts, verify compilation and
the affected job in installed Tools/the game, starting with a small region or limited plan. Game capture and
live-fire jobs open the game on screen.

- Script file writes outside `$profile:` raise a modal "Script Authorization Required" dialog that stalls the run.
- A `Resource` or file path that contains a GUID prefix (`{...}`) must be kept whole.
- Do not call `Sleep()` in game entities and expect a render: shots are taken from frame events, because the renderer
  only draws between frames.
- Keep arguments' names in step with `rmtlib/export.py` (settings are passed as `-rmtNAME=VALUE`).
- Compile errors show up in the engine log as `SCRIPT (E)`; `rmt.py` treats a compile error as fatal and does not retry.

## Reference
The Workbench script API docs are in the Tools install (`Workbench/docs`). BI's own scripts for patterns:
`python -m rmtlib.pak cat scripts/WorkbenchGame/WorldEditor/SCR_WorldDataExportTool.c` (the model for `mapdata`),
`scripts/GameLib/entities/autotest/Screenshot_Autotest.c` (the model for the captures).


`Scripts/WorkbenchGame/RMT/RMT_MortarTablesJob.c` implements the `mortar_tables` dispatch. It reads the
profile-relative CSV supplied by `-rmtMortarPlan`, samples native ballistic pages for each shell/charge and
writes table rows plus completion status. `webdata.py mortar` prepares and checks the plan/results. A real
Workbench run verified compilation and all 31 vanilla configurations (417 rows) on 2026-10-05.
