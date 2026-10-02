# `rmtlib/`: the Python library behind `rmt.py`

`rmt.py` (one folder up) only parses arguments. Everything it does is in these modules. Import them as
`from rmtlib import ...` from the repo root. The user-level docs are in [../docs](../docs/); this file is for
someone reading or changing the code.

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

Exporters never import bakers and bakers never launch the game. The only thing they share is the raw folder layout
described in [../docs/export-jobs.md](../docs/export-jobs.md).

## Modules

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

### Bakers (each has `bake(raw, site, log=print)`)

| Module | Output | Notes |
|---|---|---|
| `bake_roads.py` | `roads.json` | `build(roads)` makes the node and edge graph (`SNAP_M`, `TOUCH_M`, `EXTEND_M`, `SIMPLIFY_M` at the top set the joining rules); `material_kind` types road pieces when there is no `.topo` |
| `bake_los.py` | `los/`, `light/` | `Grid` reads the chunk grid and units from `probe.json`; `bake_chunk` makes one tile; `light_cells` and `bake_lz` make the 10 m grids |
| `bake_places.py` | `places.json` | `strings()` reads the English string table out of the paks; `MDT`, `TOWNS`, `LANDMARKS`, `SKIP` map descriptor types |
| `bake_plants.py` | `foliage.json`, `plants/`, light foliage and clutter | needs the `los` and `foliage` bakes first |
| `satellite.py` | `tiles/` | `build(shots_dir, terrain_raw, out_dir)`; `mosaic(...)` renders one test picture of a box |
| `foliage.py` | `foliage/` | `analyse(src, out_dirs)` is the baker |

### `check_los.py`: `rmt.py check`
Not a baker: `score(check_csv, site, log)` walks every engine sight line from the `sightlines` job through the baked
`los/` tiles (`Tiles` loads them as needed, newest 48 kept) and prints how often they agree with the engine, for
objects and terrain, the bare terrain and bullets (`cover` plane). Returns the three shares.

### `fieldmap.py` and `trees.py`: `rmt.py fieldmap`
- `fieldmap.install(manifest, site, field_map, map_id, tiles, photos, log)`: one world's bake into the website:
  the files into `<field_map>/static/data/maps/<map_id>/` (the field map and its 3D view read the same ones), the 3D
  view's trees into its `trees/`, and the map's entry in `<field_map>/static/3d/maps.json` (`map_entry`).
  `MAPS` maps world slugs to the site's map id, title and 3D camera start (`MAP_IDS` is just the ids);
  `default_field_map(repo)` finds `arma-map/everon-map` beside the repo's folder. `tuned_colours` reads the
  hand-tuned tree colours from the site's Everon tree table before the trees are rebuilt, and `build_trees` puts them
  back.
- `trees.build(objects, foliage, out, photos, log)`: the tree tiles and `species.json` (`rings_for` makes each kind's
  shape, `photo_colours` the optional colours). Byte-identical to everon-3d-map's old `build_trees.py` it was
  ported from.

`foliage.py` is also used while exporting: `plant_list(raw, out_csv, limit)` writes the list of plants to photograph,
and `bmp_to_png(folder)` converts the game's screenshots as they arrive.

## Conventions
- Every `bake` takes the raw folder and the site folder and a `log` function; all of them print their own progress.
- Binary output is little endian, gzip level 6 to 9 with `mtime=0`, so rebakes are byte-identical.
- Coordinates are world metres, x east and z north; rows south to north, columns west to east.
- Nothing here has Everon-specific constants: size, origin and chunk grid come from `probe.json`.
- Dependencies: standard library for export; `numpy` for bakers; `Pillow` for `satellite.py` and `foliage.py`.

## Changing something safely
- New export job: see "Writing a new job" in [../docs/addon.md](../docs/addon.md), then add it to `JOBS` or
  `ALL_JOBS` in `export.py`.
- New baker: add a module with `bake(raw, site, log)`, call it from `bake()` in `rmt.py`, and add its name to the
  `--parts` help text.
- There is no automatic test suite. A cheap check after any change: `python -m py_compile` on the file, then
  `python rmt.py --help`.
