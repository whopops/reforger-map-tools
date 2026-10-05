# Custom weapons, ammunition and vehicle guns

World selection lists world files, not weapons. Weapon mods often ship `.ent` test scenes or asset-image worlds;
their presence there does not enable modded ballistic extraction. The legacy Labs bullet/rocket lists remain
fixed to base-game ammunition. Use the separate **Ballistics** page for custom projectiles.

## GUI workflow

1. Download the mod and all its dependencies through Arma Reforger. Restart this GUI after updating its code.
2. Open **Ballistics**, press **Scan installed addons**, and filter by addon, type, weapon name or calibre.
3. Select a weapon, vehicle or ammunition prefab and press **Inspect selection / find ammunition**.
4. Pick a discovered projectile. Inspection shows inherited physics values and the prefabs they came from.
   If automatic reference discovery cannot find ammo, select the ammunition prefab directly using the catalogue.
5. Verify the gun's `BulletInitSpeedCoef` and enter it as the launch-speed coefficient. Ammo's `InitSpeed` is
   multiplied by this value. Vehicles may have several guns/muzzles with different coefficients: inspect source
   values and choose explicitly. A single coefficient found on the selected prefab is offered as a starting value;
   it is not proof that it belongs to the chosen muzzle. Tick the verification checkbox once checked.
6. Choose a dataset name, flight duration (3–30 seconds), launch height and test world. Default is EmptyEden at
   5,000 m above sea level, independent of website terrain files. The world must have adequate space and a weather
   manager for wind runs. At extreme speed/downward elevation increase the height or shorten the recording.
7. Press **Record custom ballistics**. The game opens for calm and four wind cases (or calm only); progress and
   cancellation use the existing Run page. Do not interact with the game while recording.

The runner loads the owning weapon/projectile addons and their transitive dependencies. Missing dependencies or
ambiguous resources fail explicitly. Inspect/scan use installed files and do not start Workbench or the game.
Catalogue classifications use file paths; unusual mod layouts are available under **All prefabs**. Inheritance
and references are resolved by resource GUID when present. Binary/compiled prefabs cannot be statically inspected
by this reader, and missing source is reported rather than inferred.

## What is measured

The existing `RMT_FireTest` spawns the projectile and calls the game's movement component directly, with the selected
coefficient. It records launch velocity and position/velocity samples, then builds flight/drop/time/wind tables.
This supports ordinary bullet, shell and unguided rocket movement components, including ammunition used by vehicle
guns. It does not spawn and fire the whole vehicle or measure its sight zeroing, turret dynamics, muzzle dispersion,
damage/penetration, attachments or scripted firing behavior. Guided missiles and unusual scripts require separate
validation. These paths have Python tests; live modded engine measurements have not yet been validated.

Inspection preserves source provenance and multiple numeric values instead of guessing a vehicle's selected muzzle.
Discovery follows referenced `.et` prefabs and `.conf` ammunition configurations to depth 8 / 500 resources. Mod scripts, unsupported external resources and
runtime loadouts may need manual ammunition selection. A projectile that dies before two seconds can leave raw
CSV results but may not be tableable by the current fitter. Recorded duration is a sampling limit, not necessarily
the projectile's natural lifetime.

## Results and resume

Results go under the Data page's output folder, `ballistics/<dataset>/<signature>/`:

- `manifest.json`: resource and addon identity, inherited physics, explicit coefficient, engine builds, world,
  recording settings, addon-file fingerprints and the exact plan.
- `ballistics.json`: the measured `rounds` table, whether winds were recorded and measurement limitations.
- Raw `plan.csv`, `plan.json`, `shots.csv` and `traj.csv` stay in the game profile at
  `rmt/custom-ballistics/<dataset>/<signature>/w<N>/firetest/` (the manifest gives the absolute path).

Matching completed wind runs resume. Changed settings or addon fingerprints select a new signature, preventing
reuse of measurements for another coefficient or mod version. Missing trajectory coverage fails instead of
exporting a partial round table. Calm-only results omit wind fields so they cannot masquerade as measured wind data.
Results are separate custom datasets; they do not replace base-game `bullets.json`/`rockets.json` or install into
the website automatically. Website integration needs an explicit importer and weapon/ammo identity mapping.

## CLI and code

```powershell
python customballistics.py scan --output out/ballistics/catalog.json
python customballistics.py inspect --resource "{RESOURCE_GUID}Prefabs/Weapons/MyWeapon.et" --addon ADDON_GUID --output out/ballistics/inspect.json
python customballistics.py run --resource "{RESOURCE_GUID}Prefabs/Ammo/MyRound.et" --addon ADDON_GUID --name my-round --coefficient 1 --output out/ballistics
```

GUID values in these examples are placeholders: copy the actual resource and owning addon from the catalogue.
`--weapon` and `--weapon-addon` optionally load/record the selected weapon's addon too. Use `--workbench` for the
Setup override, `--duration`, `--height`, `--world` or `--calm-only` to adjust recording.

Code: `customballistics.py` is the worker CLI; `rmtlib/ballistics.py` owns discovery, provenance, plans and capture;
`rmtgui/ballistics.py` owns the page. Existing `Runner`, `RMT_FireTest`, `rockettest.flights_in` and `rocketfit.tables`
provide engine execution and fitting. No new Enforce API is assumed. Verify with
`python -B -m unittest discover -p "test_*.py"`, an offscreen GUI build and a limited live modded-ammo recording.
