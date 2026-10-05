# Website calibration recipes

These reviewed inputs preserve the known `arma-map` values that were embedded in browser code or manually tuned.
`website-calibration.json` is a 2026-10-05 snapshot with provenance: legacy sight definitions, construction role
membership/mapping, mortar/sound/blast baselines, cave coordinates and tree colours. It contains no runtime room,
ban, player, credential or cache data. `legacy-reticles.js` preserves the source geometry of the existing site's
`gunReticle`; `rmtlib/reticles.py` generates standalone SVGs from the same angular geometry.

Use **Website data → Export curated website recipes + legacy sight sketches** or:

```powershell
python webdata.py recipes --output out/website-data
```

This works without a website checkout or game install. It exports all 16 legacy gun/vehicle SVGs, their definitions,
manual cave/colour inputs and construction roles. These are source recipes, not freshly validated measurements.
Refresh measurable inputs with their producers; review manual changes explicitly. See
[the full producer map](../docs/website-data.md) and [custom sight workflow](../docs/sights.md).
