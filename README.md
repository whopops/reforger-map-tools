# Reforger Map Tools

Point `rmt.py` at any Arma Reforger map. It runs Arma Reforger Tools (Workbench) and the game itself unattended,
exports everything a map site needs, then bakes it into a site-ready data folder: roads, line-of-sight tiles, place
names, satellite tiles and tree/bush data. Nothing in it is specific to one map.

This file is the quick start and the map of the folder. The detail is in `docs/`:

| Doc | What it explains |
|---|---|
| [docs/export-jobs.md](docs/export-jobs.md) | `rmt.py export`: every job, its settings, its raw output files, how retries and resume work |
| [docs/bakers.md](docs/bakers.md) | `rmt.py bake`: every baker, its inputs, its output files and their binary layouts |
| [docs/satellite-and-foliage.md](docs/satellite-and-foliage.md) | The two jobs that run in the game itself: how they work, how to tune them |
| [docs/addon.md](docs/addon.md) | The Enforce scripts inside Workbench and the game, and the command-line contract between them and `rmt.py` |
| [docs/firetest.md](docs/firetest.md) | The mortar tools: `firetest.py` (live-fire test) and the `ballistics` job |
| [docs/audible.md](docs/audible.md) | `audible/`: how far gunshots are heard, from the game's sound files |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Hard rules, known failures and what to do about them |
| [PLAN.md](PLAN.md) | Design, spike results and decisions |

## Requirements

- Windows, with Steam running.
- Arma Reforger (Steam app 1874880) and Arma Reforger Tools (1874910) installed. `rmt.py` finds them through the
  Steam registry key and `libraryfolders.vdf`; `--workbench <exe>` overrides the Workbench path.
- Python 3 (tried on 3.13) with `numpy` and `Pillow`. Exporting needs only the standard library; baking needs both.
- Workbench and the game **closed** while `rmt.py` runs (it refuses to start otherwise).
- A mod map needs its addon downloaded from the Workshop (the game's `addons` folder is searched automatically).

## Quick start

```bash
python rmt.py worlds                          # list the 103 or so worlds Workbench can see
python rmt.py export Arland                   # raw data: probe, mapdata, roads, names, entities, terrain, surface
python rmt.py export Arland --jobs satellite  # satellite shots (runs the game, takes over the screen)
python rmt.py bake Arland                     # raw data -> out/arland-a9806a/<build>/site/
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

Global option: `--workbench <path to ArmaReforgerWorkbenchSteamDiag.exe>`.

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
```

Order rules: `probe` runs first in every export that includes it (it is in the default list), and `satellite` needs
`probe` to have run before (it reads the map bounds from it). In a bake, `plants` needs `los` and `foliage` baked
first, and `satellite` needs the terrain export.

## Where things go

| What | Where |
|---|---|
| Raw data from the Workbench jobs | `<Documents>\My Games\ArmaReforgerWorkbench\profile\rmt\<slug>\<build>\` |
| Raw data from the game jobs (`satellite`, `foliage`) | `<Documents>\My Games\ArmaReforger\profile\rmt\<slug>\<build>\satellite` and `...\foliage` |
| Run record (`manifest.json`) and baked site data | `out/<slug>/<build>/` and `out/<slug>/<build>/site/` in this repo |
| World list cache | `out/worlds.txt` |
| Generated addon copy | `.build/` (rebuilt every run; do not edit) |

`<slug>` is the world's file name in lower case plus the first six characters of its GUID (`arland-a9806a`);
`<build>` is the game's Steam build id. Raw exports are large (Everon is several GB) and stay on your PC; only
`site/` is meant to be uploaded. `rmt.py` never deletes an export.

## What is in this folder

| Path | What it is |
|---|---|
| `rmt.py` | The only command you run. Parses arguments, `bake` logic. |
| `rmtlib/export.py` | `export` and `worlds`: world resolution, retries, manifest, satellite grid |
| `rmtlib/workbench.py` | Builds the addon, launches Workbench or the game, supervises it through its log |
| `rmtlib/steam.py` | Finds Steam, the game, Tools, profiles and logs; reads build ids |
| `rmtlib/bake_roads.py` | Baker: `roads.json` (uses `rmtlib/topo.py`) |
| `rmtlib/topo.py` | Reader for BI's `.topo` map-geometry file (decoded by hand) |
| `rmtlib/bake_los.py` | Baker: line-of-sight tiles and 10 m light grids |
| `rmtlib/bake_places.py` | Baker: `places.json` (uses `rmtlib/pak.py` for the game's string table) |
| `rmtlib/satellite.py` | Baker: corrects the game's shots and cuts the tile pyramid |
| `rmtlib/foliage.py` | Plant list for the foliage job, photo conversion, and the photo analysis |
| `rmtlib/bake_plants.py` | Baker: per-chunk plant files, `foliage.json`, 10 m foliage and clutter layers |
| `rmtlib/pak.py` | Reads files out of the game's `.pak` archives (also a command, below) |
| `addon/` | The Enforce scripts (see [docs/addon.md](docs/addon.md)) |
| `firetest.py` | Live mortar firing test: plan, fire in the game, score ([docs/firetest.md](docs/firetest.md)) |
| `audible/` | Gunshot audibility from the game's sound files; separate scripts, run from that folder ([docs/audible.md](docs/audible.md)) |
| `docs/` | The documentation listed above |

Which data came from which tool: `everon-data/mortar/` from `firetest.py`, `everon-data/sound/` from `audible/`, and
new exports of any map from `rmt.py`. The first Everon export (`everon-data/` terrain, objects, surface, roads,
foliage) came from older tools that live in the `arma-map` repo (`everon-map/tools`) and are replaced by `rmt.py`.

### `pak.py`: read the game's own files

Handy for seeing how BI does something. It is a standalone command:

```bash
python -m rmtlib.pak list "SCR_WorldDataExport"                       # regex over every path in the game paks
python -m rmtlib.pak cat scripts/WorkbenchGame/WorldEditor/SCR_WorldDataExportTool.c
```

`list <regex>` prints matching paths with size and pak. `cat <exact path>` prints one file as text. The first call
scans every pak and takes a few seconds.
