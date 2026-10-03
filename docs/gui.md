# The desktop app (`rmt_gui.py`)

A window over the same tools: pick a world, tick the data you want, choose a folder, press Start. The other tools in
the folder (mortar, blast and rocket tests, gunshot audibility, the game-file reader, the self-tests) are on its
**Labs** page. Status: first version, built from [gui-plan.md](gui-plan.md) phases 1 to 4 plus the Labs page; see
"What has been tested".

## Starting it

**Without Python:** download the zip from the repo's Releases page, unzip it and double-click
`Reforger Map Tools.exe` ([packaging.md](packaging.md)). `rmt.exe` beside it is the command line (`rmt.exe detect`).

**From this folder, with Python:** double-click `Reforger Map Tools.bat`. The first time, it:
1. finds Python 3.10 or newer (`py -3`, then `python`; if there is none it says where to get it);
2. makes a private Python environment in `.venv\` beside it (nothing is installed into your own Python);
3. installs `requirements.txt` into it (PySide6, numpy, Pillow, SciPy: a few minutes, shown in its window).

After that it just opens the window, with no console. It installs again by itself when `requirements.txt` changes
(it keeps a copy in `.venv\rmt-requirements.txt` to compare); delete `.venv\` to start over.
`"Reforger Map Tools.bat" --console` opens the window with a console beside it, to see an error.

**Setup → Add shortcuts** puts a *Reforger Map Tools* icon on the desktop and in the Start menu (they run
`.venv\Scripts\pythonw.exe rmt_gui.py`, so no console window).

Without the launcher:

```bash
pip install -r requirements.txt     # numpy, Pillow, SciPy, PySide6
python rmt_gui.py
```

If the app fails to start under `pythonw` (no console), it shows the error in a message box and appends it to
`%LOCALAPPDATA%\ReforgerMapTools\gui-error.log`; an error in a button's handler is shown in a message box too.

Windows only, like the rest of the tools. Steam must be running; Workbench and the game must be closed.

## Pages

| Page | What it does |
|---|---|
| **Setup** | Checks this PC (`rmtlib/detect.py`): Steam, the game and the Tools with their build ids, Workbench, the Documents folder (OneDrive-aware), the Workbench profile, Workshop mods, whether Steam is running and Workbench and the game are closed, free disk space, numpy, Pillow, and SciPy. Each problem says how to fix it. A Workbench path can be set by hand. |
| **World** | Every world in the game and your downloaded mods, read from the addons' own `resourceDatabase.rdb` (`rmtlib/addons.py`), so Workbench isn't started. By default only each terrain's base world (`Arland`, `EmptyArland`, `Cain`, `Eden`, ...) and every mod world; *Show every world* lists the game modes and tools too. *Use a .ent file on disk* takes a world from your own project. |
| **Data** | What to make, in plain terms (`rmtlib/products.py`): roads, terrain/objects/line of sight, place names, satellite imagery, trees and foliage, the accuracy check. Three buttons tick a set in one go: *Field map data* (what the field map shows, installed into it), *Full map export* (everything, satellite included, installed into the field map) and *Clear*. What each needs is added on its own and shown. *Quick test* runs 2 chunks per job. The **output folder** is where manifests and site data go. *Also install into the field map* runs `rmt.py fieldmap` at the end (folder holding `server.py`, and the map's id on the site). *Advanced*: chunk size, stall timeout, launches per job, and `--set` job settings. |
| **Run** | The plan as a step list, each step's state and progress from the engine's heartbeat (chunks, shots, plants, with a rough time left), the full log, elapsed time, **Cancel**, **Open output folder**, **Save log**. |
| **Past runs** | Every export in the output folder: world, game build, which jobs finished, what is baked. *Open folder*, *Open raw export*, *Bake again* (the parts its finished jobs allow), *Install into field map*. |
| **Labs** | The standalone tools, each command with a form for its options (see below). Shows the same command for a terminal, says whether it starts the game, and runs it on the Run page (log, progress, Cancel). *Read the docs*, *Open results folder*, and for the rocket test *Copy rockets.json into the field map*. |

### Labs

| Tool | Commands | Starts the game |
|---|---|---|
| Mortar fire test (`firetest.py`) | run the full test, report on a run, write the plan, group, gun, barrel | run (~25 min), group and gun (unless given a run folder to report on), barrel (~1 h) |
| Mortar blast test (`blasttest.py`) | run (shells as checkboxes, first N trials, run folder), report, plan | run (~20 min) |
| Rocket flight test (`rockettest.py`, `rocketfit.py`) | fly the rockets, fit and write `out/rockets.json`, check the site's answers, report on a check, write the plans | run (~20 min), check (~25 min) |
| Rocket launcher test (`launchertest.py`) | run, report on a run, write the plan | run (~30 min) |
| Gunshot audibility (`audible/`) | 1. measure the samples, 2. make the result table, reach by gun class, loudness of game sounds | never |
| Game files (`python -m rmtlib.pak`) | find files, show a file | never |
| Self-test | `python -m unittest discover -p test_*.py` | never |

The tests' *Field map data* option (`--site`) is filled in from the Data page's field map folder (`static\data` under
it). A command that starts the game first checks that Steam is running and the game is closed, and asks before
starting. The tools are described as data in `rmtgui/labs.py` (`TOOLS`); a new script or command is a new entry there.
Progress for the game tests comes from their heartbeat: `fire|setup|aims=N` and `fire|aim|..|left=K` (fire and rocket
tests), `blast|setup|trials=N` and `blast|trial|..|left=K`, and a count of `gun|landed` / `gun|lost` rounds (and
`launcher|fired` / `launcher|lost` for the launcher test).

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
- A Labs command runs as `rmt_gui.py [--stderr-info] --script <file.py> <args>` (or `--module <name>`): the script
  runs as `__main__` in its own folder (the audible scripts read and write files there), with its prints turned into
  the same JSON lines and an `error` and `done` event at the end. The packaged app will use the same switch.
- The worker is `python.exe` beside the window's `pythonw.exe`; Qt starts it without a console window, and the
  `tasklist`/`taskkill` calls pass `CREATE_NO_WINDOW`, so nothing flashes up.
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
- `--events` turns errors into `error` and `done` events;
- the launcher: on a PC with only the Microsoft Store Python 3.13 it made `.venv`, installed the requirements and
  opened the window;
- the window, offscreen: every page builds, the World page lists the game's 103 worlds, every Labs command builds
  the right command line and says correctly whether it starts the game, and the Self-test ran through the worker
  (4 tests OK) with its output on the Run page;
- the Labs wrapper with `rmtlib.pak list`, `audible/loud.py` and the self-tests, and the Labs heartbeat lines.

Not yet tested:
- a Labs command that starts the game (fire, blast, rocket tests) from the window;
- *Add shortcuts*;
- a real `run` through Workbench;
- Cancel during a live run;
- mod maps: whether loading a Workshop mod's GUIDs is enough for Workbench to open its world;
- packaging with PyInstaller.

## Not done yet

- **Trees without the game**: the profile library from [foliage-opacity-review.md](foliage-opacity-review.md).
  Until then, *Trees and foliage* (and so *install*) runs the game on screen.
