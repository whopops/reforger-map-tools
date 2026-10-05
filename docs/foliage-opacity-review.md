# Review: measuring foliage opacity without screenshots

Status: review and proposal, now done: option 2 (compute it from the game files) works and is checked against the
game; see [foliage-mesh.md](foliage-mesh.md). The rest is kept for the record. Based on the code and docs in this repo
and on the Workbench script API pages in the Tools install (`Workbench\docs\EnfusionScriptAPI`).

## 1. What the number is for

For each tree and bush kind we need how much of the view it blocks, by height (0.25 m slices) and by viewer distance
(close, 25, 50, 100, 200, 300 m), plus a crown-from-below value. It feeds `foliage_profiles.json`, then the plant
tiles and the 10 m foliage layer used by the "Measured" line of sight in the field map and the 3D viewer.

## 2. What it costs today

`rmt.py export --jobs foliage` runs the real game on an empty world and takes 49 views per plant, each shown and
hidden, so 98 screenshots and about 100 s per kind (about 70 kinds on Everon, so roughly two hours). It needs a GPU
and a display, the game window takes over the screen, and screenshots are 6 MB BMPs converted to PNG as it goes. It
is the part of the pipeline least suited to "anyone can run it".

## 3. What has been ruled out

| Approach | Result | Where recorded |
|---|---|---|
| Physics rays, every setting (visibility flag, Foliage / ViewGeometry / Vegetation layers) | Rays only hit trunks and branches: about 18% of a plant's box and a correlation of 0.37 against the photos. Leaves are not in the collision data | `foliagetrace` job; `satellite-and-foliage.md`, "Why photographs" |
| Orthographic camera | Renders black in this build | `troubleshooting.md` |
| Workbench screenshots | Command-line Workbench never draws the world | `troubleshooting.md` |

## 4. What the engine API offers (checked in the Tools docs)

- `VObject` has one method: `GetMaterials`.
- `MeshObject` can *create* a mesh (`UpdateVerts`, `UpdateIndices`, `GetNumGeoms`) but has no way to read triangles
  or vertices back.
- `Material` can get and set parameters by name or index; it has no texture-reading method.
- `TreeEntityClass` exposes only `GetSoundType` and `GetSoundFoliageHeight` (the height used for rustle sounds).
- `TraceParam` returns the entity, normal, material name and surface properties of a hit, nothing about
  transparency.

So a script running in Workbench can not read a tree's geometry or leaf textures. Any geometric method has to read
the game files from outside the engine. I did not find a documented opacity or concealment property. A quick
`python -m rmtlib.pak` search of the tree prefabs and their components for anything like it is still worth doing
(item A in section 6).

## 5. Options

| | Idea | Needs the game? | Needs a GPU? | Fits the view-based numbers? | Effort | Verdict |
|---|---|---|---|---|---|---|
| **1** | **A shipped library of measured profiles, keyed by prefab.** Trees and bushes of the base game are the same assets on Everon, Arland and Kolguyev. Measure each prefab once, ship the results with the app, and only photograph prefabs that are not in the library (mod maps, new game content) | no, for base-game maps | no | yes, identical numbers | small | **Do this first.** It removes the game run for almost every user |
| **2** | **Compute it from the game files.** Read each plant's mesh (`.xob`, with its detail levels) and leaf textures (`.edds`, alpha channel) from the paks, then render them in software side-on at a set of angles with alpha testing, and cut the result into the same slices | no | no | in principle, yes, per detail level, which is what produces the "denser at distance" effect | large; the unknown is the model format | **Spike, time-boxed.** Best long-term answer if the format can be read |
| **3** | **A fitted model for unknown plants.** Fit cover against measurable features (kind, height, box width, species name words) across the library, and predict for plants not in it | no | no | roughly | medium | Fallback for mod plants when photos are not available. State the error openly |
| **4** | **Fewer photographs.** Keep photos for new kinds only, and cut the views: 4 sides instead of 8 (the notes say 8 sides is within 0.008 of 16; 4 untested), skip the far bands for bushes (too few pixels past about 200 m anyway), shoot only the kinds not in the library | yes | yes | yes | small | Keep as the last-resort path inside the GUI, with an honest time estimate |
| 5 | More ray tricks (other flags, layers, finer grids) | no | no | no | small | **Stop.** Leaves are not in the collision data. Remove `foliagetrace` from user-facing lists |
| 6 | Read opacity from an engine property | no | no | unknown | small | Only if the search in item A finds one |

## 6. Recommended plan

**A. One-hour check (read-only).** Search the pak files for the tree and bush prefabs of Everon and Arland and list
what components and properties they carry (`python -m rmtlib.pak list` / `cat` / `grep`). Also grep the script API
docs for AI visibility or concealment. Outcome: option 6 is dead or alive, and we learn which `.xob`, `.emat` and
`.edds` files each plant uses.

**B. Build the library (option 1).**
1. Key: the prefab's resource path including its GUID, plus the game build it was measured on. A new game build
   re-checks only prefabs whose files changed; compare the pak entry size or a hash of the `.xob`.
2. Store: one `foliage_library.json` in the app, same schema as `foliage_profiles.json`, merged by prefab. Include
   the old Everon measurements as the first entries (they exist and were 16-side photos), and re-measure with the
   current job for any kind that disagrees.
3. Use: `bake --parts foliage` first fills each kind from the library; only missing kinds need photos. In the GUI the
   "Trees and foliage" product shows "all N kinds known" (no game run) or "M kinds need photographs, about X minutes".

**C. Spike the mesh method (option 2), box: a few days.**
1. Take 3 prefabs: one tall conifer, one broadleaf, one bush. Find their `.xob` and material files (from A).
2. Can the `.xob` be parsed (vertices, indices, detail levels, material ids)? Check whether a community parser
   exists before writing one. BI does not publish the format; I have not verified that any tool reads it.
3. Can the leaf `.edds` be decoded to an alpha mask (Pillow reads standard block-compressed formats; the Enfusion
   wrapper needs checking), and what alpha cut-off do the materials use?
4. Render the 3 plants side-on at 8 yaws, slice by 0.25 m, and compare with the photo numbers.
5. Go / no-go: **go** if the per-slice cover error against the photos is small compared with the spread the photos
   already have (the side-to-side spread was 0.06; the old 16-vs-8 sides difference was 0.008) and clearly better
   than the rays (correlation 0.37). Suggested bar: mean absolute error under 0.05 and correlation above 0.9 on the
   Everon kinds. **No-go** if far detail levels use baked impostors we can not read, or if shader tricks (alpha to
   coverage, dithered fades, wind-bent cards) change the answer.

**D. If C is a go:** compute the whole library from the paks (no game, no GPU), add the detail-level bands, run it
for every kind of every base-game map in minutes, and keep photographs only to *validate* a sample after each game
update. Mod plants then work too, as long as their files are in the paks or the mod folder.

**E. If C is a no-go:** keep photographs for unknown kinds (option 4, trimmed), and add option 3 as the offline
guess.

## 7. How to judge any new method

Ground truth is the existing photo measurements (Everon: about 70 kinds, `everon-data/foliage/`). Report, per
height band and per distance band: mean absolute error in cover, correlation, and the worst five kinds. Do **not**
use `rmt.py check` for this: the engine's sight lines pass through leaves, so they can not say how see-through a
tree looks to a player.

## 8. Effect on the GUI plan

The "Trees and foliage" product in [gui-plan.md](gui-plan.md) becomes: *use the library* (default, instant, no game),
*photograph the unknown kinds* (needs the game, shows a time estimate), or later *compute from game files*. A user
who only wants map data for a base-game map never has to run the foliage job.

## 9. Open questions

- Do the three base maps use exactly the same prefabs and models for the same kinds? Prefab names and GUIDs say yes
  for shared assets; the check is a diff of the three `plants.csv` lists against measured profiles.
- Seasonal and map-specific variants (snowy spruce, autumn birch on Kolguyev) are separate prefabs, so each needs
  its own library entry.
- Whether wind and growth scale change cover. Today `scale` is applied per placed plant; the library stores the
  profile at scale 1.
