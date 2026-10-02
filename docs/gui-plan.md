# Plan: a desktop GUI for Reforger Map Tools

Status: a first version is built ([gui.md](gui.md)). Done: phase 1 (engine API: `paths`, `events`, `--events`,
`--workspace`, `run`, `detect`, the addon index), the window for phases 2 to 4 (Setup, World, Data, Run, Runs),
phase 6 (Labs: fire, blast and rocket tests, audibility, game files, self-tests) and a double-click launcher
(`Reforger Map Tools.bat`, which makes `.venv\`) in place of packaging for now.
Not done: a live run from the window, packaging (phase 5).
Changed from the plan: world listing reads the addons' resource databases instead of starting Workbench; errors stay
`SystemExit` messages but become `error` events with `--events` (no `RmtError` classes yet); everon-3d-map was merged
into arma-map, so `viewer3d` below is now part of `fieldmap`.

## 1. Goal

A program people run on their own PC (a native window, not a web page) that:

1. finds Arma Reforger, Arma Reforger Tools, Steam and the user's mods by itself;
2. lists the worlds it can see (base game and mods) and lets the user pick one, or browse to a `.ent`;
3. lets them choose *what data they want* in plain terms (roads, line of sight, place names, satellite, trees, ...)
   and works out which export jobs and bakes that needs;
4. runs it unattended, with real progress, cancel and resume;
5. writes the result to a folder the user chose, in the layout arma-map and the 3D viewer already read.

Out of scope for v1: Linux or macOS (Workbench and Steam paths here are Windows-only), `firetest.py`, `blasttest.py` and
`audible/` (Everon-specific research tools, see section 9), editing arma-map's own code.

## 2. Recommendations

| Decision | Recommendation | Why |
|---|---|---|
| Platform | Windows only | `steam.py` reads the registry; Workbench and the game are Windows builds here |
| Toolkit | **PySide6 (Qt)** | The whole engine is Python. Qt gives real tables, a log view, process handling and a normal-looking app. Tkinter works but is clumsy for a live log and a pipeline view. Electron and Tauri are browser engines, which you ruled out. A .NET rewrite would mean porting every baker |
| Relationship to the CLI | **GUI is a thin front end over the CLI.** The GUI starts `rmt` as a child process and reads a stream of JSON events from it | One engine to maintain and test. A hung Workbench or a crash in a baker cannot freeze or kill the window. Cancel is "kill the process tree", which `workbench.py` already does on a stall |
| Packaging | PyInstaller one-folder build plus a zip or Inno Setup installer; the same exe re-launches itself as the worker (`rmt.exe --worker ...`) | No Python install for users. Expect roughly 150 to 250 MB with Qt, numpy and Pillow |
| Where data goes | User-chosen **workspace folder** (default `Documents\ReforgerMapTools`) | The install folder may be read-only. Today everything is under the repo (`out/`, `.build/`) |

## 3. What stops the code being a library today

These are the changes needed in `rmtlib` before any GUI is useful. Most are small.

| # | Problem in the code today | Change |
|---|---|---|
| 1 | `REPO` (in `workbench.py`) is the repo folder; exports go to `REPO/out`, the addon is built into `REPO/.build`, `worlds.txt` lives in `REPO/out` (`export.py` lines 53, 91) | A `Paths` object (workspace, addon build dir, bundled addon source) passed in. Default is the old repo layout so the CLI behaves as before. Bundled `addon/Scripts` become a resource of the frozen app |
| 2 | Errors are `SystemExit("message")` in `steam.py` and `export.py` | A small `RmtError` hierarchy (`NotInstalled`, `WorldNotFound`, `WorldDidNotLoad`, `JobFailed`, ...) with a message and a hint. The CLI prints it and exits; the GUI shows it |
| 3 | Progress is `print`. `export` and the bakers take `log=print` in places only | One `emit(event)` function. Default prints the same text as now; with `--events jsonl` it prints JSON lines (section 4) |
| 4 | No cancel | A cancel flag checked in the supervise loop and between bakes. Hard cancel is killing the child process, so soft cancel is only needed in bakers |
| 5 | `fieldmap.MAP_IDS`, `viewer3d.MAPS`, `viewer3d.FIELD_REFERENCE` and `tuned_colours` are hard-wired to Everon, Kolguyev and Arland | Take a map descriptor (id, title, camera start) from the caller; keep the three as defaults. See section 7 for the arma-map side |
| 6 | Sibling-folder guesses: `..\..\arma-map\everon-map`, `..\everon-3d-map` | Remember the folders the user picks (settings file). Keep the guesses as first suggestions |
| 7 | Workbench writes raw output only under its profile (`$profile:`, a hard rule: any other path pops a modal dialog) | Keep raw output there; the workspace holds manifest, site and a copy or link of what is needed. Spike: does `-profile <dir>` work for Workbench and the game? If yes, raw output can go straight to the workspace |
| 8 | The game-side jobs change the game's video settings and restore them afterwards | Back the settings file up on start and restore on next app launch if a run died (the GUI is more likely to be killed than a terminal) |
| 9 | `export.py` is one long procedure for all jobs | Add a `plan(world, products)` function that returns the ordered steps (jobs, then bakes) without running anything, so the GUI can show it, estimate it and tick it off |

## 4. Architecture

```
 +-----------------------------+            JSON lines on stdout
 |  GUI (PySide6, one process) |  <------------------------------+
 |  screens, settings, history |                                  |
 +--------------+--------------+                                  |
                | starts / kills                                  |
                v                                                 |
 +-----------------------------+        +---------------------------+
 |  worker: rmt.exe --events   | -----> |  Workbench / the game     |
 |  plan -> export -> bake     | <----- |  (log heartbeat, status)  |
 +-----------------------------+        +---------------------------+
        uses rmtlib (unchanged logic)
```

Event lines (all have `t` for the kind and a timestamp):

```
{"t":"plan","steps":[{"id":"export:probe"},{"id":"export:terrain"},{"id":"bake:los"}, ...]}
{"t":"step","id":"export:terrain","state":"start"|"done"|"failed"|"skipped"}
{"t":"progress","id":"export:terrain","done":120,"total":324,"unit":"chunks"}
{"t":"log","level":"info","text":"..."}
{"t":"need","what":"close Workbench"}          # a user action is required
{"t":"error","code":"WorldDidNotLoad","message":"...","hint":"..."}
{"t":"done","ok":true,"site":"...","seconds":1234}
```

Progress totals come from what already exists: the chunk grid is known after `probe`, `RMT|chunk|` lines give done
counts, and the satellite and foliage grids are computed before launch. The existing heartbeat, `.status.json` files
and `.ok` markers are what make cancel and resume work; the GUI adds nothing to them.

## 5. Detecting the game ("generalised")

A **Setup** screen runs these checks and shows each as found, missing or manual override, with the fix from
`docs/troubleshooting.md`:

| Check | How (mostly in `steam.py` already) |
|---|---|
| Steam installed and its libraries | Registry plus `libraryfolders.vdf` |
| Arma Reforger (app 1874880), build id | `appmanifest` in each library |
| Arma Reforger Tools (app 1874910), build id, Workbench exe | same; exe path is `Workbench\ArmaReforgerWorkbenchSteamDiag.exe` |
| Documents folder (may be on OneDrive) | registry, as today |
| Workbench and game profile and log folders | derived |
| Workshop mods and local addons | `workshop` folder and `Documents\My Games\ArmaReforger\addons` |
| Steam running; Workbench or the game running | process list. The run is blocked, with a clear message, if Steam is not running or either engine is open |
| Disk space in the workspace | free space against the estimate for the chosen products |
| Display needed for game jobs | warn that satellite and foliage open the real game on screen |

A "Browse" button on every row for non-standard installs. A **Copy diagnostics** button bundles these results, build
ids and the tail of `console.log` for bug reports.

## 6. Screens

1. **Setup** (first run, and a tab afterwards): the checks above.
2. **World**: table of worlds (name, where it comes from: base game or which mod, map size once known). Filled by the
   existing `worlds` job (a few seconds, cached; Refresh button) plus a scan of mod addon folders. "Browse for .ent".
3. **Data**: tick *products* rather than jobs (section 8). Shows what each needs, an estimated time and disk size,
   and presets: *Quick test* (2 chunks, `--max-chunks 2`), *Field map data*, *Everything*. Advanced expander for
   `--set` values (SatSpan, FoliageSides, Step, tile size, region).
4. **Destination**: the workspace folder; optional "install into" targets: arma-map's field map folder and the 3D
   viewer folder, with map id and title for a new world (section 7).
5. **Run**: a step list (the plan) with a live state per step, a progress bar with elapsed and a rough remaining time
   once the first chunks are timed, the log below, **Cancel** and **Open output folder**. Banners when the game is
   about to take over the screen, and when a step needs the user ("close Workbench"). Everything is resumable, so
   Cancel is safe and the button after it is "Resume".
6. **Results**: what was written, sizes, the accuracy score if `check` was run, **Open folder**, **Zip for sharing**.
7. **Runs**: every export found under the workspace (world, game build, state, size), with *Resume*, *Re-bake only*
   (after a baker changed) and *Delete raw data*.

## 7. The arma-map side (needs a decision)

`fieldmap` and `viewer3d` work for the three known maps. A new map needs two more things on the website side that the
GUI can not safely do by editing code:

- arma-map keeps its map list in `static/app.js` and `server.py` (`MAPS`). The 3D viewer has `data/maps.json`
  (already written by `viewer3d.install`).
- Proposal: the GUI writes a small `map.json` (id, title, world, size, tile, start, hasTrees, source build) into
  each map's data folder, and arma-map reads its map list from the folders it finds. That is a change in the
  arma-map repo, not here. Until then the GUI shows the exact lines to paste.

## 8. Data products and what they run

User-facing choice, mapped to the existing jobs and bakes. The planner adds dependencies automatically.

| Product | Export jobs | Bake | Runs in | Rough time (from the docs) |
|---|---|---|---|---|
| Map basics | `probe` | | Workbench | seconds (Arland about 3 s) |
| Roads | `mapdata` (and `roads` as a fallback source) | `roads` | Workbench | minutes |
| Terrain, objects, line of sight | `terrain`, `entities`, `surface` | `los` | Workbench | `surface` is the slowest job; time Arland first |
| Place names | `names` | `places` | Workbench | minutes |
| Satellite imagery | `satellite` | `satellite` | **the game** | Arland 9 shots about 1 minute; Everon about 1,100 shots, 1 to 2 hours |
| Trees and foliage | `foliage` (photos) or the profile library (see the foliage review) | `foliage`, `plants` | **the game** | about 100 s per plant kind, about 70 kinds on Everon |
| Accuracy check (optional) | `sightlines` | run `check` | Workbench | seconds to fire the lines |
| Install into field map / 3D viewer | | `fieldmap`, `viewer3d` | | minutes |

Dependencies: `plants` needs `los` and `foliage`; `satellite` bake needs the terrain export; `foliage` photos need
`entities` (the plant list comes from the map's own entities); `viewer3d` needs `los`, `foliage`, `plants` and the
raw `objects/`.

## 9. firetest, blasttest and audible

These are Everon research tools: `firetest.py` and `blasttest.py` each need a live game run (`blasttest.py` on
`EmptyEden`, about 15 to 20 minutes) and the arma-map site data for Everon's terrain, and `audible/` reads sound
files and needs numpy and scipy. `blasttest.py` also imports `firetest.py` and reads the game's
`resourceDatabase.rdb` to find prefab GUIDs, so it only works with both files together. Put them under an **Advanced / Labs** tab in a later phase, as launchers with
their own pages, or leave them as scripts. Not needed to "extract map data for arma-map".

## 10. Phases

Each phase ends with something you can run and check.

| Phase | Work | Done when |
|---|---|---|
| 0. Spikes | (a) does `-profile` redirect raw output? (b) does the frozen exe re-launch itself as a worker and start Workbench from it? (c) the foliage spike in `foliage-opacity-review.md` | answers written down |
| 1. Engine API | `Paths`, `RmtError`, `emit()` events, `--events jsonl`, `plan()`, cancel, settings file. No GUI | the CLI behaves as before and `rmt.py export Arland --events jsonl` produces a clean event stream |
| 2. Detect and list | Setup screen and World screen | a fresh PC shows the right installs and the world list, and a wrong install shows the right fix |
| 3. Run | Data, Destination and Run screens; plan, progress, cancel, resume | Arland quick test from the window, killed half way and resumed |
| 4. Results and installs | Results and Runs screens, `fieldmap` and `viewer3d` with map descriptors, zip for sharing | an Arland bake lands in arma-map and the viewer from the window |
| 5. Package | PyInstaller build, installer, first-run experience, diagnostics bundle | a person who has never seen the repo extracts Arland on their own PC |
| 6. Labs | firetest and audible pages (optional) | |
| Later | foliage without photos, per the review | |

## 11. Risks and unknowns

- **Workbench and the game are fragile to automate.** The known hazards (modal dialogs, black renders, wrong working
  directory, one export per game build) are in `docs/troubleshooting.md`. The GUI must keep the stall watchdog and
  show *which* hazard fired.
- **Game jobs take over the screen** for hours. The Run screen has to say so before it starts.
- **Game updates** change the build id, so a run is tied to a build and old exports are kept, not reused. The Runs
  screen shows the build per run.
- **Mod maps** that depend on other mods need those addons' GUIDs on the command line. `export.py` adds the world's
  own addon; I did not check whether that addon's own dependencies are also added, so test a real mod map early.
- **Untested code paths.** The `sightlines` job has not been run in Workbench yet (per `troubleshooting.md`).
- **Licensing** of Qt for Python (LGPL) and of anything in the installer: check before publishing.
- Nothing here has been run; estimates come from the numbers already written in these docs.

## 12. What I need from you

1. OK to go Windows-only with PySide6 and "GUI over the CLI"?
2. Who are the users: you and your group (so a zip is enough), or the public (needs an installer and support)?
3. Is a change to arma-map to read its map list from the data folder acceptable (section 7)?
4. Is v1 "extract data and install into arma-map" enough, with firetest and audible left as scripts?
