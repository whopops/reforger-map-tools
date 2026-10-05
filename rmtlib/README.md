# `rmtlib/`: the Python library behind `rmt.py`

`rmt.py` (one folder up) parses arguments and orchestrates bake, check, install and product runs. These modules
implement engine discovery, export supervision and data processing. Import them as
`from rmtlib import ...` from the repo root. The user-level docs are in [../docs](../docs/); this file is for
someone reading or changing the code.

For the complete repository flow, including the GUI, addon and live-fire tools, start with
[../docs/code-guide.md](../docs/code-guide.md).

## How the modules fit together

```
rmt.py
 |- export.py ---- workbench.py ---- steam.py        export: launch Workbench / the game, watch, keep a manifest
 |     '- foliage.py                                  (plant list + photo conversion while the foliage job runs)
 |- bake_*.py, satellite.py, foliage.py              bake: raw export -> site data
 |     |- topo.py                                     (BI's .topo reader, used by bake_roads)
 |     '- pak.py                                      (game pak reader, used by bake_places)
 |- check_los.py                                      check: baked los/ tiles vs the engine's sight lines
 '- fieldmap.py ---- trees.py                         fieldmap: site data + entities -> the website (arma-map's
                                                      field map and its 3D view)
```

Bakers never launch the game. Export also uses `foliage.py` for the plant list and screenshot conversion; that
module's photo analysis is invoked during baking. The shared raw layout is described in
[../docs/export-jobs.md](../docs/export-jobs.md).

## Modules

### For the desktop app and `rmt.py run` (see [../docs/gui.md](../docs/gui.md))
- `paths.py`: `workspace()` (manifests and site data; `out/` by default, `--workspace` to change), `build_root()` and
  `addon_source()` (repo, or `%LOCALAPPDATA%` and the bundle when packaged).
- `events.py`: `enable()`, `emit(kind, **fields)`, `step`, `progress`, and `heartbeat(label, msg)`, which turns the
  engine's `RMT|` lines into progress (called from `workbench._supervise`; export jobs, satellite and foliage, and
  the Labs tests' `fire|`, `blast|` and `gun|` lines as step `lab`). Does nothing until enabled.
- `addons.py`: `installed(install)` (every addon with its GUID, title and dependencies), `list_worlds(install)`,
  `find_world(install, arg)` -> `(resource, addon GUIDs, addon folders)`, read from `resourceDatabase.rdb`.
  `Exporter.resolve` tries it before `worlds.txt`.
- `products.py`: `PRODUCTS`, `plan(selected, install)` -> jobs, bake parts and the step list.
- `detect.py`: `report(workbench_exe)` -> the Setup checks; `ready(checks)`.
- `workbench.restore_video_settings(game_profile)`: puts back the game's screen settings after a killed foliage run.

### `steam.py`: where everything is installed
- `steam_root()`, `libraries()`: Steam path from the registry and the library folders from `libraryfolders.vdf`.
- `app(appid)`: `(install folder, build id)` of an installed Steam app.
- `Install(workbench_exe=None)`: everything `rmt` needs to know: `game_dir`, `game_build`, `tools_dir`,
  `tools_build`, `exe` (Workbench), `workbench_dir`, `game_exe`, `game_addons`, `workshop_addons`, and the two
  profile and log folders (`profile`, `logs` for Workbench; `game_profile`, `game_logs` for the game). The real
  Documents folder is read from the registry because it may be redirected to OneDrive. Raises `SystemExit` with a
  clear message when something is not installed. Windows only (`winreg`).

### `workbench.py`: run and supervise one engine launch
- `build_addon(extra_guids)`: copies `addon/Scripts` into `.build/ReforgerMapTools` and writes an `addon.gproj`
  that depends on the game and on any map addon GUIDs. Rebuilt every run so the committed addon never changes.
- `Runner(install, addon_dirs, extra_guids, log)`: `Workbench` is an older name for the same class.
  - `run(jobs, out_rel, world, args, stall, limit)`: Workbench plugin jobs on one load of the world. Returns
    `(exit code, RMT lines, status of the last job)`.
  - `run_game(job, out_rel, world, args, stall, limit, flag, screen)`: a capture or test in the real game
    (`flag` is `-rmtSat`, `-rmtFoliage` or `-rmtFire`). `screen=(w, h, mode)` temporarily changes the video settings
    and restores them afterwards.
  - `status_path(out_rel, job, game=False)`: where a job's `<job>.status.json` is.
- `read_status(path)`: parse a status file, or `None`.
- `JobFailed`: raised for a stall, a script compile error, a missing log or the time limit.
- Supervision loop (`_supervise`): deletes stale status files, finds the launch's new `console.log`, follows it for
  `RMT|` lines (heartbeats), and kills the process tree on stall. Closes `CrashReporter.exe` windows that started
  during the run.

### `export.py`: `rmt.py worlds` and `rmt.py export`
- Constants `JOBS` (the default list), `ALL_JOBS` (everything `--jobs` accepts), `CHUNK_JOBS`.
- `slug_of(resource)`: `arland-a9806a`-style folder name. `addon_of_file(path)`: addon GUID and parent folder for a
  `.ent` on disk.
- `Exporter(install)`:
  - `list_worlds(refresh)`: cached list in `out/worlds.txt`.
  - `resolve(arg)`: a file, resource path or name into `(resource, extra addon GUIDs, extra addon folders)`.
  - `export(world, jobs, tile, region, max_chunks, retries, stall, fresh, settings)`: the whole run, returns
    `(manifest, failed jobs)`. Workbench jobs share one launch and are relaunched with only the unfinished ones;
    then `satellite`, then `foliage`.
  - `satellite_args(manifest, settings)`: builds the satellite grid and camera arguments from the probe.

### `topo.py`: BI's `.topo` map geometry
- `sections(data)`, `read(path, size_z)`: decode the file. `read` returns the roads (centre line, width, type) and
  the other decoded sections, flipping BI's y to world z using the map's z extent. The byte layout is documented in
  the module docstring. `AREA`, `WATR` and `PWLN` are not decoded.

### `pak.py`: files out of the game's `.pak` archives
- `game_paks()`, `entries(pak)`, `read(...)`, `read_file(path)`: by exact path from whichever pak has it.
- Also a command: `python -m rmtlib.pak list <regex>` and `cat <path>`.

### Bakers (most expose `bake(raw, site, log=print)`; imagery and analysis use the functions below)

| Module | Output | Notes |
|---|---|---|
| `bake_roads.py` | `roads.json` | `build(roads)` makes the node and edge graph (`SNAP_M`, `TOUCH_M`, `EXTEND_M`, `SIMPLIFY_M` at the top set the joining rules); `material_kind` types road pieces when there is no `.topo` |
| `bake_los.py` | `los/`, `light/` | `Grid` reads the chunk grid and units from `probe.json`; `bake_chunk` makes one tile; `light_cells` and `bake_lz` make the 10 m grids |
| `bake_places.py` | `places.json` | `strings()` reads the English string table out of the paks; `MDT`, `TOWNS`, `LANDMARKS`, `SKIP` map descriptor types |
| `bake_plants.py` | `foliage.json`, `plants/`, light foliage and clutter | needs the `los` and `foliage` bakes first |
| `satellite.py` | `tiles/` | `build(shots_dir, terrain_raw, out_dir)`; `mosaic(...)` renders one test picture of a box |
| `relief.py` | `relief/` | `build(los_dir, tga, world, out_dir)` draws shaded terrain and solids at 0.5 m; needs baked LOS and `mapdata/*.tga` |
| `foliage.py` | `foliage/` | `analyse(src, out_dirs)` is the baker |

### `check_los.py`: `rmt.py check`
Not a baker: `score(check_csv, site, log)` walks every engine sight line from the `sightlines` job through the baked
`los/` tiles (`Tiles` loads them as needed, newest 48 kept) and prints how often they agree with the engine, for
objects and terrain, the bare terrain and bullets (`cover` plane). Returns the three shares.

### `fieldmap.py` and `trees.py`: `rmt.py fieldmap`
- `fieldmap.install(manifest, site, field_map, map_id, tiles, photos, log)`: one world's bake into the website:
  the files into `<field_map>/static/data/maps/<map_id>/` (the field map and its 3D view read the same ones), the 3D
  view's trees into its `trees/`, and its `map.json` (`map_entry`), which is how the site learns the map exists.
  `site_maps(field_map)` reads the site's `map.json` files and `site_map_id(field_map, slug)` finds a world's map id
  by the `slug` in them; title, 3D camera start, list order and `upstream` are kept from the `map.json` already there.
  `default_field_map(repo)` checks `../../arma-map/everon-map`; pass `--to` when the repos are siblings. `tuned_colours` reads the
  hand-tuned tree colours from the site's Everon tree table before the trees are rebuilt, and `build_trees` puts them
  back.
- `trees.build(objects, foliage, out, photos, log)`: the tree tiles and `species.json` (`rings_for` makes each kind's
  shape, `photo_colours` the optional colours). Byte-identical to everon-3d-map's old `build_trees.py` it was
  ported from.

`foliage.py` is also used while exporting: `plant_list(raw, out_csv, limit)` writes the list of plants to photograph,
and `bmp_to_png(folder)` converts the game's screenshots as they arrive.

## Conventions
- Ordinary `bake` functions take raw/site folders and a `log` function; imagery uses `build` and foliage analysis
  uses `analyse` with the input paths listed above. Each reports its own progress.
- Binary output is little endian, gzip level 6 to 9 with `mtime=0`, so rebakes are byte-identical.
- Coordinates are world metres, x east and z north; rows south to north, columns west to east.
- The core map grid comes from `probe.json`; downstream helpers have constraints. Relief expects 0.5 m surface
  cells, satellite/relief share a fixed tile coordinate scheme, and field-map tree colours are borrowed from Everon.
- Dependencies: standard library for ordinary export; `numpy` for bakers; `Pillow` for imagery and foliage;
  SciPy for foliage analysis and relief. Foliage capture also uses NumPy/Pillow helpers.

## Changing something safely
- New export job: see "Writing a new job" in [../docs/addon.md](../docs/addon.md), then add it to `JOBS` or
  `ALL_JOBS` in `export.py`.
- New baker: add a processing function, call it from `bake_parts()` in `rmt.py`, and add its name to the parser's
  `--parts` default/help and `products.py` plan when it belongs to a product. Update the format documentation.
- Run the regression suite from the repository root: `python -B -m unittest discover -p "test_*.py"`.
  It checks content-aware installation, map metadata, missing SciPy and terrain object classification.
  `test_sitesolver.py` is opt-in under discovery via `RMT_SITE` and needs Node plus the website's shot data.
  See [../docs/code-guide.md](../docs/code-guide.md) for validation commands and the engine-test boundary.

## Custom weapons and vehicle guns

The **Ballistics** GUI page uses `rmtgui/ballistics.py` and the worker CLI `customballistics.py`.
`rmtlib/ballistics.py` indexes installed addon prefabs, follows GUID references/inheritance, reports source physics,
loads selected addon dependencies and records direct projectile flights through the existing game test entity.
It writes separate datasets with provenance and resume signatures; it does not measure complete vehicle firing
or install custom tables into the website. Legacy Labs weapon lists are unchanged. See [../docs/custom-ballistics.md](../docs/custom-ballistics.md)
for workflow, file contracts, static-reader limits and the unverified live-mod engine boundary.


### Custom assets and complete website production

- `ballistics.py`: installed prefab/config catalog, dependency-scoped inheritance and ammo traversal; direct custom projectile flight plans and datasets.
- `sights.py`: sight component merging/traversal, Enfusion texture decoding, manual calibration validation and portable sketch export.
- `reticles.py`: the existing website's 16 gun/vehicle reticle geometries as portable SVGs.
- `webdata.py`: website input audit, native mortar plans/tables, blast/barrel conversion, construction registry extraction and curated recipe output.

Contracts and limits: [custom-ballistics](../docs/custom-ballistics.md), [sights](../docs/sights.md),
[website data](../docs/website-data.md). Curated constants live in [../recipes](../recipes/README.md).
