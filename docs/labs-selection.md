# Selected Labs tests, including installed mods

Labs lets you choose test targets separately for every category. Open **Labs**, select a category,
then **Scan installed targets**. Choose an addon under **All related addons**, search the resource list,
and tick the items to test. **Select visible** adds only the current filtered rows; selections hidden
by a filter remain selected and are counted. **Clear selection** clears the category. Nothing selected
means no test, never all installed assets.

Choose a command below the target panel and press **Start**. The terminal command uses the same saved
selection as the GUI. **Save selection** and **Load selection** transfer the recipe; a completed live
run also saves resolved physics, source hashes, dependency GUIDs and the game build in `selection.json`.
Selections persist while switching categories within the open window; save a recipe to retain them
across app sessions. Scanning reads installed files and does not start the game.

| Category | What you can select | Additional requirements |
|---|---|---|
| Mortar fire, group, gun and barrel | Baseline mortar/shell pairings, installed mortar weapons or shell prefabs | A directly selected shell needs a compatible mortar weapon. Inspect and choose resolved pairings. Group/gun requires one pairing. |
| Blast | Baseline shells or installed explosive ammunition | Select the actual explosive projectile; flight physics alone does not establish its damage. |
| Bullet flights and checks | Baseline round/barrel combinations, installed weapons, vehicles and bullet prefabs | Inspect weapon/vehicle references and choose projectile pairings. Resolve ambiguous muzzle coefficients explicitly. |
| Rocket flights and checks | Baseline rockets or installed rocket/missile ammunition | A direct prefab tests that projectile. This direct-launch test does not exercise scripted guidance or a complete launcher. |
| Launcher tests | Baseline launchers or installed launcher weapon prefabs | Choose one ammunition variant per weapon, a measured `rockets.json` containing it, readable sight zeroing and a verified launch-above-bore angle. |
| Conflict | Installed terrain worlds and Conflict scenarios | A terrain must resolve a Conflict scenario. An explicit scenario can use an existing website map id; install its terrain data first. |
| Gunshot audibility | Installed game/mod WAV samples | Measure the selection before table/reach. Set the calibrated in-game shot level at 2 metres; a sample's loudness does not establish that level. |
| Game files | Installed addon packages | Find/show operations are restricted to the ticked addons, including mods. |
| Self-test | Individual bundled regression modules | No game installation needed. These test the tool code; mod fixtures are covered by relevant modules, rather than loading arbitrary mod scripts. |

## Inspecting weapons, vehicles and ammunition

**Inspect selected targets / validate dependencies** resolves inherited prefab data and required installed
addons without firing. Its dialog lets you tick the precise resolved projectile pairings. A weapon or
vehicle may expose several ammunition types; explicitly narrow that list before a long run. Selecting
an ammunition prefab directly selects that projectile, rather than its base templates or secondary fragments.
If multiple muzzle speed coefficients remain ambiguous, use **Override launch coefficient** with the actual
barrel's value. Unsupported resources and missing dependencies fail explicitly.

Catalog categories use resource paths to find candidates. A checkbox is not a guarantee that a prefab has
usable physics: shared templates and unusual mod layouts need inspection. Install required Workshop
packages before scanning. Live launches load the selected addon dependency closure, including mods owning
inherited ammo. The launcher engine verifies that the fired prefab is the selected round; incompatible
loadouts fail instead of scoring another carried round.

## Plans, results and repeatability

The Data page's output folder contains `labs/<category>/<signature>/`. Live raw data is in the game's
profile under `rmt/labs/<category>/<signature>/`; native mortar lookup tables use the Workbench profile.
The signature includes target selection, resolved sources, physics, game build and an imported flight
dataset's hash. Different targets or updated sources produce a separate run. Measured JSON stays isolated
until you review/install it through the relevant website workflow. The GUI opens the selected output folder.

A report on an older run uses that run's recorded selection and physics. Load its `selection.json` first.
Resume also verifies the current source signature and refuses changed mods. Preserve raw files and the
signature output folder together, including native mortar tables. Flight fitting requires every planned
wind block and a trajectory for every shot; incomplete suites are rejected. A game exit alone is insufficient:
selected launches require a successful status, at least one completed shot and no skipped shots.

Mortar plan/run/group/gun/barrel commands obtain native engine lookup tables before planning, so a **plan**
can start Workbench. Baseline tables retain their calibrated range settings. Custom mortars use actual
prefab/ring coefficients with a 50-5000 metre sampling grid; this is a sampling bound, not a claim of usable
range. Unknown dispersion starts at zero and must be measured with barrel/group tests. Reports and target
inspection do not regenerate native tables.

Bullet/rocket **check** commands need this selection's scored flight dataset, or an explicitly chosen
compatible measured dataset. Baseline launchers can use the discovered website's `rockets.json`; custom
launchers require their own matching measured ammunition entry. Audibility results retain the chosen
samples and calibration separately; changing a calibration creates a different output selection.

## Command line

The GUI generates these commands and writes the selection file automatically. A minimal recipe is:

```json
{"tool": "rockettest", "targets": ["baseline:PG-7VM"]}
```

Installed target ids come from the catalog as `addonGuid|{resourceGuid}resource/path.et` (or WAV path).
Do not guess GUIDs. Use **Save selection**, or read the catalog's `id` field.

```powershell
python labtest.py catalog --output out/labs
python labtest.py prepare --tool rockettest --selection rocket-selection.json --output out/labs
python labtest.py plan --tool rockettest --selection rocket-selection.json --output out/labs
python labtest.py run --tool rockettest --selection rocket-selection.json --output out/labs
python labtest.py score --tool rockettest --selection rocket-selection.json --output out/labs
```

The standalone `firetest.py`, `rockettest.py` and similar scripts retain their baseline command-line presets.
The GUI uses `labtest.py` for explicit selections. Add new selection-aware categories to both the declarative
forms and the backend; changing only a checkbox list does not change what the engine tests.

## Verified scope

Regression tests cover category command routing, mod dependencies, recipe identity, report/resume isolation,
projectile filtering, no-game self-tests and rejection of missing flight blocks/shots. Offscreen GUI checks
exercise category selection and command construction. The updated addon compiled and started in Reforger;
one selected Chungus Workshop rocket fired with its addon loaded and produced 30 trajectory frames.
Full-duration suites, modded mortar firing and every scripted/guided launcher have not been validated.
