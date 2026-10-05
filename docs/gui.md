# The desktop app (`rmt_gui.py`)

A window over the same tools: pick a world, tick the data you want, choose a folder, press Start. The other tools in
the folder (mortar, blast and rocket tests, gunshot audibility, the game-file reader, the self-tests) are on its
**Labs** page. Additional Website data, Ballistics and Sights pages cover complete dataset production and
custom assets. Built from [gui-plan.md](gui-plan.md), with subsequent additions; see
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

**Setup â†’ Add shortcuts** puts a *Reforger Map Tools* icon on the desktop and in the Start menu (they run
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
| **Website data** | Website input audit, native mortar tables/physics, blast/barrel conversion, construction registries and curated recipes; links all producer workflows. |
| **Ballistics** | Mod weapon/vehicle/ammunition inspection, dependency-scoped source physics and custom projectile recording. |
| **Sights** | Extract inherited weapon/vehicle/optic reticles, calibrate aim/bore/range marks, export portable sketches and metadata. |
| **Labs** | The standalone tools, each command with a form for its options (see below). Shows the same command for a terminal, says whether it starts the game, and runs it on the Run page (log, progress, Cancel). *Read the docs*, *Open results folder*, target checkboxes, addon filters, saved recipes and isolated measured outputs. |

### Labs

Every category has a target checklist, addon filter, search and save/load controls. Press **Scan installed
 targets** to include downloaded mods, tick the resources, then choose the command. Weapon/vehicle inspection
opens a second checklist for resolved ammunition pairings. An empty selection cannot launch a test.
See [labs-selection.md](labs-selection.md) for the complete selection, measurement and saved-run workflow.

| Category | Selection |
|---|---|
| Mortar fire/group/gun/barrel | Mortar and shell pairings; baseline or installed mods |
| Blast | Explosive ammunition |
| Bullet flight/check/twins | Round/barrel pairings or installed weapon/vehicle ammunition |
| Rocket flight/check/twins | Rocket/missile projectiles |
| Launcher | Launcher weapon and one ammunition variant, with matching measured flight data |
| Conflict | Installed terrains or Conflict scenarios |
| Audibility | Installed WAV samples and calibrated reference level |
| Game files | Addon packages, scoped find/show |
| Self-test | Regression modules; no game required |

Plans and measurements are stored under the output folder's `labs/<category>/<signature>` and the
engine profile's corresponding signature folder. The old fixed-suite timing estimates are omitted because
runtime depends on the selected targets. Mortar planning can launch Workbench to obtain native tables.
Live commands check Steam and running game processes before launch; progress appears on the Run page.
The command preview shows the exact selected `labtest.py` invocation.

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
  runs as `__main__` in its own folder; selected Labs writes isolated outputs through `labtest.py`, with its prints turned into
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
python rmt.py run Eden --products roads,los,places,foliage --install --to ..\arma-map\everon-map --as everon
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

## Custom weapons and vehicle guns

The **Ballistics** GUI page uses `rmtgui/ballistics.py` and the worker CLI `customballistics.py`.
`rmtlib/ballistics.py` indexes installed addon prefabs, follows GUID references/inheritance, reports source physics,
loads selected addon dependencies and records direct projectile flights through the existing game test entity.
It writes separate datasets with provenance and resume signatures; it does not measure complete vehicle firing
or install custom tables into the website. Labs now supports its own explicit baseline/mod selections; see [labs-selection.md](labs-selection.md). See [custom-ballistics.md](custom-ballistics.md)
for workflow, file contracts, static-reader limits and the unverified live-mod engine boundary.


## Website data, Sights and installed mod sorting

**Website data** inventories the website application selected on Data, lists producers and runs mortar tables,
blast/barrel conversion, construction extraction and recipe exports. Map products use the normal World â†’ Data â†’
Run flow; Conflict and existing measurement tools are linked to Labs. See [website-data.md](website-data.md).

**Sights** scans installed prefabs, filters by owning addon and asset type, extracts inherited sight components
(including referenced vehicle turrets), decodes available reticles and lets you set scale, aim, bore and range
marks. Verify the calibration before exporting the preview, SVG, PNG and metadata. See [sights.md](sights.md).
Weapon packs' `.ent` test worlds remain on World; use Ballistics/Sights for their `.et` assets. Optics have their
own filter and temporary download archives are excluded. See [mod-assets.md](mod-assets.md).

All three new pages run worker CLIs through the same QProcess event/cancel mechanism. Restart the app after
updating source to load them. These pages were checked in an offscreen Qt window; mod data inspection and native
mortar-table generation were also exercised separately. Full live flights for arbitrary mod ammunition remain
unverified. Building the packaged release is a separate verification step.


## World and asset selection update

World's default list now requires `GenericTerrainEntity` evidence in a bounded 512 KiB world header read;
compiled and text resources are supported. Test/editor/image scenes, inherited scenarios and unknown sources
are available through **Advanced: scenarios, test and unknown worlds**, with type/reason labels. The addon title
and `.ent` extension do not establish that it is an independent terrain. Unusual terrains whose declaration
is outside the inspected header may require Advanced selection and Workbench inspection.

Ballistics: scan once, choose **Weapons**, **Vehicles**, **Bullets / calibres**, **Mortars / shells**,
**Rockets / missiles** or **All ammunition**, then choose an installed addon from **All related addons**.
Addon counts reflect resources in that category; unrelated addon names disappear. Inspect the selected resource
and select the actual projectile/coefficient before recording. Classification uses resource path conventions,
so **All resources (advanced)** remains available for unusual mod layouts. Ammo-named characters, sound configs
and ordinary weapon attachment configs are excluded from normal weapon/ammo lists. Custom mortar shell selection
records projectile flights; Website data's native mortar-table generator currently covers the vanilla mortars.
`test_asset_selection.py` verifies the new classification and category contracts.
