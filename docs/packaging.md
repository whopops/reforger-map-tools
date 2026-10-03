# Packaging the desktop app

Status: built. `ReforgerMapTools.spec` is the build and `.github/workflows/package.yml` runs it on GitHub's Windows
machines: pushing a tag like `v0.1.0` publishes the zip as a GitHub Release. Without it the app starts from
`Reforger Map Tools.bat`, which needs Python on the PC and installs PySide6, numpy, Pillow and SciPy into `.venv\` ([gui.md](gui.md)). The goal of packaging is phase 5 of
[gui-plan.md](gui-plan.md): someone who has never seen this repo downloads one file, unzips it and opens the app, with
no Python.

## What the user gets

A zip, `ReforgerMapTools-<version>-win64.zip` (roughly 120 MB to download, 300 MB unzipped), attached to a GitHub
Release of this repo. Unzip anywhere and double-click **`Reforger Map Tools.exe`**. Output goes to
`Documents\ReforgerMapTools` by default and the built addon to `%LOCALAPPDATA%\ReforgerMapTools` (`rmtlib/paths.py`
already does this when frozen), so the unzipped folder can be read-only.

Windows will warn the first time ("Windows protected your PC") because the exe is not signed: *More info*, then
*Run anyway*. A code-signing certificate removes that, but costs money every year; not worth it for a small group.

## How it is built

- **PyInstaller, one-folder build** (not one-file: one-file unpacks 300 MB to a temp folder on every start, which is
  slow and trips antivirus more often).
- **Two programs in the same folder, sharing their libraries**:
  - `Reforger Map Tools.exe`: the window (no console), from `rmt_gui.py`;
  - `rmt.exe`: a console program, from the same `rmt_gui.py`. The window starts it as the worker
    (`rmt.exe --worker ...`, `--script ...`). It is also the command-line tool for anyone who wants it.

  Why two: a windowless exe may have no usable output pipe, so a worker started from it could lose every progress
  line. A console exe started by Qt shows no window but always has one (`rmtgui/worker.py`).
- **Bundled as data**: `addon/` (the Workbench and game scripts), the Labs scripts (`firetest.py`, `blasttest.py`,
  `rockettest.py`, `rocketfit.py`, `launchertest.py`, `bullettest.py`, `audible/`), `rmtgui/icon.ico`,
  `rmtgui/check.svg`, `docs/` (the Labs page's *Read the docs*), and the `test_*.py` self-tests.
- **Left out** to keep it smaller: Qt's web engine, 3D, multimedia and QML modules, which the app doesn't use.
- **Built by GitHub Actions** on a Windows machine, from a `ReforgerMapTools.spec` file and a small workflow: push a
  version tag (or press *Run workflow*) and the zip appears on the Releases page. Nobody needs Python or PyInstaller
  on their own PC to make a release.

## Still to check by hand (the build machine has no game)

1. The packaged worker starts Workbench and a quick Arland run finishes (plan phase 0b and phase 3's test).
2. Cancel kills Workbench or the game under the packaged worker.
3. A Labs script (the self-test, then a game test) runs from the package.
4. On a PC without Python: unzip, open, Setup page is all green, Arland quick test works.

## Later, only if it goes public

An installer (Inno Setup, free) with a Start menu entry and an uninstaller, built by the same workflow. Qt for Python
is LGPL: shipping it as separate DLLs in a folder, as here, is allowed; a notice file listing the licences goes in
the zip.

## Making a release

Push a tag, e.g. `git tag v0.2.0 && git push origin v0.2.0`. The workflow builds, checks the build (`rmt.exe --help`,
`rmt.exe --events detect`, the self-tests, and that the window opens), zips it and publishes the release.
*Run workflow* on the Actions page, or a pull request touching the app, builds and checks it without publishing; the
build is then a download on that run's page.
