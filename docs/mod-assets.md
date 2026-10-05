# Installed-mod review and sorting

Snapshot checked on 2026-10-05: 91 addons, roughly 36,600 `.et`/`.conf` records. Counts change while Steam downloads
or updates mods. Source families now include RHS Status Quo/content packs, WCS weapons/scopes/attachments/armaments,
WCS ground vehicles and helicopters, ACE extensions, Chungus weapons and smaller utility/weather packs.

## Asset families

| Family | How it is handled |
|---|---|
| World `.ent` | World page; a pack's image-generator/test world is still a world, not a weapon entry |
| Weapon `.et` | Ballistics or Sights, grouped by owning addon and type; inspect inherited muzzle values and references |
| Ammo `.et` / ammo config `.conf` | Ballistics; magazine → ammo config → projectile traversal is necessary |
| Vehicle `.et` | Ballistics for gun/ammo references; Sights follows separate turret/gauge/weapon prefabs |
| Optic `.et` | Separate optic type and Sights filter; component GUID remains its identity when a mod changes class |
| Content pack | May contain only mesh/texture/audio assets; no prefab records is not an installation error |
| Scripts/medical/UI/weather/clothing | Not treated as weapon ballistics just because they are Workshop addons |
| Missing/stale RDB-only entry | Report source-unavailable warning; do not fabricate defaults |
| Active download `temp/data.pak` | Excluded: it can be incomplete/locked and is not the installed archive |

The resource GUID is the identity. Same path does not imply same resource. Resolve overrides only within the
selected addon and dependency closure; two unresolved active overrides are an ambiguity. Do not let an unrelated
installed weapons pack change another mod's physics. Vehicle default crew loadouts are excluded from gun/sight
reference walks, so their carried personal weapons are not presented as mounted guns.

## Concrete inspected examples

- Chungus M40 ammo inherits game 7.62×54R/core projectile data; the weapon's magazine uses a separate `.conf`
  to name its custom round. Select the actual muzzle coefficient instead of assuming an ammo-only speed is correct.
- Chungus PU: 1024-square reticle decoded from its mod texture.
- RHS PGO-7 changes the inherited sight component class under the same GUID and uses the game PGO texture.
  Component merge must combine those records rather than displaying two unrelated channels.
- RHS PSO1M2: 4096-square reticle with 13 reverse-order mips, COPY for the small levels and LZ4 for the large ones.
- WCS M2A2: turret is a referenced prefab with multiple independent sight components and 1024/2048 reticles.
  Cannon/coax prefabs also inherit generic iron-sight definitions; select the intended turret channel in the dropdown.
- WCS Armaments can override a game vehicle-core resource. Correct dependency scope is essential.

An addon can alter ballistics through scripts, guidance, rockets' thrust, weather or runtime selection. Static
inspection is provenance/discovery, not complete simulation. Direct flight tests do not reproduce full vehicle fire
control, guided missiles, weapon dispersion or dynamic sight processing. The source report, separate component
selector and explicit calibration verification keep those boundaries visible.

For a reproducible local review, run the two **Scan** buttons again after downloads finish. Reports in the chosen
output folder retain source references and warnings; no game assets or mod files are modified by scanning/extraction.
