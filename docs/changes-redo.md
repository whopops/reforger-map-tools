# Reapply these changes after replacing the checkout

Updated 2026-10-05. Keep the complete patch and this checklist outside the folder you delete. The patch
contains tracked edits and new files; a normal `git diff` alone would omit the new tooling. See the external
`reforger-tools-complete-redo.patch` and `reforger-tools-redo-manifest.json` saved with the session artifacts.

## Apply and verify

1. Clone the repository and enter its root. The base for this patch is `4608948` (initial commit).
2. Run `git apply --check <path-to-reforger-tools-complete-redo.patch>`, then `git apply <same-path>`.
   If upstream changed, resolve conflicts against the guide and manifest; do not discard newer code.
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
