this is all 100% vibe coded i never actually used the GUI i recommend just pointing and LLM at this to get what you want. stuff in here is used to make the stuff that gets used by the arma-map page.


# Reforger Map Tools

Point `rmt.py` at any Arma Reforger map. It runs Arma Reforger Tools (Workbench) and the game itself unattended,
exports everything a map site needs, then bakes it into a site-ready data folder: roads, line-of-sight tiles, place
names, satellite and shaded-relief tiles, and tree/bush data. The main map pipeline derives its grid from the
world's probe; the separate live-fire experiments use Everon and existing field-map data.

There is also a desktop app over the same tools, the mortar, blast and rocket tests and the other scripts included:
**double-click `Reforger Map Tools.bat`**. The first time, it sets up its own Python environment (`.venv\`) and
installs what it needs; after that it just opens the window. Its Setup page can add a desktop and Start menu
shortcut. See [docs/gui.md](docs/gui.md).

This file is the quick start and the map of the folder. The detail is in `docs/`:

**For AI models and contributors:** start with [docs/code-guide.md](docs/code-guide.md). It explains execution
flow, module responsibilities, data contracts, tests and limitations without requiring a full source scan.

**Website dataset production:** open **Website data** to audit the website inputs and run the additional producers.
See [docs/website-data.md](docs/website-data.md) for the complete input/producer map. **Sights** extracts mod reticles,
calibrates aim/bore/range marks and exports portable sketches; see [docs/sights.md](docs/sights.md). Installed mods
are grouped by addon and asset type; [docs/mod-assets.md](docs/mod-assets.md) records the current examples and limits.

**Custom weapons and vehicle guns:** the GUI has a separate **Ballistics** page for prefab inspection and custom
projectile flight recording. See [docs/custom-ballistics.md](docs/custom-ballistics.md) for workflow and limits.

| Doc | What it explains |
|---|---|
| [docs/website-data.md](docs/website-data.md) | Complete website input/producer map, native mortar tables, measurements and curated recipes |
| [docs/sights.md](docs/sights.md) | Extract mod reticles, calibrate aim/bore/ranges and export portable sight sketches |
| [docs/mod-assets.md](docs/mod-assets.md) | Installed-mod families, sorting, dependency isolation and reviewed examples |
| [docs/changes-redo.md](docs/changes-redo.md) | Reapply the complete changes after replacing the checkout |
| [docs/code-guide.md](docs/code-guide.md) | Quick code understanding for AI models and contributors; where to make changes and how to verify them |
| [docs/gui.md](docs/gui.md) | The desktop app (`Reforger Map Tools.bat`, `rmt_gui.py`): starting it, its pages (Labs runs the other tools), how it drives `rmt.py`, what is tested and what isn't |
| [docs/labs-selection.md](docs/labs-selection.md) | Select baseline/mod targets for every Labs category; inspect ammunition pairings, save recipes and reproduce isolated measurements |
| [docs/export-jobs.md](docs/export-jobs.md) | `rmt.py export`: every job, its settings, its raw output files, how retries and resume work |
| [docs/bakers.md](docs/bakers.md) | `rmt.py bake`: every baker, its inputs, its output files and their binary layouts; then `rmt.py check` (scoring the line of sight) and `rmt.py fieldmap` (into the website, 2D and 3D) |
| [docs/satellite-and-foliage.md](docs/satellite-and-foliage.md) | The two jobs that run in the game itself: how they work, how to tune them |
| [docs/addon.md](docs/addon.md) | The Enforce scripts inside Workbench and the game, and the command-line contract between them and `rmt.py` |
| [docs/firetest.md](docs/firetest.md) | The mortar and rocket tools: `firetest.py` (live-fire test), `blasttest.py` (blast test), `rockettest.py` (rocket flights) and the `ballistics` job |
| [docs/audible.md](docs/audible.md) | `audible/`: how far gunshots are heard, from the game's sound files |
| [docs/gui-plan.md](docs/gui-plan.md) | The plan behind the desktop app, and what is still to do |
| [docs/packaging.md](docs/packaging.md) | The desktop app as a zip with no Python needed: how it is built and released |
| [docs/foliage-opacity-review.md](docs/foliage-opacity-review.md) | Review: measuring foliage opacity without screenshots (not built) |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Hard rules, known failures and what to do about them |

## Requirements

- Windows, with Steam running.
- Arma Reforger (Steam app 1874880) and Arma Reforger Tools (1874910) installed. `rmt.py` finds them through the
  Steam registry key and `libraryfolders.vdf`; `--workbench <exe>` overrides the Workbench path.
- Python 3.10 or newer (the launcher checks this; packaging uses 3.12), with `numpy`, `Pillow`, and `scipy`.
  Ordinary Workbench export needs only the standard library; install
  `requirements.txt` for baking and the desktop app. Foliage measurement requires SciPy and checks it before processing.
- Workbench and the game **closed** while `rmt.py` runs (it refuses to start otherwise).
- A mod map needs its addon downloaded from the Workshop (the game's `addons` folder is searched automatically).

## Quick start

Run commands in PowerShell from this repository's root. If you used the batch launcher, use
`.\.venv\Scripts\python.exe` in place of `python` to use its installed dependencies. Otherwise:

```powershell
python -m pip install -r requirements.txt
python rmt.py worlds                          # list worlds visible to Workbench (count varies)
python rmt.py export Arland                   # raw probe, mapdata, roads, names, entities, terrain, surface
python rmt.py bake Arland --parts roads,los,places,relief
```

That produces map data in `out/arland-a9806a/<build>/site/` without starting the game. To prepare and install
a complete map, including measured plants, use `run` so dependencies are added automatically:

```powershell
python rmt.py run Arland --products roads,los,places,relief,foliage --install --to "..\arma-map\arma-map" --as arland --title Arland
```

`--to` must name the website folder holding `server.py`. The example assumes this repo and `arma-map` share
the same parent folder. `--as` is required for the first install of a new map; later installs can find its id
from `map.json`. This command photographs foliage in the game on screen. Add satellite imagery separately
(also runs the game on screen):

```powershell
python rmt.py export Arland --jobs probe,terrain,satellite
python rmt.py bake Arland --parts satellite
python rmt.py fieldmap Arland --to "..\arma-map\arma-map"
```

Pass `--to` explicitly in the sibling-repository layout. Current automatic discovery checks
`../../arma-map/arma-map` relative to this repo, which was intended for its previous nested location.

Start with the smallest map (Arland, about 4 km) to see the whole chain work before running Everon or Kolguyev.
Rerun `export` with the same grid and settings to resume completed chunks. Changing sampling settings does not
invalidate old `.ok` markers; keep incompatible exports separate. A new game build gets a new folder.

`<world>` can be any of: a `.ent` file on disk (mod maps), a resource path (`worlds/Eden/Eden.ent`), or a world's
file name (`Eden`). Names that match several worlds are rejected with the list of candidates.

## Commands

| Command | What it does |
|---|---|
| `python rmt.py worlds [--refresh]` | Prints every world Workbench can see. Cached in `out/worlds.txt`; `--refresh` starts Workbench once to ask it again. |
| `python rmt.py export <world> [options]` | Runs export jobs for one world. See [docs/export-jobs.md](docs/export-jobs.md). |
| `python rmt.py bake <world> [--parts ...]` | Bakes the newest export of that world into site data. See [docs/bakers.md](docs/bakers.md). |
| `python rmt.py check <world>` | Scores the baked line of sight against the engine's own sight lines (the `sightlines` job). See [docs/bakers.md](docs/bakers.md#rmtpy-check-scoring-the-line-of-sight). |
| `python rmt.py fieldmap <world> [--to ...]` | Installs the newest bake into the website (`arma-map/arma-map`): the map data both its 2D and 3D views read, the 3D view's trees and its map list. See [docs/bakers.md](docs/bakers.md#rmtpy-fieldmap-into-the-website). |
| `python rmt.py run <world> --products a,b [--install]` | Export and bake chosen products; select `check` to score and `--install` to install (`roads`, `los`, `places`, `satellite`, `relief`, `foliage`, `check`); dependencies are added. Takes the `export` options and the `fieldmap` options. See [docs/gui.md](docs/gui.md#new-command-line-pieces-usable-without-the-window). |
| `python rmt.py detect` | Checks this PC: Steam, the game, the Tools, Workbench, mods, whether Workbench and the game are closed. |
| `python conflict.py <world> [<world> ...]` | The field map's Conflict layers (bases, radio towers, HQ starts, supply stashes, vehicle spawns, refuel and repair points, FIA cache spots) from the world's Conflict scenario (`worlds/MP/CTI_Campaign_<world>.ent`): runs the `conflict` export job on it, bakes it (`rmtlib/bake_conflict.py`) and writes `static/data/<map id>.json` into the website. `python conflict.py Arland Cain` does Arland and Kolguyev. |

Global options (before the command): `--workbench <path to ArmaReforgerWorkbenchSteamDiag.exe>`; `--workspace <folder>`
(manifests and site data go there instead of `out/`); `--events` (JSON lines for the desktop app).

`export` options: `--jobs a,b,c`, `--tile <m>` (chunk size, default 500), `--region tx0,tz0,tx1,tz1` and
`--max-chunks N` (both for tests), `--set NAME=VALUE` (repeatable, passed on as `-rmtNAME=VALUE`), `--retries N`
(default 3), `--stall S` (seconds without progress before the run is killed, default 600).

`bake` option: `--parts roads,los,places,satellite,relief,foliage,plants` (default all). Parts run in that order;
dependencies are not added. Missing optional capture inputs may be skipped; read the output even on exit 0.

## The full pipeline

```
export  --jobs probe,mapdata,roads,names,entities,terrain,surface     (Workbench, minutes to hours)
export  --jobs satellite                                              (game, about 1-2 h on Everon)
export  --jobs foliage                                                (game, about 100 s per plant kind)
bake    (roads, los, places, satellite, relief, foliage, plants)              (Python, no game needed)
export  --jobs sightlines, then check                                 (optional: how well the tiles match the game)
fieldmap                                                              (install the bake into the website, 3D trees too)
```

Order rules: explicit `export --jobs` runs Workbench jobs in the order you give, so put `probe` first when needed.
`run` orders jobs and adds dependencies for you. Satellite needs a probe recorded in the manifest and terrain for
baking; foliage capture needs exported entities. In a bake, `plants` needs `los` and `foliage` baked first;
`relief` needs baked `los` and the `mapdata` raster. Low-level `bake --parts` does not add dependencies.

## Where things go

| What | Where |
|---|---|
| Raw data from the Workbench jobs | `<Documents>\My Games\ArmaReforgerWorkbench\profile\rmt\<slug>\<build>\` |
| Raw data from the game jobs (`satellite`, `foliage`) | `<Documents>\My Games\ArmaReforger\profile\rmt\<slug>\<build>\satellite` and `...\foliage` |
| Run record (`manifest.json`) and baked site data | `out/<slug>/<build>/` and `out/<slug>/<build>/site/` in this repo (or in the `--workspace` folder; the app's output folder) |
| World list cache | `<workspace>/worlds.txt` (`out/` by default; world resolution uses resource databases first and this list as fallback) |
| Engine sight lines for `check` | `<raw folder>\sightlines\check.csv` |
| The website's copy (`fieldmap`) | `<website>/static/data/maps/<id>/`, with its `map.json`; pass `--to` for the sibling-repository layout |
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
| `conflict.py`, `rmtlib/bake_conflict.py` | The Conflict layers: export (the `conflict` job), bake and install of `static/data/<map id>.json` |
| `rmtlib/satellite.py` | Baker: corrects the game's shots and cuts the tile pyramid |
| `rmtlib/relief.py` | Baker: shaded-relief tiles from baked LOS terrain/solids and the `mapdata` raster |
| `rmtlib/foliage.py` | Plant list for the foliage job, photo conversion, and the photo analysis |
| `rmtlib/bake_plants.py` | Baker: per-chunk plant files, `foliage.json`, 10 m foliage and clutter layers |
| `rmtlib/pak.py` | Reads files out of the game's `.pak` archives (also a command, below) |
| `addon/` | The Enforce scripts (see [docs/addon.md](docs/addon.md)) |
| `firetest.py` | Live mortar firing test: plan, fire in the game, score ([docs/firetest.md](docs/firetest.md)) |
| `blasttest.py` | Live mortar blast test: who goes down or is hurt around a burst ([docs/firetest.md](docs/firetest.md)) |
| `rockettest.py`, `rocketfit.py` | Live rocket flight test in fifteen winds, the flight and wind tables the site's rocket calculator reads, and a copy of that calculator whose answers `check` fires in the game ([docs/firetest.md](docs/firetest.md)) |
| `launchertest.py` | Live launcher test: soldiers fire the real launchers to check sights, launch scatter and hits ([docs/firetest.md](docs/firetest.md)) |
| `bullettest.py` | Live bullet flight test: the scoped rifles', machine guns' and vehicle guns' rounds for the site's sight calculator, and `check`, its answers fired in the game ([docs/firetest.md](docs/firetest.md)) |
| `test_sitesolver.py` | `rocketfit.py`'s copy of the site's shot calculator against the real one (`shot-core.js`, in Node): `--site <field map folder>`, or `RMT_SITE` under the self-test |
| `customballistics.py`, `rmtlib/ballistics.py`, `rmtgui/ballistics.py` | Custom mod weapon/ammo/vehicle discovery, inherited physics, dependency-aware flight recording and separate datasets |
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
