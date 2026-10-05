# Foliage from the game's meshes (`rmtlib/foliage_mesh.py`)

How see-through every tree and bush prefab is, measured from the game's own models and leaf textures, without running
the game. It produces the same numbers the foliage photographs did (`cover` per 0.25 m slice per distance band, the
crown from below, the bush cell maps), checked against the photographs, plus three extinction values. The photo job
stays as the check (and for prefabs the library cannot read).

```bash
python -m rmtlib.foliage_mesh build            # the base game's library, out/foliage-library/<game build>.json.gz
python -m rmtlib.foliage_mesh build --only t_picea_abies   # a few prefabs (tests)
python -m rmtlib.foliage_mesh show Prefabs/Vegetation/Bush/b_rosa_canina_1s.et
python rmt.py bake <world> --parts foliage,plants         # uses the library when there is one for the build
python -m rmtlib.foliage_mesh option <site>/data/maps/everon out/foliage-mesh-option/everon   # see below
```

`bake --parts foliage` writes `site/foliage/` from the library for every standing plant kind in the map's entities
export. Kinds the library lacks come from the map's photographs when there are any, else they are listed (photograph
just those). With no library for the build, the photographs are used as before.

## What it does

For each standing tree and bush prefab of the base game (417; 255 distinct meshes), at mesh scale 1 (the placed scale is
applied by the bakers and the field map, which already scale `k` by 1/scale and widths by scale):

1. The prefab's `MeshObject` `.xob` and each crown material's `OpacityMap` `.edds` are read from the paks
   (`rmtlib/xob.py`, `rmtlib/edds.py`). Materials without an opacity map (bark, `MatPBRBasic` logs) are opaque.
   The prefab's own material swaps (`MeshObject` `Materials`, `MaterialAssignClass` `SourceMaterial` ->
   `AssignedMaterial`) are applied first: 123 of the 402 prefabs use them, mostly the `_aut` autumn variants, which
   keep the summer mesh and swap in sparser leaf textures.
2. Bands: the close-up, then 25, 50, 100, 200 and 300 m. Each band draws the LOD the game draws at that distance
   (below). The camera is the photo job's: a standing eye (1.7 m above the base), looking north, a 40 degree lens,
   1440 pixels high, pitched as `RMT_FoliageCapture.PlaceCamera` does; the close-up backs off as that does.
3. The plant is turned to 8 yaws. Each crown pixel is alpha-tested as the game does: opacity sampled (bilinear) at
   the mip the game samples for that triangle's on-screen size, faded for cards seen edge-on by the material's
   `FadeFaces`, blocked when at least 0.5.
4. Per 0.25 m slice (heights measured at the plant's axis, as in the photographs) and averaged over the yaws:
   - `cover`: the blocked share between the outermost blocked columns (the photographs' metric), `cover_sd` its
     spread over the yaws, `width_m`;
   - `k`: `-ln(1 - cover) / width`, the slab value. Kept because the field map (`los-worker.js` `buildProfile`)
     rebuilds a slice's width from `cover` and `k` that way;
   - `k_disc`: the k that lets one solid disc as wide as the slice, with `e^(-k x chord)` through it, pass what the
     slice passes (the library writes it into `foliage_shots.csv`'s `k` column). It is a property of one plant seen
     alone and is not what the light grid needs: `bake_plants.kind_profiles` spreads each plant over its footprint
     in a 10 m cell, so it keeps the blocked cross-section instead, `mean(cover x width) / (pi hw^2)`, from `cover`
     and `width_m` only. (Feeding it `k_disc` made the light grid's foliage about 1.6 times denser than that.)
   - `k_chord`: `-ln(transmittance through the crown) / mean distance from the first card to the last` along the
     view (the handoff plan's chord k), and `k90`, the 90th percentile of per-ray tau / chord; `n`, the rays through
     the crown. These are for later use (section 5 of the plan) and are not read by anything yet. Do not put them in
     `k`: the field map would make every plant about three times narrower.
5. The crown from straight below (`top`: cover, `width_m`, k from the vertical chords) and, for bushes, the 0.25 m cell
   map of the close-up and the 25 m band (`map`, percent blocked).

A record is keyed by the prefab's full resource name (`{GUID}path`, from the game's `resourceDatabase.rdb`) and stores
the mesh's and each texture's pak size and CRC-32 and a CRC-32 of the prefab and its ancestors: rebuilding after a game
update measures only what changed. Records
also keep the LODs' triangle counts, the prefab's `LODFactors`, the switch distances and which LOD each band used.

## Checked against the game

Zero-wind photographs from the photo job (`-rmtFoliageWind=0`, game build 24903726, 2026-10-05):

| set | slices | cover MAE | correlation |
|---|---|---|---|
| 15 kinds, close up (the five worst of the old set and ten across the rest) | 15 x 8 sides | 0.026 | 0.972 |
| 5 kinds, close up and 25 / 50 / 100 / 200 m | 5 x 8 sides per band | 0.022 | 0.981 |
| per band on those 5: close / 25 / 50 / 100 / 200 m | | 0.018 / 0.019 / 0.012 / 0.020 / 0.040 | 0.987 / 0.985 / 0.993 / 0.981 / 0.963 |

On Everon's 70 photographed kinds (old photographs, taken in wind): slice MAE 0.067, correlation 0.925; per kind MAE
0.020, correlation 0.988. The wind photographs are the noisier reference (their own side-to-side spread is 0.043);
the worst kinds there are flexible birches and pines, which is what wind looks like.

Known differences: a fallen birch stem (`t_betula_pendula_stem_01`, `MatPBRBasic`, no opacity map) and dark bushes in
front of dark ground (`b_juniperus_communis_0`), where the photographs' 24-level change threshold misses part of the
bush: the render matches the photograph by eye there, the photograph's mask is the one short.

## What was established on the way (so it is not done again)

- **The mesh decode is right.** The decoded triangles, drawn by the engine as debug shapes from the photo camera
  (`-rmtFoliageOverlay`, research), cover the game's own picture of the plant: 99.8% of the plant's pixels fall
  inside them, and their outline matches the decoded projection to IoU 0.995.
- **UVs are signed 16-bit around a centre** (see `rmtlib/xob.py`). Reading them as unsigned 0-1 over min-max (the
  first attempt) still passes an angle-preservation check but puts texels in the wrong place: per pixel, the game's
  plant and that texture lookup were uncorrelated, which is what made bushes look far too thin.
- **The alpha test behaves as 0.5.** `MatPBRTreeCrown` leaves `AlphaTest` at its class default 0 (read with the
  `materials` research job, which dumps every parameter with its default); the crown pixel shader
  (`ps_pbrtree$CLIP$CROWN`, disassembled with the Windows SDK's `dxc -dumpbin`) discards when
  `opacity x fAlphaMul - fade < fAlphaTest`, with `fAlphaTest` from the engine; birch shows a clean step at 0.5 and 0.5
  fits all sets without tuning.
- **Nothing turns the cards.** The crown vertex shader's position depends on POSITION, one COLOR channel and wind only.
- **Wind matters for the photographs, not the mesh.** At zero wind the game's picture of a plant is identical run to
  run (mask IoU 0.99+); with wind the old photographs moved leaves around. Shoot checks with `FoliageWind=0`.
- **Prefabs carry their own `scale`** (birch 3s 1.196, poplar 3s 0.898, hazel 1 1.13); the photographs were taken at
  it. The library is at mesh scale 1.
- **The stored mips are denser** (vegetation's FoliageAlpha-style mip filter is baked into the shipped textures), so
  sampling the game's mip gives the thickening at distance.
- **Video settings change what is drawn.** The checks ran with `Atoc NONE` (no alpha-to-coverage), `TextureDetail 1`,
  `GeometricDetail 3`. Alpha-to-coverage, lower object detail or a different lens (a scope) move the numbers and the
  LOD switches.
- **No authored concealment value.** The only candidates on the prefabs are `Occlusion 30` (`Prefabs/Vegetation/Core/
  Tree_Base.et`) and `Occlusion 80` (`Bush_Base.et`); what reads them is unknown, so they are not used.

## LOD switches

Measured on 9 kinds at 18 distances from 10 to 320 m (the photo job with `FoliageLod` set to them, one side), the LOD
the game drew, identified by matching each LOD's render to the photograph (IoU 0.86-0.96 for the right one). Fitted:

    d(i -> i+1) = 1963 x R^1.088 x LODFactor_i^-0.395 x triangles_i^-0.502   metres

R the mesh's bounding radius (m), `LODFactor_i` the prefab `MeshObject`'s `LODFactors` entry, `triangles_i` the LOD's
count; leave-one-kind-out error 11%, about the spacing of the measured distances. For a 2560x1440 picture with a 40
degree lens at `GeometricDetail 3`. The `.xob`'s own per-LOD screen-size thresholds (0.5, 0.15, 0.02, ...) alone do not
explain the switches. A prefab without `LODFactors` gives its LODs to the bands in their authored order, and its
record says so.

## Size and time

The library for all 417 prefabs (`out/foliage-library/<build>.json.gz`): see the build's last log line; a record is
8-90 KB of JSON before compression. A map's `foliage_profiles.json` from it is the same layout as from the photographs.
Building it takes about 20-60 s a prefab on one core; `build` uses all but two cores.

## Comparing with the photographs on the site (`option`)

`python -m rmtlib.foliage_mesh option <map folder of the site> <out>` writes the library's version of a published
map's foliage beside the photographs' one, for an A/B switch on the site:

    foliage/foliage_profiles.json   foliage.json   plants/<tx>_<tz>.bin.gz   light/foliage.bin.gz

Same layouts, same kinds in the same order (so `trees/` and the rest of `light/` still go with them). The plants are
read back from the map's own `plants/` tiles, so it needs no entities export; read back with the photographs' own
numbers it gives the same tiles but for 72 of 762,786 Everon plants at tile edges (positions are stored to the cm)
and +-1/255 in 6.5% of the light cells. Kinds the library lacks keep their photograph numbers.
