# Reapply these changes after replacing the checkout

Updated 2026-10-05. Keep the complete patch and this checklist outside the folder you delete. The patch
is relative to the final Git baseline, which already contains most of the implementation. A full source snapshot
`reforger-tools-complete-source.zip` and `reforger-tools-source-manifest.json` are also saved outside the repository.
Use that snapshot to recover the whole implementation independently of the baseline. It excludes `.git`,
`.venv`, generated exports and game/mod assets; it includes the source, addon scripts, docs and recipes.

## Apply and verify

1. Clone the repository and enter its root. The final patch base is `cae8cad` (initial commit). The earlier
   `4608948` history was replaced during this session; verify your current commit before applying the patch.
2. Run `git apply --check <path-to-reforger-tools-complete-redo.patch>`, then `git apply <same-path>`.
   If your fresh clone has a different baseline, extract the complete source snapshot into a separate folder
   and compare/copy its files into the new checkout using the source manifest and this guide. Keep the new
   checkout’s `.git` folder. Review conflicts against upstream changes; do not discard newer code.
3. Install `requirements.txt` or start `Reforger Map Tools.bat` to prepare the GUI environment.
4. Run `python -B -m unittest discover -p "test_*.py"` and inspect skipped tests.
5. Run `python webdata.py audit --site "../arma-map/arma-map" --output out/website-audit`.
6. Start/restart the GUI. Confirm Website data, Ballistics and Sights appear. Check Setup before engine work.
7. For engine verification, `python webdata.py mortar --output out/website-mortar` compiles/runs Workbench;
   inspect done status, all expected configurations and the resulting tables. Do not replace website data
   until reviewed. Arbitrary mod flight/sight calibration requires an appropriate in-game validation.

## Implementation to preserve

- `customballistics.py`, `rmtlib/ballistics.py`, `rmtgui/ballistics.py`, `test_custom_ballistics.py`:
  mod prefab/config catalog, scoped GUID/inheritance, muzzle selection and separate recorded flight datasets.
- `sighttools.py`, `rmtlib/sights.py`, `rmtgui/sights.py`, `test_sights.py`:
  separate vehicle/weapon/optic sorting, component inheritance, mounted reference traversal, ENF1 COPY/LZ4
  reticle decoding, calibration, fingerprint guard and portable SVG/PNG/JSON/JS/HTML export.
- `webdata.py`, `rmtlib/webdata.py`, `rmtlib/reticles.py`, `rmtgui/website.py`, `test_webdata.py`:
  complete website input audit, mortar plan/table/physics generation, blast/barrel converters,
  construction registries and legacy reticle/calibration recipes.
- `recipes/website-calibration.json`, `recipes/legacy-reticles.js`, `recipes/README.md`:
  preserve provenance and clearly distinguish historical/manual constants from new measurements.
- `addon/Scripts/WorkbenchGame/RMT/RMT_MortarTablesJob.c` plus export-plugin dispatch and
  `rmtlib/export.py` job list: expose ballistics and mortar_tables; prepare native sampling plan.
- `rmtgui/app.py`, `rmtgui/labs.py`: new pages and Conflict workflow, worker wiring, Workbench status/checks.
- `rmtlib/fieldmap.py`: discover current nested website and legacy layouts.
- `ReforgerMapTools.spec`: bundle recipes and new CLI/library/page modules.
- README files and `docs/`: preserve the updated code guide, custom-ballistics, sights, mod-assets,
  website-data, GUI, export, bakers, audible and this redo checklist.

## Evidence and boundaries

The current website audit classified 73,950 static data files with zero unknown producers. Native Workbench
mortar extraction completed 31 configurations and 417 rows. Vanilla, RHS and WCS reticles were decoded;
RHS PSO1 uses a 4096-pixel, 13-mip container. Vehicle default crew equipment is excluded from mounted discovery.
Tests validate data contracts; they do not establish live accuracy of every installed mod or a packaged build.
New mod packages need website selector/schema integration. Runtime rooms, sessions, bans and caches are website
runtime state, not Reforger source data. Read [code-guide.md](code-guide.md) and [website-data.md](website-data.md).


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


## Selected Labs update

Preserve `labtest.py`, `rmtlib/labselection.py`, `rmtgui/labtargets.py`, `test_lab_selection.py` and
`docs/labs-selection.md`. Retain the `rmtgui/app.py` / `labs.py` worker routing, selected Runner calls in
fire/blast/rocket/launcher scripts, inherited-source filtering in `rmtlib/ballistics.py`, selected coefficient
handling in rocket checks, and partial-calibration support in `rocketfit.py`. Preserve the launcher addon's
`expectedProjectile` column check: it prevents scoring the wrong carried ammunition.

All Labs categories now expose installed target selection; helper categories select samples, addons or test
modules. Mortar selected planning obtains native tables with mod dependencies. Reports use recorded physics,
resume checks current sources, and fitting rejects incomplete wind blocks or missing trajectories. Custom
mortar dispersion remains unknown until measured. The game compiled the addon and a selected Chungus mod
rocket completed one shot with 30 trajectory frames. Full modded mortar/launcher suites remain unverified.
After recovery, scan Labs targets, choose a mod, inspect its pairings, save/load the recipe and check the
command preview. Run the regression suite before launching measurements.
