# The addon (`addon/`)

Enforce script that runs inside Workbench and the game. You never launch it by hand: `rmt.py` builds a fresh copy
into `.build/ReforgerMapTools/` on every run (a `.gproj` depending on the game, plus the map's own addon GUID for a
mod map) and starts the engine on it. Edit `addon/`, never `.build/`. `addon.gproj` and `resourceDatabase.rdb` in
`addon/` are not used by the build (the `.rdb` is ignored by git).

## Files

| File | Module | Role |
|---|---|---|
| `Scripts/WorkbenchGame/RMT/RMT_ExportPlugin.c` | WorkbenchGame | The plugin. Reads the command line, loads the world, runs the jobs in order, returns the exit code. Also holds the `probe`, `mapdata` and `worlds` jobs. |
| `Scripts/WorkbenchGame/RMT/RMT_Context.c` | WorkbenchGame | Shared state: arguments, the loaded world, terrain bounds, chunk grid, region and chunk limits; `.ok` markers; status files; one-level-at-a-time folder creation. Also the base class of the chunk jobs. |
| `Scripts/WorkbenchGame/RMT/RMT_GridJobs.c` | WorkbenchGame | Chunk jobs: `terrain`, `entities`, `surface`. |
| `Scripts/WorkbenchGame/RMT/RMT_WorldJobs.c` | WorkbenchGame | Whole-world jobs: `roads`, `names`. |
| `Scripts/WorkbenchGame/RMT/RMT_FoliageTrace.c` | WorkbenchGame | The `foliagetrace` experiment. |
| `Scripts/WorkbenchGame/RMT/RMT_BallisticsJob.c` | WorkbenchGame | The `ballistics` job ([firetest.md](firetest.md)). Accepted by the plugin but not listed in `rmt.py`. |
| `Scripts/Game/RMT/RMT_GameHook.c` | Game | When the game starts with `-rmtSat`, `-rmtFoliage` or `-rmtFire`, spawns the matching entity once the world is ready. |
| `Scripts/Game/RMT/RMT_SatCapture.c` | Game | The satellite capture entity. |
| `Scripts/Game/RMT/RMT_FoliageCapture.c` | Game | The foliage photograph entity. |
| `Scripts/Game/RMT/RMT_FireTest.c` | Game | The mortar firing test entity, driven by `firetest.py` ([firetest.md](firetest.md)). |

World entities must live in the **Game** script module, not WorkbenchGame (the editor never ran `_WB_AfterWorldUpdate`
in command-line mode, and entities defined in WorkbenchGame were not found).

## Command line

Workbench is started as:

```
ArmaReforgerWorkbenchSteamDiag.exe -gproj <.build addon.gproj> -addonsDir "<.build>,<game>\addons,<tools>\Workbench\addons[,<workshop addons>][,<map addon folder>]"
    -wbModule=WorldEditor -plugin=RMT_ExportPlugin -rmtJob=<job>[,<job>...] -rmtOut=$profile:<folder>
    [-rmtWorld=<resource>] [-rmtTile=500] [-rmtStep=<m>] [-rmtRegion=tx0,tz0,tx1,tz1] [-rmtMaxChunks=N] [...]
```
The working directory **must** be the Workbench folder (otherwise `./addons` resolves wrongly and a modal "Missing
Addon" dialog blocks forever). `rmt.py` does this.

| Argument | Meaning |
|---|---|
| `-rmtJob` | One job or a comma list: `probe`, `mapdata`, `roads`, `names`, `entities`, `terrain`, `surface`, `foliagetrace`, `ballistics`; or `worlds` on its own. Unknown name: exit 2 before anything is loaded. |
| `-rmtOut` | Output folder, always `$profile:<relative path>`. Required. |
| `-rmtWorld` | World resource (`{GUID}worlds/.../x.ent`). Required for every job except `worlds`. |
| `-rmtTile` | Chunk size in metres (default 500, minimum 10). |
| `-rmtStep` | Sample spacing for `terrain` (default 1) and `surface` (default 0.5), minimum 0.25. |
| `-rmtRegion`, `-rmtMaxChunks` | Chunk window (inclusive) and a cap on new chunks per job; for tests. |
| `-rmtFtPerKind` | `foliagetrace` plants per kind. |

The game is started as:

```
ArmaReforgerSteamDiag.exe -addonsDir "<same list>" -addons <our GUID>[,<map addon GUIDs>] -world <resource>
    -rmtSat 1 | -rmtFoliage 1 | -rmtFire 1  -rmtOut=$profile:<folder> -window -nosplash  [-rmtSat... | -rmtFoliage... | -rmtFireSettle=<s>]
```
(`-window` is replaced by a forced screen size when `FoliageWidth/Height/Mode` are used.) The game-side settings are
listed in [export-jobs.md](export-jobs.md).

## How the pieces talk

- **Heartbeat.** Scripts print `RMT|<message>` lines (`start`, `opened`, `world`, `begin|<job>`, `chunk|...`,
  `end|<job>|<code>`, `exit|<code>|<label>`). `rmt.py` tails the launch's `console.log` for them. No such line for
  `--stall` seconds means a dialog or a hang and the process is killed.
- **Status files.** Each job ends by writing `<out>/<job>.status.json`:
  `{"job", "result": "done"|"partial"|"failed", "made", "skipped", "remaining", "items", "ms"}`. `rmt.py` deletes them
  before each launch, and trusts nothing older.
- **Chunk files.** A chunk is finished only when `<file>.ok` exists; it is written after the data file is closed. A
  rerun skips finished chunks.
- **Exit code.** `Workbench.Exit(code)` reaches the process exit code: 0 done, 1 job failed, 2 bad arguments, 3 world
  did not load.
- **Game jobs** have no exit code worth reading (the game is closed with `RequestClose`); the status file is what counts.

## Writing a new job

1. Add a class with a `Run()` returning 0 on success; for per-chunk work extend the chunk-job base class in
   `RMT_Context.c` (see `RMT_TerrainJob` in `RMT_GridJobs.c` for the smallest example).
2. Write only under `m_Ctx.m_sOut` (which is `$profile:`), create folders with `RMT_Context.MakeDirs`, call
   `m_Ctx.WriteStatus(...)` at the end, and print `RMT|...` lines often enough to be a heartbeat.
3. Add the name to the allowed list and to `RunJob` in `RMT_ExportPlugin.c`, and to `JOBS`/`ALL_JOBS` in
   `rmtlib/export.py` so `--jobs` accepts it.
4. Test on Arland with `--max-chunks 2` first.

The Workbench API docs are in the Tools install (`Workbench/docs`). BI's own scripts, for reference, can be read with
`python -m rmtlib.pak cat <path>` (see the README).
