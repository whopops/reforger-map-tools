# Producing every arma-map website input

`reforger-map-tools` owns game-data extraction, baking, measurements and calibration exports. `arma-map` owns the
web server and browser application. The current website application is `arma-map/arma-map/` (contains `server.py`);
older layouts used `arma-map/everon-map/`. Nearby discovery accepts both. Never choose the outer repository folder
when a nested application contains `server.py`.

The desktop **Website data** page is the coverage checklist and entry point. Set **Data → field map folder**,
then **Audit selected website**. `website-audit.json` maps current `static/data` files to their producers, counts
files/bytes and reports unknown inputs. Audit checks coverage, not freshness, completeness of a new bake or accuracy.

## Producer map

| Website input | Producer | GUI workflow |
|---|---|---|
| `maps/<id>/map.json` | `rmtlib/fieldmap.py` | Data: install bake into field map |
| `roads.json` | roads/mapdata export → `bake_roads.py` | Data: Roads |
| `places.json` | names export → `bake_places.py` | Data: Place names |
| `los/*.bin.gz`, `los/index.json` | entities/terrain/surface export → `bake_los.py` | Data: Terrain, objects and line of sight |
| `light/*.bin.gz` | `bake_los.py` | Same LOS workflow; height, forest, canopy, buildings, landing zones, foliage and clutter |
| `plants/*.bin.gz`, `foliage.json` | entities + photographed shapes → `bake_plants.py` | Data: Trees and foliage |
| `foliage/foliage_profiles.json` | foliage capture → `foliage.py` | Data: Trees and foliage |
| `trees/*.bin.gz`, `trees/species.json` | `trees.py`, installed by `fieldmap.py` | Data: install into field map |
| `trees/models.json`, `trees/models.bin.gz` | `python -m rmtlib.tree_models <map folder>` (from the game's meshes) | command line |
| `tiles/z/x/y.jpg` | satellite capture → `satellite.py` | Data: Satellite imagery |
| `relief/z/x/y.jpg` | mapdata raster + LOS → `relief.py` | Data: Relief map |
| `<map>.json`: bases, HQs, supplies, spawns, repair/refuel, FIA cache references | Conflict job → `bake_conflict.py` / `conflict.py` | Website data → Conflict references (Labs) |
| `mortar-tables.json` | `webdata.py mortar` → engine `RMT_MortarTablesJob` | Website data: Mortar reference tables |
| Mortar shell physics formerly embedded in `3d/mortar.js` | `webdata.py mortar` / `mortar-plan` | Same; writes `mortar-physics.json` |
| Measured mortar speed variation / barrel spread | `firetest.py barrel`, then `webdata.py barrel` | Labs: muzzle study; Website data: convert study |
| `rockets.json`, including measured launcher sight marks | `rockettest.py` + `rocketfit.py` | Labs: Rocket flight test, score, check |
| `bullets.json` | `bullettest.py` + `rocketfit.py` | Labs: Bullet flight test, score, check |
| Custom ammo flight data | `customballistics.py` | Ballistics: inspect and record; separate dataset |
| Sound reach formerly embedded in `app.js` | `audible/audible.py`, then `audible/audible3.py` | Labs: Gunshot audibility steps 1/2; `audible.json` |
| Blast zones formerly embedded in `app.js` | `blasttest.py`, then `webdata.py blast` | Labs: blast test/score; Website data: summary conversion |
| Optic scale, zeroing, range marks and artwork | `sighttools.py`, `rmtlib/sights.py` | Sights; see [sights.md](sights.md) |
| Existing calibrated sight definitions / SVG sketches | `rmtlib/reticles.py`, `recipes/website-calibration.json` | Website data: curated recipe export |
| Construction registry membership and role mapping | `webdata.py construction`, curated role recipes | Website data: Construction registry |
| Hand-marked caves / tuned tree colours | reviewed calibration recipes | Website data: curated recipe export; preserve/edit manual values intentionally |

This accounts for the current website's **73,950 static data files** in the 2026-10-05 audit. A later website can
introduce inputs: audit again; an unknown file is a coverage gap, not permission to silently classify it as Conflict.

`rooms.json`, `bans.json`, browser plans, `compressed_cache`, `tile_cache` and `/api/maps` / `/3d/maps.json` are
runtime/server-derived state. They are not game export products. Landing artwork, icons, schematic construction
shapes, UI labels and solver algorithms are application assets/code rather than measured datasets.

## Workflow

1. On **Data**, choose **Full map export**, the world and a website map ID, then export/bake/install. A complete
   regeneration needs full satellite and foliage captures, not Quick test or a partial chunk run. To replace upstream
   Everon tiles, capture/install local tiles and review the old `upstream` setting.
2. Use **Conflict references** for that world's scenario after map installation. `conflict.py` currently resolves
   `CTI_Campaign_<world>` by convention; a custom scenario needs an explicit scenario-capable exporter/adaptation.
   Caves are hand-marked and preserved from existing website data. Curated baseline cave coordinates are exported
   separately; merge them deliberately when rebuilding a brand-new site.
3. Produce mortar tables/physics, rocket and bullet flights, measured dispersion, blast and sound results. Run each
   tool's validation/check as documented. Existing Labs can copy scored `rockets.json` / `bullets.json` into the site.
4. Extract/calibrate custom sights and connect them to custom ammo. Export curated recipes to reproduce existing
   legacy reticle sketches and manual values.
5. Review output, install the compatible datasets, and audit again. Website changes are required to consume new
   custom weapons/sight packages and refreshed JSON equivalents of embedded JavaScript constants. These new
   exports do not patch JavaScript or automatically expand client/server weapon whitelists.

## Reference/calibration commands

```powershell
python webdata.py audit --site ../arma-map/arma-map --output out/website-data
python webdata.py mortar --output out/website-data
python webdata.py mortar-plan --output out/website-data
python webdata.py barrel --input "<completed muzzle-study folder>" --output out/website-data
python webdata.py blast --input "<blast run>/summary.json" --output out/website-data
python webdata.py construction --output out/website-data
python webdata.py recipes --output out/website-data
```

`mortar` launches Workbench on EmptyEden and uses `BallisticTable.GetHeightFromProjectileSource`, the game's own
lookup. Its plan derives shell prefab, coefficient/ring, range bounds/step, units and dispersion from the game's
ballistic-page configs. `mortar-plan` extracts physics/plans without launching. It writes plans under the Workbench
profile and result JSON in the chosen output folder. Completed engine status plus valid rows for **every** planned
ring are required. It exports all seven vanilla shells; it does not discover arbitrary modded mortar page sets.

`mortar-tables.json` retains the website's weapons/shells/rings/table schema and four column names. Dispersion is
the current game config's standard value; it differs from a separately measured 90% spread or a curated prior
table. The shared solver's physics/spread constants must be refreshed consistently when adopting new measurements.
`mortar-physics.json` preserves move-component mass, drag, speed and ring coefficients rather than grabbing a
different mass from the item's rigid body.

`blast` selects standing/unconsciousness-enabled results: `down50` → kill radius and `hurt10` → danger radius;
missing/nonfinite fits fail. `barrel` writes per-weapon base-speed mean/SD and angular up/side SD in radians from
complete muzzle samples. The website currently uses shared speed constants, so adopting per-weapon results may
require a reviewed solver adaptation. Do not average them implicitly.

`construction` extracts both vanilla building registries, includes the curated role for known prefabs, and reports
unmapped new entries. It does not measure construction collision/footprint, costs or rank restrictions. Recipes
include the 104-prefab/26-role mapping, sight definitions, sound/blast baselines, mortar baselines, cave coordinates
and tree colours, with snapshot provenance. Regenerating a recipe does not turn an old calibration into a new
measurement. The website source is not required to export these recipes after cloning this repo.

## Verification

2026-10-05: actual Workbench compilation and mortar lookup completed: 31 configurations, 417 valid rows, exit/status
success. Read-only inspection verified installed vanilla and multiple mod optics and WCS M2A2 turret references.
The audit reported no unknown existing static data files. Python tests cover inventory drift, nested imagery,
schema/completeness, calibration and component identity. Full map captures and live modded flight/guidance are
long-running measurements and have not been rerun by this coverage review.
