# Code guide for AI models and contributors

Reviewed against this checkout on 2026-10-05. This is a quick architecture map, not a substitute for reading the
functions affected by a change. Update it when commands, formats or responsibilities change.

## Purpose and boundaries

This Windows Python project extracts Arma Reforger world data using Workbench and the game, then converts it into
files consumed by the separate `arma-map/arma-map` website. It also has a PySide6 desktop frontend and standalone
live-fire and sound-analysis tools. It does not serve or deploy the website.

The map pipeline uses world bounds from a probe. The live-fire tools use Everon and the website's existing terrain
and weapon tables; do not assume every script is map-independent. Engine runs require installed Steam/game/Tools.

## Read in this order

1. [../README.md](../README.md): setup and supported commands.
2. `rmt.py`: CLI parser, dispatch, newest-export selection, bake/check/install/run orchestration.
3. `rmtlib/products.py`: product dependencies and ordered execution plans.
4. `rmtlib/export.py`, then `rmtlib/workbench.py`: resolution, manifests, retry/resume, launches and supervision.
5. The relevant baker and matching addon job; follow the table below.

Detailed contracts: [export-jobs.md](export-jobs.md), [bakers.md](bakers.md), [addon.md](addon.md).

## Execution flow

```text
Batch launcher -> rmt_gui.py -> rmtgui/app.py
                                  |
                           rmtgui/worker.py (QProcess)
                                  |
CLI --------------------------> rmt.py
                                  |
 run -> products.plan -> Exporter.export -> Runner -> generated addon -> engine
                                  |                              |
                                  |                     raw CSV/images/status files
                                  v
                          bake_parts -> site/ -> score_los / install_site
```

`rmt.py export` accepts jobs directly; it does not expand product dependencies. Workbench jobs run in the supplied
order in one world load, followed by separate game launches for satellite and foliage. Put `probe` first when
needed. `rmt.py run` expands dependencies and orders everything using `products.plan`, then exports, bakes,
optionally scores LOS, and optionally installs. `--install` adds roads, LOS, places and foliage to the plan.

`bake`, `check` and `fieldmap` normally select a manifest using `newest_export`: newest **manifest modification
time**, not highest numeric build id. Matching accepts the resource, resource without GUID, slug or world file stem.
`check --csv ... --site ...` can bypass manifest lookup. A low-level `bake` uses a fixed part order and does not add
dependencies or validate unknown part names. Missing satellite/relief/foliage input can be reported as skipped while
`bake` returns success; `run` treats these missing inputs as failure. Other missing inputs can raise errors.

## Python responsibilities

| Files | Responsibility |
|---|---|
| `rmt.py` | Public CLI; `dispatch`, `newest_export`, `bake_parts`, `score_los`, `install_site`, `run`; guarded JSON error reporting with `--events` |
| `rmtlib/products.py` | `PRODUCTS`, closure of dependencies, job/bake order, GUI step plan |
| `rmtlib/export.py` | `Exporter.resolve/export/list_worlds`, slug, manifest, retries, satellite camera arguments, foliage capture preparation |
| `rmtlib/workbench.py` | Generated addon, `Runner` (`Workbench` alias), launch arguments, log supervision, process-tree cleanup, video-settings backup/restore |
| `rmtlib/steam.py`, `addons.py`, `detect.py` | Steam registry/library discovery and profiles; resource database indexing and mod dependencies; Setup diagnostics |
| `rmtlib/paths.py`, `events.py` | Source/bundle/workspace paths; JSON-line events and `RMT\|` heartbeat translation |
| `rmtlib/topo.py`, `pak.py`, `prefab.py` | BI binary map geometry; archive index/read CLI; prefab inheritance/value lookup |
| `rmtlib/fieldmap.py`, `trees.py` | Install a bake into the website, preserve existing metadata, generate shaped 3D tree records/species |
| `rmtgui/app.py`, `theme.py` | Setup, World, Data, Run, Website data, Ballistics, Sights, Past runs and Labs pages; settings, UI state and appearance |
| `rmtgui/worker.py`, `labs.py` | Child-process execution/cancellation and JSON-to-Qt signals; declarative Labs forms/commands |
| `rmt_gui.py` | GUI entrypoint and packaged console worker; `--worker`, `--script`, `--module` modes; script output/error wrapping |

## Products and data transformations

Every plan includes its products' required jobs; `foliage`, `relief` and `check` also depend on LOS.

| Product | Raw jobs/inputs | Python processing and outputs under `site/` |
|---|---|---|
| roads | probe, mapdata, roads | `bake_roads.py` + `topo.py`: `.topo` roads preferred, road pieces fallback; joined/simplified graph in `roads.json` |
| los | probe, entities, terrain, surface | `bake_los.py`: classify objects, combine ground/roof/canopy/cover; `los/` chunks and whole-map `light/` grids |
| places | probe, names; installed game paks | `bake_places.py`: English string-table resolution; `places.json` |
| satellite | probe, terrain, game screenshots | `satellite.py`: terrain-aware perspective sampling and JPEG pyramid in `tiles/` |
| relief | probe, mapdata, baked LOS | `relief.py`: multiscale shading of ground/buildings/solids, BI raster for sea; JPEG pyramid in `relief/` |
| foliage | probe, entities, game plant photos; baked LOS | `foliage.py` measures shown/hidden photo pairs into `foliage/`; `bake_plants.py` joins profiles to instances into `foliage.json`, `plants/` and foliage/clutter light grids |
| check | probe, sightlines, baked LOS | `check_los.py`: walk engine rays through baked planes, report agreement; this is scoring, not a pass/fail threshold |

`conflict.py` is separate from these products. It resolves a terrain's `CTI_Campaign_<stem>` scenario, exports
`conflict`, calls `bake_conflict.py`, writes `site/conflict.json` under the scenario's workspace run, and optionally
installs `static/data/<map id>.json`. It keeps hand-authored `caves` from the existing installed file.

## Engine side and Python/Enforce contract

Source is `addon/Scripts/`; `.build/ReforgerMapTools` is disposable generated output. `build_addon` copies scripts
and writes an addon project with the base game and required mod GUIDs. Edit source, never generated copies.

| Engine file | Role |
|---|---|
| `WorkbenchGame/RMT/RMT_ExportPlugin.c` | `RunCommandline`: load world, dispatch jobs, begin/end heartbeat, exit; probe/mapdata/worlds live here |
| `RMT_Context.c` | Argument parsing, bounds/grid, profile directories, status writing; `RMT_ChunkJob` handles region, limits and `.ok` resume markers |
| `RMT_GridJobs.c` | Terrain height sampling, entity CSVs, surface rays |
| `RMT_WorldJobs.c` | Road pieces/splines, map labels, sightline validation rays, Conflict entities/settings |
| `RMT_FoliageTrace.c`, `RMT_BallisticsJob.c` | Experimental foliage rays; engine shell-flight table (`ballistics` is accepted by `rmt.py export --jobs`) |
| `Game/RMT/RMT_GameHook.c` | `OnWorldPostProcess` flags spawn the matching game capture/test entity |
| `RMT_SatCapture.c`, `RMT_FoliageCapture.c` | Frame-driven image capture, metadata, resumable plant photography |
| `RMT_FireTest.c`, `RMT_GunTest.c` | Direct projectile launches vs rounds fired through a real mortar; plan/shot/trajectory/muzzle measurements |
| `RMT_BlastTest.c`, `RMT_LauncherTest.c` | Blast victims/damage; real soldier launcher aiming/firing/tracking |

Paths in this table are relative to `addon/Scripts/`; Workbench filenames after the first row share
`WorkbenchGame/RMT/`, game filenames share `Game/RMT/`.

Launch settings are `-rmtNAME=VALUE`; Python `--set NAME=VALUE` forwards them. Scripts write under `$profile:`;
writes elsewhere can trigger a blocking authorization dialog. Jobs report `<job>.status.json`, with `result`
`done`, `partial` or `failed`, and print `RMT|` heartbeat lines. Python removes stale status files before launch,
watches the fresh console log, and kills stalled process trees. Compile failures stop retries; failure to load a
world exits early. `--retries` is the total attempt count, not extra retries. Partial chunk jobs are accepted as
successful test runs, so exit 0 does not guarantee a whole-map export. `.ok` markers skip completed chunks;
changing sampling settings does not automatically invalidate them. Use a deliberately separate export when
changing grid/settings, and inspect status and coverage before installation. Raw exports are not deleted by rmt.

## Storage and format contracts

| Location | Contents |
|---|---|
| `out/<slug>/<game build>/` | Manifest and baked `site/`; override via `--workspace` or `RMT_WORKSPACE` |
| Workbench profile `rmt/<slug>/<build>/` | `probe.json`, raw objects/terrain/surface/roads/names/mapdata/sightlines and status files; manifest `raw` points here |
| Game profile `rmt/<slug>/<build>/` | Satellite and foliage photos/metadata; separate from Workbench raw path |
| Website `static/data/maps/<id>/` | Installed shared 2D/3D data and `map.json`; target must contain `server.py` |
| `%LOCALAPPDATA%/ReforgerMapTools/` | Packaged build directory, video-independent app files and GUI crash log; Qt settings are in the registry |

The slug is a sanitized lowercase world stem, plus the first six GUID characters when present. Profile discovery
uses the real Windows Documents location, including redirection; `--workspace` does not relocate engine exports.
In a packaged app, the default workspace is `~/Documents/ReforgerMapTools`, with source assets in the bundle.

World positions are metres: x east, z north, y elevation. Grid arrays are rows south to north, columns west to
east. Compressed binary map arrays are little endian with deterministic gzip timestamps. LOS chunks concatenate
terrain Uint16, then top/bottom/kind/cover Uint8 planes; sizes and units come from `los/index.json`, not guesses.
Object kind is a separate plane from underside height. See [bakers.md](bakers.md) for complete layouts including
plants, light grids and the eight-byte 3D tree records. Satellite/relief use a shared fixed tile scheme, with
fine URL zoom 0 and progressively coarser levels. Relief requires 0.5 m surface cells.

Installation compares directory-file contents before skipping unchanged files, including same-size/same-time
edits. It merges directories rather than purging old files; missing optional output stays as it was. `map.json`
keeps existing custom fields such as `upstream`, title/start/order, and refreshes measured grid fields and
`hasTrees`/`hasRelief`. A new map needs `--as`; existing ids are found by slug. Automatic website discovery searches the repository and three ancestors for nested `arma-map/arma-map`,
legacy `arma-map/everon-map` and direct applications; in the current sibling-repository layout pass `--to "../arma-map/arma-map"`. Upstream satellite tiles are copied
only with `--tiles`. Tree rebuilding needs raw objects and foliage measurements. Tuned colours are read from the
installed Everon species table before rebuilding; retain that table if those colours matter.

## Standalone experiments

These `*test.py` files are experiment CLIs, not unittest files:

| Script | Function |
|---|---|
| `firetest.py` | Mortar solver/terrain loader, aim plans, direct firing, repeat groups, real gun and barrel study, scoring |
| `blasttest.py` | Victim layouts, shell plans, game blast runs, damage/radius fits |
| `rockettest.py` | Rocket flight plans across winds; resumable blocks; tables and solver checks/twin flights |
| `rocketfit.py` | Fit/interpolate trajectories and wind response; Python copy of the site's rocket/bullet solver |
| `bullettest.py` | Bullet flight/check plans using rocket-test infrastructure; bullet table generation |
| `launchertest.py` | Real launcher soldier plans, bore/sight measurements, flight/hit scoring |
| `audible/*.py` | Pak indexing, WAV loudness, spectra, assumed-noise audibility estimates; run from `audible/` |

See [firetest.md](firetest.md) for commands and result contracts. Some Labs commands write into the engine profile
even when only planning, and some score commands update website weapon tables. Read the relevant command branch
before running it. `firetest --site` expects `static/data`, whereas `rmt fieldmap --to` and solver parity `--site`
expect the website root. Audible has its own hard-coded install path/cache; it does not use Steam discovery and
does not automatically install `audible.json`. Its `S.npy`/`N.npy` must be generated before the reach table.

## Validation and change map

From the repository root, using an interpreter with `requirements.txt` installed:

```powershell
python -B rmt.py --help
python -B rmt.py bake --help
python -B rmt.py run --help
python -B -m unittest discover -p "test_*.py"
```

`test_bake_regressions.py` checks content replacement, unchanged files, metadata preservation/new-map install and
early missing-SciPy failure. `test_firetest.py` checks terrain object-plane classification. `test_sitesolver.py`
compares Python with website `static/shot-core.js` in Node; unittest discovery opts in only when `RMT_SITE` is set.
Even then its CLI skips if Node/core/rocket/bullet files are missing, so read the output before claiming parity.
For an explicit comparison in the sibling-repository layout:
`python -B test_sitesolver.py --site "../arma-map/arma-map"`. Always pass the site path: its default also
assumes the older nested checkout layout.

Python tests do not validate Enforce compilation, live game rendering, real projectile physics, or mod loading.
Engine-affecting changes need a small actual job/test. Do not call a partial run a complete-map validation.

| Change | Update/check together |
|---|---|
| Export job | Addon dispatch/class/status/heartbeat, `export.ALL_JOBS`, optional `CHUNK_JOBS`, product plan and export docs |
| Product or baker | `products.PRODUCTS`/orders/labels, `rmt.py` parser and `bake_parts`, GUI assumptions, output docs |
| CLI option | Parser, worker/Labs command construction, help examples and relevant README |
| Binary schema | Producer, index metadata, website consumer, format/version and regression coverage |
| Shot solver | `rocketfit.py`, external site's `shot-core.js`, parity check, game check plans |
| Packaging | `ReforgerMapTools.spec`, bundled scripts/data/imports, `.github/workflows/package.yml`, packaging docs |

The batch file creates `.venv`, installs dependencies when its saved requirements copy differs, then opens the
window. Packaging builds two executables sharing `_internal`: the window and console `rmt.exe`, both using
`rmt_gui.py` entry dispatch. The workflow builds on Windows and checks help, JSON diagnostics, self-tests and
offscreen GUI startup. This workflow definition is not evidence that a particular release or live engine run passed.

## Custom weapons and vehicle guns

The **Ballistics** GUI page uses `rmtgui/ballistics.py` and the worker CLI `customballistics.py`.
`rmtlib/ballistics.py` indexes installed addon prefabs, follows GUID references/inheritance, reports source physics,
loads selected addon dependencies and records direct projectile flights through the existing game test entity.
It writes separate datasets with provenance and resume signatures; it does not measure complete vehicle firing
or install custom tables into the website. Labs uses explicit baseline/mod selections; standalone scripts retain their baseline presets. See [custom-ballistics.md](custom-ballistics.md)
for workflow, file contracts, static-reader limits and the unverified live-mod engine boundary.

Ballistics resource indexing streams archive directory chunks instead of reading entire paks. Reference traversal
includes ammunition `.conf` files; resource overrides are scoped to the selected addon and its dependencies,
so an unrelated installed weapon pack cannot silently change inspected physics. `test_custom_ballistics.py`
checks identity isolation, inheritance, config traversal, missing dependencies, multiple muzzle values, plans
and rejection of an engine success status without trajectory files.


## Website production and sight tooling (current implementation)

Start with [website-data.md](website-data.md) for the complete consumer-to-producer inventory. The website
application is currently `../arma-map/arma-map`, containing `server.py`; `static/data` alone is not the application
root. `webdata.py audit` classifies files and flags unknown inputs or absent producers. Current audit: 73,950 files,
zero unclassified files. This verifies coverage, not the quality of every generated measurement.

| Entry/module | Responsibility |
|---|---|
| `webdata.py`, `rmtlib/webdata.py`, `rmtgui/website.py` | Audit; fresh engine mortar tables/physics; blast and barrel report conversion; construction registries; curated recipes |
| `sighttools.py`, `rmtlib/sights.py`, `rmtgui/sights.py` | Mod sight discovery, component inheritance, dependency-scoped textures, ENF1 COPY/LZ4 decoding, calibration and portable export |
| `rmtlib/reticles.py`, `recipes/legacy-reticles.js` | Reproduce the website's 16 existing gun/vehicle sight sketches without the website checkout |
| `recipes/website-calibration.json` | Versioned curated cave points, tree colours, construction mapping, sound/blast/weapon/sight calibration snapshots; explicit provenance |
| `addon/Scripts/WorkbenchGame/RMT/RMT_MortarTablesJob.c` | Native BallisticTable sampling from a Python-generated shell/charge plan |

Mortar extraction resolves inherited ballistic-page configurations and ammunition physics, writes a CSV plan,
then launches Workbench with `-rmtMortarPlan`. Completion requires a fresh done status and usable rows for every
configuration. A real run on 2026-10-05 compiled and produced 417 rows for 31 configurations. It uses configured
standard dispersion, which is not interchangeable with the site's historical measured spread calibration.

Sight inheritance matches component GUID even when a mod changes concrete component class; channels remain
separate. Traversal excludes character/loadout references so default vehicle crew do not add personal rifle
sights. Archive scans exclude temporary downloads. ENF1 textures have a mip directory and reverse mip payload
order; raw LZ4 chunks share a dictionary. Tests cover corruption, overlap and COPY/mip selection.

Coordinates are source-image pixels; angle units are degrees. Aim and bore alignment require manual verification.
A texture centre is only an initial suggestion. Export checks finite calibration, bounds and the saved image
fingerprint before writing portable PNG/SVG/JSON/renderer/preview files. Schematic iron sights do not reconstruct
meshes. Arbitrary mod shader/script behavior and guided ammunition still need in-game validation.

The Website data page links map production and Labs' Conflict, bullet, rocket, blast, barrel and sound workflows.
Embedded browser constants are generated as reviewable JSON/SVG/JS recipes. New mod weapons still require website
selector/schema integration; producing a package does not automatically register it in the website.
`test_sights.py` and `test_webdata.py` cover these contracts. Packaged builds must bundle `recipes/` and all root
worker CLIs. See [changes-redo.md](changes-redo.md) before moving or replacing the checkout.


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


## Labs selection contract (current)

Read [labs-selection.md](labs-selection.md) before changing Labs. `rmtgui/labtargets.py` owns the category
checklists, addon/search filters, saved requests and resolved-projectile picker. `rmtgui/labs.py` describes
commands and routes all GUI categories through `labtest.py`. `rmtlib/labselection.py` catalogs installed
resources, resolves targets/dependencies/physics, hashes source identity and supplies the selected Runner.
`labtest.py` dispatches each category, configures legacy planners in an isolated worker process and keeps
measured outputs under a selection signature. Do not mutate module globals in the GUI process.

A request contains `tool`, nonempty unique `targets`, and optionally `projectiles`, `coefficient`,
`mortarWeapon`, `dataset`, `launchAngleDegrees`, `soundLevelLUFS` or `soldier`. A prepared recipe adds `items`,
`sourceHashes`, `guids`, `addonDirs`, `gameBuild`, `datasetHash` where applicable, and `signature`.
Direct ammo selection resolves the root projectile only. Inherited sources are merged, not treated as extra
rounds. Explicit weapon/vehicle inspection exposes pairings for the user's second selection.

Engine status must be done with completed shots and no skips. Launcher CSV appends `expectedProjectile`;
`RMT_LauncherTest.c` fails if another carried ammo prefab fires. Flight scoring requires all wind blocks
and every planned shot. Reports read saved physics; resume additionally verifies current source hashes.
Self-tests bypass Steam discovery. WAV and Pak targets are scoped to selected installed addons.
`test_lab_selection.py` validates these contracts; `test_asset_selection.py` covers resource classification.
See the redo checklist for source recovery and verified game smoke-test limits.
