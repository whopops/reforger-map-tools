# Sights, optics and website sketches

Use **Sights** in the desktop app. This is separate from World selection and Ballistics: `.ent` files are worlds,
`.et` files are prefabs, and `.conf` files can supply ammo or optic configuration. A weapons addon can also contain
a test world; that does not make its weapons world data.

1. **Scan sights** indexes installed game, Workshop and local project addons without launching the engine.
2. Filter by addon, **Optics / Weapons / Vehicles**, and search. Select an optic, weapon or vehicle and **Extract selected sight**.
3. Choose the component in the dropdown. Vehicle turret optics and attached weapon optics may be in referenced
   prefabs. Results preserve the component identity, owning prefab and property source; crew personal equipment is excluded.
4. Check extracted zeroing ranges and angular scale. The preview uses original texture pixels. Click to set the
   aiming point (yellow), bore point (blue), or selected range mark. Numeric boxes allow exact adjustment.
5. Choose extracted texture or a cross/post/notch/peep schematic. **Import reticle image** accepts PNG, DDS/EDDS,
   TGA or JPG if an asset is unavailable or a reference screenshot is needed. Imported screenshots need manual scale.
6. Enter a package name, verify scale and sight-to-bore alignment against the game, then tick the verification box.
   **Save calibration** preserves work; **Export website package** writes the package and opens its HTML preview.

The texture centre is an unverified convenience default. Prefab zeroing angles are not proof that this default is
the aiming point or bore row. Dynamic sights, zoom-dependent scale, thermal processing and guided weapons need
individual in-game validation. A static reader does not reproduce shader/UI transforms or reconstruct iron-sight meshes.

## Outputs and units

Outputs use the Data page's folder, under `sights/`. Inspections have stable separate resource folders. Each export contains:

| File | Purpose |
|---|---|
| `inspection.json` (inspection folder) | Root selection, inherited fields with provenance, all discovered sight components, texture errors and source warnings |
| `reticle.png` | Decoded highest-resolution original texture, when using texture artwork |
| `sketch.svg` | Portable SVG with embedded PNG or generated schematic geometry |
| `sight.json` | `rmt-sight-v1`: image dimensions, aim/bore coordinates, pixels per degree, zeroing and user range marks |
| `sight-renderer.mjs` | Browser renderer using degrees right/up for target hold, and pixel-to-degree scale |
| `preview.html` | Self-contained interactive preview; works directly from a file URL |
| `README.txt` | Website integration instructions |

`m_fReticleAngularSize` is degrees across the `m_fReticlePortion` fraction of texture width. Where both are explicit,
`pixelsPerDegree = width * portion / angularSize`. All stored aim/bore/marker coordinates are original image pixels.
Positive hold is right/up. A range-line elevation is `(row - boreY) / pixelsPerDegree`.
`sight.json.website` provides the existing site's `pxdeg`, `centre`, `axis`, `zeros` and `lines` field names.

The existing site's `shot-core.js` chooses hardcoded sight/weapon definitions. A new package **does not automatically
register a custom weapon**: copy its assets, resolve relative paths against the JSON URL, call the supplied renderer
from a custom sight selector, connect the measured ammo table, and update server weapon validation where needed.
This repo generates the inputs; it does not serve or deploy the website. Existing calibrated gun/vehicle sketches
can also be regenerated via **Website data → Export curated website recipes + legacy sight sketches**.

## CLI and implementation

```powershell
python sighttools.py scan --output out/sights/scan.json
python sighttools.py inspect --resource "{GUID}Prefabs/Weapons/Attachments/Optics/MyOptic.et" --addon ADDON_GUID --output out/sights/my-optic
python sighttools.py export --spec out/sights/my-calibration.json --output out/sights/my-package
```

`scan`/`inspect` use Steam/game/Tools discovery. `export` only needs the saved calibration/image and Pillow.
`rmtlib/sights.py` merges inherited component GUIDs even when a mod changes component class, preserves separate
channels and follows dependencies in the selected addon scope. Traversal is bounded to 500 resources / 8 levels;
warnings identify unsupported or missing sources. It supports normal Pillow image formats and ENF1 DDS with COPY
or dictionary-chunked LZ4 mips, stored smallest-to-largest. Pillow decodes DDS BC formats including BC7.
Inspection never guesses an unsupported texture; it exposes a note and offers image import.

Reticle PNG fingerprints prevent exporting a saved calibration against a replaced image of the same dimensions.
Unknown scale defaults require explicit user verification. Keep original asset provenance and respect mod asset
redistribution permissions when publishing assets.

Verified 2026-10-05: vanilla/RHS PGO-7 (2048 square), Chungus PU (1024), RHS PSO1M2 (4096, 13 reverse-order mips),
and three WCS M2A2 turret textures. Unit tests cover component identity, shared LZ4 dictionaries, corrupt payloads,
portable export and invalid calibration. These checks validate extraction, not custom zeroing or live firing accuracy.
