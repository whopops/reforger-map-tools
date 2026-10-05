How far a gunshot can be heard: where the muzzle blast drops below the game's background noise.

Reads the game's own sound files straight from its .pak files (no Workbench needed), so run these from this folder:

  python audible.py       # first: measures samples and writes S.npy and N.npy
  python audible3.py      # then: prints the table and writes audible.json (metres per gun, per noise level)
  python loud.py <regex>  # loudness (LUFS), peak and length of any game .wav, e.g.  python loud.py "Bed_Meadow"

Files
  pakx.py      index / list / cat files out of the game's .pak archives (first run builds pakindex.json, a minute or two)
  loud.py      BS.1770 loudness of a game .wav
  audible.py   third-octave spectra of the shot's Far/Mid blast layers and of the ambient bed and wind recordings
  audible2.py  reach(): shot level at 2 m, less 6 dB per doubling and ISO 9613 air absorption, against the noise
  audible3.py  guns and impacts x four noise levels -> local audible.json (website installation is a separate step)

Needs Python with numpy and scipy (install ../requirements.txt with the interpreter you use here).
If you used the root batch launcher, replace python above with ..\.venv\Scripts\python.exe.
Check GAME in pakx.py before running: it is the game's addons folder, fixed to the default Steam path.
Delete pakindex.json when the game updates or GAME changes, and remeasure spectra after asset changes.
audible2.py and audible3.py load S.npy and N.npy at startup and fail if they are missing; loud.py is independent.
Generated ranges are estimates, not in-game hearing measurements. See README.md and ../docs/audible.md.

What comes from the game:  gun loudness (Sounds/_SharedData/Configs/Amplitude/*LUFS*.conf: rifle -15.5, 7.62 MG -13.5,
heavy -9; slope factors scale the suppressed rifle, mortar and impacts), the ambient beds (all mastered to -30 LUFS), the
wind bus (-10 dB in Environment_Ambients_2D_Everon.acp), and the AI's own 500 m / 100 m hearing (SCR_AIDangerReaction_WeaponFired).
What is estimated:  how loud the wind is at each noise level (Still -55 .. Storm -40 LUFS; the game scales it with the
weather), the 0 dB detection threshold, and air absorption (the game's "AirAbsorptionLite" isn't published).
The best check is to stand in game at a measured distance from a firing gun and compare.
