# `audible/`: how far a gunshot can be heard

Works out where a gun's muzzle blast drops below the game's background noise, from the game's own sound files. It
needs no Workbench and no game running: it reads the sound files straight out of the game's `.pak` archives. It
produces `everon-data/sound/` and feeds the field map's "Who can hear it" tool (the `REACH_M` table in the site's
`app.js`) and the mortar sound ranges.

## Requirements and setup
- Python with `numpy` and `scipy`.
- The game installed at the default Steam path. `pakx.py` has it fixed:
  `C:\Program Files (x86)\Steam\steamapps\common\Arma Reforger\addons`. If yours differs, edit `GAME` at the top of
  `audible/pakx.py`.
- **Run everything from inside the `audible/` folder** (the scripts import each other and read and write files in
  the current folder).

```bash
cd audible
python audible.py        # step 1: measure the shot and noise samples -> S.npy, N.npy (prints the band table)
python audible3.py       # step 2: the result table -> audible.json (metres per gun per noise level)
python loud.py "Bed_Meadow"   # any time: loudness of any game .wav matching the regex
```
The first run builds `pakindex.json` (an index of every file in every game pak) and takes a minute or two. Do step 1
first: `audible2.py` and `audible3.py` load `S.npy` and `N.npy` when they start and fail if they are missing.

## The scripts

| Script | What it does |
|---|---|
| `pakx.py` | Indexes the game's paks and reads files out of them. `python pakx.py list <regex>`, `cat <exact path>` (raw bytes to stdout), `grep <pathregex>::<textregex>` (matching lines of matching text files). Used by the others. |
| `loud.py` | BS.1770 K-weighted loudness (LUFS), peak, RMS and length of game `.wav` files. `python loud.py <regex> [<regex> ...]` lists every match. |
| `audible.py` | Third-octave spectra (50 Hz to about 6.3 kHz) of the shot's Far and Mid blast layers (the 5.56 samples) and of the ambient bed and wind recordings; also holds the ISO 9613-1 air-absorption function. Writes `S.npy` and `N.npy`. |
| `audible2.py` | `reach(class_lufs, noise_lufs, thresh=0)`: the distance at which the shot's best band falls to the noise. Run directly it prints reaches for rifle, MG, heavy and suppressed shots at four noise levels. |
| `audible3.py` | The final table: every gun and impact type at four noise levels, rounded to 5 m, printed and written to `audible.json` as `{levels, noise, reach}`. |

## Method
1. The shot starts at 2 m (the amplitude config's inner range) at the loudness its amplitude class names (read from
   `Sounds/_SharedData/Configs/Amplitude/*LUFS*.conf`): rifle -15.5 LUFS, 7.62 MG -13.5, heavy MG and launchers -9.
   Suppressed rifle, mortar and impacts are scaled by their slope factor relative to the rifle's 76.
2. It falls 6 dB per doubling of distance, less air absorption per band (ISO 9613-1 at 15 C, 70% humidity).
3. The background is the ambient bed and wind recordings (all mastered to -30 LUFS) through the wind bus at -10 dB,
   so -40 LUFS at full wind. Four levels: still -55, breeze -50, windy -45, storm -40 LUFS.
4. The shot is heard while its loudest 50 ms is above the noise in any third-octave band (60 Hz and up).

## What comes from the game and what is estimated
**From the game:** gun loudness classes, the ambient beds, the wind bus level, and the AI's own 500 m / 100 m hearing
(`SCR_AIDangerReaction_WeaponFired`).
**Estimated:** how loud the wind is at each noise level (the game scales it with weather), the 0 dB detection
threshold, that the named loudness is the level at 2 m (the game does not say), and air absorption (the game's
"AirAbsorptionLite" is not published). The best check is to stand in the game at a measured distance from a firing
gun and compare. Results for a different threshold can be had with the `thresh` argument of `reach()`.

The matching result files are documented in `everon-data/sound/README.md`.
