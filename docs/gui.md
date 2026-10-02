# The desktop app (`rmt_gui.py`)

A window over the same tools: pick a world, tick the data you want, choose a folder, press Start. Status: first
version, built from [gui-plan.md](gui-plan.md) phases 1 to 4. The window itself has not been opened yet (PySide6 was
not installed when it was written); the engine side it drives was checked without launching Workbench (see "What has
been tested").

```bash
pip install -r requirements.txt     # numpy, Pillow, PySide6
python rmt_gui.py
```

Windows only, like the rest of the tools. Steam must be running; Workbench and the game must be closed.

## Pages

| Page | What it does |
|---|---|
| **Setup** | Checks this PC (`rmtlib/detect.py`): Steam, the game and the Tools with their build ids, Workbench, the Documents folder (OneDrive-aware), the Workbench profile, Workshop mods, whether Steam is running and Workbench and the game are closed, free disk space, numpy and Pillow. Each problem says how to fix it. A Workbench path can be set by hand. |
| **World** | Every world in the game and your downloaded mods, read from the addons' own `resourceDatabase.rdb` (`rmtlib/addons.py`), so Workbench isn't started. By default only each terrain's base world (`Arland`, `EmptyArland`, `Cain`, `Eden`, ...) and every mod world; *Show every world* lists the game modes and tools too. *Use a .ent file on disk* takes a world from your own project. |
| **Data** | What to make, in plain terms (`rmtlib/products.py`): roads, terrain/objects/line of sight, place names, satellite imagery, trees and foliage, the accuracy check. What each needs is added on its own and shown. *Quick test* runs 2 chunks per job. The **output folder** is where manifests and site data go. *Also install into the field map* runs `rmt.py fieldmap` at the end (folder holding `server.py`, and the map's id on the site). *Advanced*: chunk size, stall timeout, launches per job, and `--set` job settings. |
| **Run** | The plan as a step list, each step's state and progress from the engine's heartbeat (chunks, shots, plants, with a rough time left), the full log, elapsed time, **Cancel**, **Open output folder**, **Save log**. |
| **Runs** | Every export in the output folder: world, game build, which jobs finished, what is baked. *Open folder*, *Open raw export*, *Bake again* (the parts its finished jobs allow), *Install into field map*. |

Settings (last world, products, folders) are kept between sessions (`QSettings`, in the registry under
`HKCU\Software\ReforgerMapTools`).

## How it works

```
rmt_gui.py (window, rmtgui/app.py)
   |  starts, reads JSON lines, kills on Cancel
   v
rmt.py --events --workspace <output folder> run <world> --products ... [--install ...]   (rmtgui/worker.py)
   |  export jobs, bakes, check, install: the same code as the command line
   v
Workbench / the game   (heartbeat RMT| lines in console.log -> progress events)
```

- The window never runs an export itself. The worker is a child process, so a hung Workbench can't freeze the window,
  and **Cancel** kills the worker and everything under it (`taskkill /T`). Every job resumes: run the same thing again
  and finished jobs and chunks are kept.
- `rmt.py --events` prints JSON lines (`rmtlib/events.py`): `plan`, `step`, `progress`, `log`, `error`, `result`,
  `done`. Without `--events` the command line prints exactly what it did before.
- `rmt.py --workspace <folder>` replaces `out/` for manifests and site data (`rmtlib/paths.py`). Raw export data stays
  in the engine's profile folder (`Documents\My Games\ArmaReforgerWorkbench\profile\rmt\...`, and the game's profile
  for satellite and foliage): the engine's scripts may only write there.
- If a foliage run is killed while the game's screen settings are changed, the original settings are saved in
  `<game profile>\rmt\video-settings-backup.json` first and put back the next time the app starts or a game job
  runs (`restore_video_settings` in `rmtlib/workbench.py`).

## New command-line pieces (usable without the window)

```bash
python rmt.py detect                                       # the Setup page's checks, as text
python rmt.py run Arland --products roads,los --max-chunks 2
python rmt.py run Eden --products roads,los,places,foliage --install --to ..\..\arma-map\everon-map --as everon
python rmt.py --workspace D:\maps run Cain --products los
python rmt.py --events detect                              # JSON lines, as the app reads them
```

`run` = the export jobs the products need, then the bakes, then `check` and the install if asked. A world name now
resolves through the addons' resource databases first (instant, and a Workshop map brings the GUIDs of its mod and the
mods it depends on), then through `out/worlds.txt` as before.

## What has been tested, and what hasn't

Checked on this PC without launching Workbench or the game:
- every new and changed file compiles; `rmt.py --help` and `rmt.py detect` work, and `detect` saw the game running;
- world lookup gives the same worlds and slugs as before (`Arland` -> `arland-a9806a`, `Eden` -> `eden-853e92`,
  `Cain` -> `cain-1ea95d`), and the default world list is the six base terrains;
- product plans add their dependencies (trees add the line of sight; install adds roads, line of sight, places and
  trees);
- heartbeat lines turn into the right progress events;
- `--events` turns errors into `error` and `done` events.

Not yet tested:
- the window itself (PySide6 wasn't installed);
- a real `run` through Workbench;
- Cancel during a live run;
- mod maps: whether loading a Workshop mod's GUIDs is enough for Workbench to open its world;
- packaging with PyInstaller.

## Not done yet

- **Packaging**: a PyInstaller build. `rmt_gui.py --worker` already makes the frozen app re-launch itself as the
  worker, and `rmtlib/paths.py` already moves the addon build to `%LOCALAPPDATA%` when frozen.
- **Labs page** for `firetest.py`, `blasttest.py` and `audible/` (gui-plan.md section 9).
- **New maps on the site**: installing a world the field map doesn't know still needs its id added to `MAPS` in the
  field map's `app.js` and `server.py` (gui-plan.md section 7).
- **Trees without the game**: the profile library from [foliage-opacity-review.md](foliage-opacity-review.md).
  Until then, *Trees and foliage* (and so *install*) runs the game on screen.
