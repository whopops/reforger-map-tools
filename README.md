# Reforger Map Tools

Point `rmt.py` at any Arma Reforger map. It runs Arma Reforger Tools (Workbench) and the game itself unattended,
exports everything a map site needs, then bakes it into a site-ready data folder: roads, line-of-sight tiles, place
names, satellite tiles and tree/bush data. Nothing in it is specific to one map.

There is also a desktop app over the same tools, the mortar, blast and rocket tests and the other scripts included:
**double-click `Reforger Map Tools.bat`**. The first time, it sets up its own Python environment (`.venv\`) and
installs what it needs; after that it just opens the window. Its Setup page can add a desktop and Start menu
shortcut. See [docs/gui.md](docs/gui.md).

This file is the quick start and the map of the folder. The detail is in `docs/`:

| Doc | What it explains |
|---|---|
| [docs/gui.md](docs/gui.md) | The desktop app (`Reforger Map Tools.bat`, `rmt_gui.py`): starting it, its pages (Labs runs the other tools), how it drives `rmt.py`, what is tested and what isn't |
| [docs/export-jobs.md](docs/export-jobs.md) | `rmt.py export`: every job, its settings, its raw output files, how retries and resume work |
| [docs/bakers.md](docs/bakers.md) | `rmt.py bake`: every baker, its inputs, its output files and their binary layouts; then `rmt.py check` (scoring the line of sight) and `rmt.py fieldmap` (into the website, 2D and 3D) |
| [docs/satellite-and-foliage.md](docs/satellite-and-foliage.md) | The two jobs that run in the game itself: how they work, how to tune them |
| [docs/addon.md](docs/addon.md) | The Enforce scripts inside Workbench and the game, and the command-line contract between them and `rmt.py` |
| [docs/firetest.md](docs/firetest.md) | The mortar and rocket tools: `firetest.py` (live-fire test), `blasttest.py` (blast test), `rockettest.py` (rocket flights) and the `ballistics` job |
| [docs/audible.md](docs/audible.md) | `audible/`: how far gunshots are heard, from the game's sound files |
| [docs/gui-plan.md](docs/gui-plan.md) | The plan behind the desktop app, and what is still to do |
| [docs/packaging.md](docs/packaging.md) | Proposal: how to ship the desktop app as a zip with no Python needed |
| [docs/foliage-opacity-review.md](docs/foliage-opacity-review.md) | Review: measuring foliage opacity without screenshots (not built) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Hard rules, known failures and what to do about them |

## Requirements

- Windows, with Steam running.
- Arma Reforger (Steam app 1874880) and Arma Reforger Tools (1874910) installed. `rmt.py` finds them through the
  Steam registry key and `libraryfolders.vdf`; `--workbench <exe>` overrides the Workbench path.
- Python 3 (tried on 3.13) with `numpy`, `Pillow`, and `scipy`. Exporting needs only the standard library; install
  `requirements.txt` for baking and the desktop app. Foliage measurement requires SciPy and checks it before processing.
- Workbench and the game **closed** while `rmt.py` runs (it refuses to start otherwise).
- A mod map needs its addon downloaded from the Workshop (the game's `addons` folder is searched automatically).

## Quick start

```bash
python rmt.py worlds                          # list the 103 or so worlds Workbench can see
python rmt.py export Arland                   # raw data: probe, mapdata, roads, names, entities, terrain, surface
python rmt.py export Arland --jobs satellite  # satellite shots (runs the game, takes over the screen)
python rmt.py bake Arland                     # raw data -> out/arland-a9806a/<build>/site/
python rmt.py fieldmap Arland                 # site/ -> arma-map/everon-map (field map and 3D view)
```

Start with the smallest map (Arland, about 4 km) to see the whole chain work before running Everon or Kolguyev.
`export` is safe to rerun: it picks up where it stopped. A new game build always gets a new folder.

`<world>` can be any of: a `.ent` file on disk (mod maps), a resource path (`worlds/Eden/Eden.ent`), or a world's
file name (`Eden`). Names that match several worlds are rejected with the list of candidates.

## Commands

| Command | What it does |
|---|---|
| `python rmt.py worlds [--refresh]` | Prints every world Workbench can see. Cached in `out/worlds.txt`; `--refresh` starts Workbench once to ask it again. |
| `python rmt.py export <world> [options]` | Runs export jobs for one world. See [docs/export-jobs.md](docs/export-jobs.md). |
| `python rmt.py bake <world> [--parts ...]` | Bakes the newest export of that world into site data. See [docs/bakers.md](docs/bakers.md). |
| `python rmt.py check <world>` | Scores the baked line of sight against the engine's own sight lines (the `sightlines` job). See [docs/bakers.md](docs/bakers.md#rmtpy-check-scoring-the-line-of-sight). |
| `python rmt.py fieldmap <world> [--to ...]` | Installs the newest bake into the website (`arma-map/everon-map`): the map data both its 2D and 3D views read, the 3D view's trees and its map list. See [docs/bakers.md](docs/bakers.md#rmtpy-fieldmap-into-the-website). |
| `python rmt.py run <world> --products a,b [--install ...]` | Export, bake, check and install in one go, from what you want (`roads`, `los`, `places`, `satellite`, `foliage`, `check`); dependencies are added. Takes the `export` options and the `fieldmap` options. See [docs/gui.md](docs/gui.md#new-command-line-pieces-usable-without-the-window). |
| `python rmt.py detect` | Checks this PC: Steam, the game, the Tools, Workbench, mods, whether Workbench and the game are closed. |

Global options (before the command): `--workbench <path to ArmaReforgerWorkbenchSteamDiag.exe>`; `--workspace <folder>`
(manifests and site data go there instead of `out/`); `--events` (JSON lines for the desktop app).

`export` options: `--jobs a,b,c`, `--tile <m>` (chunk size, default 500), `--region tx0,tz0,tx1,tz1` and
`--max-chunks N` (both for tests), `--set NAME=VALUE` (repeatable, passed on as `-rmtNAME=VALUE`), `--retries N`
(default 3), `--stall S` (seconds without progress before the run is killed, default 600).

`bake` option: `--parts roads,los,places,satellite,foliage,plants` (default all).

## The full pipeline

```
export  --jobs probe,mapdata,roads,names,entities,terrain,surface     (Workbench, minutes to hours)
export  --jobs satellite                                              (game, about 1-2 h on Everon)
export  --jobs foliage                                                (game, about 100 s per plant kind)
bake    (roads, los, places, satellite, foliage, plants)              (Python, no game needed)
export  --jobs sightlines, then check                                 (optional: how well the tiles match the game)
fieldmap                                                              (install the bake into the website, 3D trees too)
```

Order rules: `probe` runs first in every export that includes it (it is in the default list), and `satellite` needs
`probe` to have run before (it reads the map bounds from it). In a bake, `plants` needs `los` and `foliage` baked
first, and `satellite` needs the terrain export.

## Where things go

| What | Where |
|---|---|
| Raw data from the Workbench jobs | `<Documents>\My Games\ArmaReforgerWorkbench\profile\rmt\<slug>\<build>\` |
| Raw data from the game jobs (`satellite`, `foliage`) | `<Documents>\My Games\ArmaReforger\profile\rmt\<slug>\<build>\satellite` and `...\foliage` |
| Run record (`manifest.json`) and baked site data | `out/<slug>/<build>/` and `out/<slug>/<build>/site/` in this repo (or in the `--workspace` folder; the app's output folder) |
| World list cache | `out/worlds.txt` (only `rmt.py worlds` uses it now: names resolve through the addons' resource databases first) |
| Engine sight lines for `check` | `<raw folder>\sightlines\check.csv` |
| The website's copy (`fieldmap`) | `arma-map\everon-map\static\data\maps\<id>\`, with its `map.json` (beside this repo's folder by default) |
| Generated addon copy | `.build/` (rebuilt every run; do not edit) |

`<slug>` is the world's file name in lower case plus the first six characters of its GUID (`arland-a9806a`);
`<build>` is the game's Steam build id. Raw exports are large (Everon is several GB) and stay on your PC; only
`site/` is meant to be uploaded. `rmt.py` never deletes an export.

## What is in this folder

| Path | What it is |
|---|---|
| `rmt.py` | The command line. Parses arguments; `bake`, `check`, `fieldmap`, `run` and `detect` logic. |
| `Reforger Map Tools.bat` | Double-click launcher for the desktop app: makes `.venv\`, installs `requirements.txt`, opens the window |
| `rmt_gui.py`, `rmtgui/` | The desktop app ([docs/gui.md](docs/gui.md)): `app.py` the window, `worker.py` the child process, `labs.py` the Labs page's tools and commands, `theme.py` the look (dark, the field map's yellow), `icon.ico`; `requirements.txt` lists what it and the bakers need |
| `test_*.py` | Regression tests: `python -m unittest discover -p "test_*.py"` (or Labs → Self-test) |
| `rmtlib/export.py` | `export` and `worlds`: world resolution, retries, manifest, satellite grid |
| `rmtlib/addons.py` | Every installed addon and its worlds, from their resource databases; a world's mod dependencies |
| `rmtlib/products.py` | What you ask for (roads, line of sight, ...) as export jobs and bake parts |
| `rmtlib/detect.py` | The checks behind `rmt.py detect` and the app's Setup page |
| `rmtlib/paths.py` | Where the workspace and the built addon are (repo, `--workspace`, or the packaged app) |
| `rmtlib/events.py` | `--events`: JSON progress lines from the engine's heartbeat |
| `rmtlib/workbench.py` | Builds the addon, launches Workbench or the game, supervises it through its log |
| `rmtlib/steam.py` | Finds Steam, the game, Tools, profiles and logs; reads build ids |
| `rmtlib/bake_roads.py` | Baker: `roads.json` (uses `rmtlib/topo.py`) |
| `rmtlib/topo.py` | Reader for BI's `.topo` map-geometry file (decoded by hand) |
| `rmtlib/bake_los.py` | Baker: line-of-sight tiles and 10 m light grids |
| `rmtlib/check_los.py` | `rmt.py check`: scores the line-of-sight tiles against the engine's sight lines |
| `rmtlib/fieldmap.py` | `rmt.py fieldmap`: installs a bake into the website (field map and 3D view) |
| `rmtlib/trees.py` | The website's 3D trees: per-chunk tree records and the species shapes (used by `fieldmap`) |
| `rmtlib/bake_places.py` | Baker: `places.json` (uses `rmtlib/pak.py` for the game's string table) |
| `rmtlib/satellite.py` | Baker: corrects the game's shots and cuts the tile pyramid |
| `rmtlib/foliage.py` | Plant list for the foliage job, photo conversion, and the photo analysis |
| `rmtlib/bake_plants.py` | Baker: per-chunk plant files, `foliage.json`, 10 m foliage and clutter layers |
| `rmtlib/pak.py` | Reads files out of the game's `.pak` archives (also a command, below) |
| `addon/` | The Enforce scripts (see [docs/addon.md](docs/addon.md)) |
| `firetest.py` | Live mortar firing test: plan, fire in the game, score ([docs/firetest.md](docs/firetest.md)) |
| `blasttest.py` | Live mortar blast test: who goes down or is hurt around a burst ([docs/firetest.md](docs/firetest.md)) |
| `rockettest.py`, `rocketfit.py` | Live rocket flight test, and the flight and wind tables the site's rocket calculator reads ([docs/firetest.md](docs/firetest.md)) |
| `launchertest.py` | Live launcher test: soldiers fire the real launchers to check sights, launch scatter and hits ([docs/firetest.md](docs/firetest.md)) |
| `bullettest.py` | Live bullet flight test: the scoped rifles', machine guns' and vehicle guns' rounds, the site's sight calculator ([docs/firetest.md](docs/firetest.md)) |
| `rmtlib/prefab.py` | Reads values out of the game's prefabs, following their inheritance |
| `audible/` | Gunshot audibility from the game's sound files; separate scripts, run from that folder ([docs/audible.md](docs/audible.md)) |
| `docs/` | The documentation listed above |

Which data came from which tool: `everon-data/mortar/` from `firetest.py`, `everon-data/rockets/` from
`rockettest.py`, `everon-data/sound/` from `audible/`, and
new exports of any map from `rmt.py`. The first Everon export (`everon-data/` terrain, objects, surface, roads,
foliage, `check.csv`) came from older tools that were in the `arma-map` repo (`everon-map/tools`); `rmt.py` replaced
them and they have been removed (they are in that repo's git history). arma-map holds only what runs the website
(the field map and, at `/3d/`, its 3D view, which used to be the separate everon-3d-map); all the tooling that makes
its data lives here. `rmt.py fieldmap` replaces arma-map's old `tools/import_map_data.py` and everon-3d-map's old
`tools/import_rmt.py`, `tools/import_field_map.py` and `tools/build_trees.py` (both repos' git history keeps the
originals).

### `pak.py`: read the game's own files

Handy for seeing how BI does something. It is a standalone command:

```bash
python -m rmtlib.pak list "SCR_WorldDataExport"                       # regex over every path in the game paks
python -m rmtlib.pak cat scripts/WorkbenchGame/WorldEditor/SCR_WorldDataExportTool.c
```

`list <regex>` prints matching paths with size and pak. `cat <exact path>` prints one file as text. The first call
scans every pak and takes a few seconds.
