# `rmt.py bake`: raw export to site data

Also on this page: [`rmt.py check`](#rmtpy-check-scoring-the-line-of-sight) (how well the line of sight matches the
game) and [`rmt.py fieldmap`](#rmtpy-fieldmap-into-the-website) (the bake into the website, its 2D and 3D views).

```bash
python rmt.py bake <world> [--parts roads,los,places,satellite,relief,foliage,plants]
```

Baking is plain Python (numpy, Pillow, and SciPy); it does not start Workbench or the game. It takes the **newest export** of
the world (the most recently written `out/*/*/manifest.json` whose world, slug or file name matches what you typed)
and writes `out/<slug>/<build>/site/`. Parts always run in the order `roads, los, places, satellite, relief, foliage, plants`,
whatever order you list them in. `--parts` defaults to all of them and does not add dependencies. Missing inputs
for satellite, relief or foliage print a message and are skipped; other missing inputs can stop the bake.
Low-level `bake` can return 0 after these skips; `run` treats them as failure. Read the output for completeness.

| Part | Needs (from the export) | Writes (under `site/`) |
|---|---|---|
| `roads` | `probe.json`; `mapdata/*.topo` or else `roads/` | `roads.json` |
| `los` | `probe.json`, `terrain/`, `objects/`, `surface/` | `los/`, `light/` |
| `places` | `names/descriptors.csv` and the game's paks | `places.json` |
| `satellite` | game-profile `satellite/` shots, `terrain/` | `tiles/<z>/<x>/<y>.jpg` |
| `relief` | `mapdata/*.tga`, already baked `los/` with 0.5 m surface cells | `relief/<z>/<x>/<y>.jpg` |
| `foliage` | game-profile `foliage/shots.csv` and photos | `foliage/foliage_shots.csv`, `foliage/foliage_profiles.json` |
| `plants` | `objects/`, and `los` and `foliage` already baked | `foliage.json`, `plants/`, `light/foliage.bin.gz`, `light/clutter.bin.gz` |

All binary files are little endian and gzip-compressed with a zero timestamp, so a rebake of the same input is
byte-identical. Rows always run south to north and columns west to east. Coordinates are world metres: x east, z north.

Size budget: the whole `site/` should stay under 2.5 GB, not counting `tiles/`. On Everon the baked field map is about
157 MB, so the budget only matters on very large maps. Data grows with map area; at the same detail:

| Map | Size | Area | Site data (projected) |
|---|---|---|---|
| Arland | ~4 km | 16 km² | ~0.02 GB |
| Everon, Kolguyev | 12.8 km | 164 km² | ~0.2 GB |
| A big community map | 20 km | 400 km² | ~0.5 GB |
| The budget's limit | ~40 km | ~1,600 km² | 2.5 GB |

Nothing enforces the budget yet. A map that would go over can bake its line of sight at 1 m instead of 0.5 m (a
quarter of the size). Raw exports (several GB) stay on your PC and are never uploaded.

---

## `roads` (`bake_roads.py`, `topo.py`) -> `roads.json`

**Source.** BI's own 2D-map roads from the `.topo` file the `mapdata` job writes. They are already merged into whole
roads and typed by BI (0 runway, 1 main, 2 paved, 3 dirt, 5 footpath, with widths). After flipping y to z they match
the game's road pieces to about 3 m, and they carry on across bridges. If the world has no `.topo` or it has no roads,
the `roads` job's pieces are used instead, typed by surface material (decals dropped; `Trail` is a footpath; dashed
asphalt is a main road; asphalt, cobble, concrete a street; dirt, forest, gravel a dirt road; anything else is dropped).

**Joining.** A road end joins another road only where the surfaces touch: within half of both widths plus 1 m
(at least 2 m) of the other road's centre line, either to its end or by splitting it. A loose end is then carried
straight on for at most 12 m and joined if that hits another road. Nothing else is joined; roads that cross without
either ending there stay separate (a bridge and a crossroads look the same in 2D). Lines are simplified to 0.3 m.

**Output.**
```
{"version", "source": "bi-topo" | "road-pieces", "kinds": ["main road","street","dirt road","foot path"],
 "nodes": [[x, z], ...],
 "edges": [[a, b, kind, [[x, z], ...], width], ...],     a,b = node indexes; kind 0..3
 "runways": [[[x, z], ...], ...]}
```
The log prints road counts, joined and dead ends, and length per kind.

## `los` (`bake_los.py`) -> `los/`, `light/`

Line-of-sight data from terrain, entities and surface. The chunk grid, origin, height unit and light-grid size all
come from `probe.json`.

`los/<tx>_<tz>.bin.gz`, per chunk (open sea chunks are skipped), concatenated:

| Plane | Type | Meaning |
|---|---|---|
| terrain | Uint16[T*T] | ground height in `terrain.unit` metres above the water line (sea floor clamped to 0) |
| top | Uint8[S*S] | top of whatever stands on each surface cell, in 0.25 m above the ground |
| bottom | Uint8[S*S] | where it starts (canopy underside; 0 for solid things), same units |
| kind | Uint8[S*S] | 0 nothing, 1 building, 2 solid, 3 tree, 4 see-through fence, 5 bush or low plant |
| cover | Uint8[S*S] | top of what stops bullets, same units (0 = nothing) |

`los/index.json` holds the grid, the units, the layout and the list of chunks written.

`light/` holds 10 m grids covering the whole map, rows south to north:
`height.bin.gz` (Int16, decimetres), `forest.bin.gz` (1 bit per cell, packed), `canopy.bin.gz` (Uint8, four planes
one after another: top, base, low, crown), `buildings.bin.gz` (Uint8, metres) and `lz.bin.gz` (Uint8 helicopter
landing: 0 water, 1 good, 2 marginal, 3 no-go). The log prints the share of land that is good, marginal and no-go.

## `places` (`bake_places.py`) -> `places.json`

Every map descriptor shown on the map with a type set on the placed entity. English names come from the game's own
string table (`Language/localization.en_us.conf`, read from the paks). Capital-letter names (hills, ridges) are
re-cased.

```
{"version", "source",
 "towns":     [{"name", "type": City|Town|Village|Settlement, "xz": [x, z]}, ...],
 "landmarks": [{"name", "type": Area|Hill|Island|Water|Sea|Ridge|Valley, "xz": [x, z]}, ...],
 "pois":      [{"type": e.g. "Church"|"Fuel station", "name"?, "xz": [x, z]}, ...]}
```
Trees, roads, fences and similar descriptor types are skipped. Conflict bases, supplies, vehicles and caves come from
game modes and are not in the world, so they are not made here.

## `satellite` (`satellite.py`) -> `tiles/`

Corrects the game's perspective shots into a true top-down map and cuts the tile pyramid. Details in
[satellite-and-foliage.md](satellite-and-foliage.md). Tiles are `tiles/{z}/{x}/{y}.jpg`, 256 px, JPEG quality 85;
zoom 0 is the finest (about 0.39 m per pixel), zoom 5 the coarsest at 12.501 m per pixel, a 50 m origin offset, y
counted from the south. Each coarser zoom is built from four tiles below it. Sea fills with a dark green; tiles that
are entirely empty are not written. Needs the shots in the game profile folder and the terrain export. Takes a long
time on a large map.

## `foliage` (`foliage_mesh.py`, `foliage.py`) -> `foliage/`

From the mesh library for the game build when there is one (`python -m rmtlib.foliage_mesh build`, see
[foliage-mesh.md](foliage-mesh.md)): every standing plant kind in the entities export, same files and layout, plus
`k_disc`, `k_chord`, `k90`, `width_m` per slice in the library (the site's `foliage_profiles.json` keeps only `y`, `cover`
and `k`, the fields `los-worker.js` reads). Kinds the library lacks come from the photographs below, or are listed.

Without a library it analyses the foliage photographs (before/after pairs; the pixels that differ are where the plant blocks the view).
Writes `foliage_shots.csv` (`id,prefab,kind,band,slice_m,cover,k,width_m,pixels`) and `foliage_profiles.json`
(per prefab: kind, shots, height, close-up `slices`, `top` from below, and `bands` per distance). Also writes both
into the export's own foliage folder, with `debug/<id>.png` pictures for the first 20 shots (plant tinted red, slice
lines drawn) so you can see what counted as plant. A shot that fails is skipped and counted.
`cover` is the share of the outline that blocks the view; `k` is how fast it blocks sight per metre crossed, so what
remains visible is `e^(-k x metres)`.

## `relief` (`relief.py`) -> `relief/`

Draws shaded terrain, buildings, walls and rocks at 0.5 m from baked LOS; vegetation is omitted. Broad and fine
shading use north-west light, with weights fitted to BI's Arland raster. The sea comes from the `mapdata` TGA.
Requires SciPy and 0.5 m surface cells; another LOS surface resolution is rejected. The JPEG tile pyramid shares
satellite's coordinate scheme. `site/relief.u8` is a temporary NumPy memory-mapped picture, removed after a
successful build when possible. Installing copies `relief/` and sets `map.json`'s `hasRelief` timestamp.

## `plants` (`bake_plants.py`) -> `foliage.json`, `plants/`, `light/foliage.bin.gz`, `light/clutter.bin.gz`

Every standing tree and bush (prefab under `/Vegetation/Tree/` or `/Vegetation/Bush/`, excluding debris, stumps,
branches and fallen trees) from the entities export, joined to the measured profile of its kind. Plants of kinds that
were not photographed are left out and counted in the log.

- `foliage.json`: `{"bins": 10, "margin", "baseUnit", "tiles", "prefabs", "plants": [{"h", "hw": [10], "k": [10]}, ...]}`.
  Per kind (the index is the kind byte in the plant tiles): height `h`, and per tenth of that height the half-width
  `hw` (half the mean measured width) and blocking `k = mean(cover x width) / (pi hw^2)`: the slices' blocked
  cross-section spread over the disc the light grid fills, so a cell of many plants blocks a sight line by the sum
  of their blocked cross-sections. Only `cover` and `width_m` are read (photographs and the mesh library give the
  same k for the same picture). It is no longer `-ln(1 - cover) / width`, which made a crown with a hole as dense
  as a solid one.
- `plants/<tx>_<tz>.bin.gz`: per chunk, every plant reaching into it: `n` Uint32, then `x` Uint16[n], `z` Uint16[n]
  (cm from `margin` metres south-west of the chunk corner), `base` Uint16[n] (ground under the plant in `baseUnit`
  metres; 0.01 unless the map is too high for cm), `kind` Uint8[n], `scale` Uint8[n] (hundredths).
- `light/foliage.bin.gz`: Uint8 per 10 m cell and height band (edges 0, 1, 2, 4, 7, 12, 20, 45 m): average foliage k,
  0 to 255 meaning 0 to 0.5 per metre.
- `light/clutter.bin.gz`: Uint8 per cell and band: share filled by solid things, 0 to 255 meaning 0 to 100%.

## `rmt.py check`: scoring the line of sight

```bash
python rmt.py check <world>                               # the newest export's sight lines against its site/los
python rmt.py check --csv <check.csv> --site <folder>     # any sight lines against any site (a folder with los/)
```

Not a bake part: it reads the `sightlines` export ([export-jobs.md](export-jobs.md#sightlines)) and the baked `los/`
tiles and prints how often they agree with the engine (`check_los.py`). Each line is walked through the tiles every
0.25 m, leaving out 0.5 m at each end. The tiles call it blocked where the ground rises above it, or where it passes
between the underside and top of a building, wall, rock, pole, tree or bush (not a see-through fence, as on the map);
the engine calls it blocked when its ray stopped short. Also printed: the same for the bare terrain, for bullets
(terrain and the `cover` plane, when the tiles have one), by distance, and what the engine hit where the tiles saw
nothing (the likeliest gaps in the bake). About 10 s for 20,000 lines.

On the 2026 Everon export (`everon-data/check.csv` against the field map's Everon tiles): objects and terrain agree
95.0%, terrain alone 67.8%, bullets 91.5%; misses are mostly tree trunks and destructible props between the 0.5 m
surface rays.

## `rmt.py fieldmap`: into the website

```bash
python rmt.py fieldmap <world> [--to <arma-map/everon-map>] [--as <id>] [--tiles] [--photos]
```

Installs the newest bake of a world into the website (`fieldmap.py`, with the trees from `trees.py`): arma-map's
`everon-map`, which serves the field map at `/` and its 3D view at `/3d/`. Both views read the same files, so each
map's data is there once. Needs the `los`, `places`, `roads`, `foliage` and `plants` bakes, and for the trees the
`entities` export.

| Written (under `static/`) | From | Read by |
|---|---|---|
| `data/maps/<id>/los/` | `site/los/` | both (line of sight; the 3D view also draws its terrain and objects from them) |
| `data/maps/<id>/light/` | `site/light/` | both (the 3D view uses `height`, `canopy`, `buildings`, `forest`) |
| `data/maps/<id>/plants/`, `foliage.json`, `foliage/foliage_profiles.json` | `site/plants/`, `site/foliage.json`, `site/foliage/` | both (Measured line of sight; the 3D view's "Measured tree shapes" draws `foliage.json`'s `bins` and `plants`) |
| `data/maps/<id>/roads.json`, `places.json` | `site/` | both (the 3D view turns them into its own forms as it loads) |
| `data/maps/<id>/tiles/` | `site/tiles/` | the field map: satellite tiles, for every map whose `map.json` names no `upstream` tile server (Everon has one for now; `--tiles` copies them anyway) |
| `data/maps/<id>/relief/` | `site/relief/` | the shaded-relief base layer; `map.json` records its `hasRelief` timestamp |
| `data/maps/<id>/trees/` | the raw `objects/` and `site/foliage/` | the 3D view's shaped trees: `trees.py`, below |
| `data/maps/<id>/map.json` | `site/los/index.json` and the probe | what the site knows about the map: `{title, slug, order, world, tile, cols, rows, lightCols, lightCell, unit, start, hasTrees, upstream?}`. The site lists every folder that has one (its join screen, and the 3D view's `maps.json`, which the server builds from them). `title`, `start`, `order` and `upstream` are kept from the one already there |

`--to` automatic discovery checks `../../arma-map/everon-map` relative to this repo; in the sibling layout pass
`--to "../arma-map/everon-map"` explicitly; `--as` defaults to the site's map whose
`map.json` has the world's slug. A new map needs only `--as <id>` (and `--title <name>`, else the world's name) on its
first install: its `map.json` puts it on the site, with the 3D camera over the land chunk nearest the middle (edit
`start` in `map.json` to change it), last in the list (`order`).
Directory files with identical contents are skipped; same-size changes are copied even if timestamps match.
Installation merges directories without deleting old files. Missing optional directories stay as they are.
Trees are rebuilt when raw objects and foliage measurements are available; otherwise existing trees are kept.

**Trees** (`trees.py`). Every standing tree and bush in the entities export becomes an 8-byte record in
`trees/<tx>_<tz>.bin.gz` (Uint16 x and z in cm from the chunk corner, then Uint8 species, yaw in 360/256°, height in
0.25 m and crown radius in 0.1 m; gzip -9 with no name or time, so a rebuild is byte-identical). `trees/species.json`
has one shape per kind: 7 rings from the ground up (two for the trunk, five for the crown), made from the close-up
foliage measurements (the widest-slice outline, a trunk from the narrowest stem slice, kept within 1.2-3% of the
height), and the page scales each tree by its own box. Stumps, fallen trunks and debris are left out. Its `format`
(2) changes only when a field's meaning does; its `version` is a hash of everything written, so browsers refetch.

**Tree models** (`tree_models.py`). Optional, beside `species.json`: `trees/models.json` and `models.bin.gz`, one
low-poly model per species fitted to the game's own mesh (leaf clumps where its leaves are solid, its trunk; about
80-350 triangles near, a coarser one for distant tiles; 80-150 KB a map). The site's 3D view draws them for **Tree
shapes: Models**, each tree at its own height and yaw from the tiles above. Made from a published map folder, no bake
or game run needed: `python -m rmtlib.tree_models <site>/data/maps/<id>`; one process (about 0.5-2 GB, 6-15 minutes a
map). The models are our own shapes, not the game's geometry or textures.

**Tree colours.** The foliage photos are taken against a bright hazy sky, which washes leaf colours out, so the
site's Everon tree table carries hand-tuned colours. `fieldmap` reads them from
`static/data/maps/everon/trees/species.json` before rebuilding and gives every kind it knows the same colours, on
every map (its `version` gets a `c` on the end). Other kinds get plain tree and bush greens, or `--photos` reads
colours from the foliage photos in the game profile instead. Don't delete the Everon table: it is where the tuned
colours live.

## Typical re-bake situations

| You changed | Re-run |
|---|---|
| Nothing, but want the site files fresh | `bake <world>` |
| Re-exported terrain, entities or surface | `bake <world> --parts los,relief,plants` (satellite also uses terrain) |
| Re-exported `mapdata` or `roads` | `bake <world> --parts roads` (also `relief` if its mapdata raster changed) |
| Re-exported `names` | `bake <world> --parts places` |
| Retook satellite shots | `bake <world> --parts satellite` |
| Retook foliage photos | `bake <world> --parts foliage,plants` |
