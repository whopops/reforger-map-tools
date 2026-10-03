# PyInstaller build of the desktop app (docs/packaging.md). Run on Windows from this folder:
#   pip install -r requirements.txt pyinstaller
#   pyinstaller --noconfirm ReforgerMapTools.spec
# and the app is in dist\ReforgerMapTools\: "Reforger Map Tools.exe" (the window) and rmt.exe (the worker the window
# starts, and the command line), sharing one _internal\ folder. GitHub builds it: .github/workflows/package.yml.

import ast
import glob
import os

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.abspath(SPECPATH)

# The Labs scripts aren't imported by the app: they are run from the bundle as files (rmt_gui.py --script), so they
# go in as data, and whatever they import goes in as hidden imports.
LAB_SCRIPTS = [f for f in glob.glob(os.path.join(HERE, "*.py")) if os.path.basename(f) not in ("rmt.py", "rmt_gui.py")]
LAB_SCRIPTS += glob.glob(os.path.join(HERE, "audible", "*.py"))
LOCAL = {os.path.splitext(os.path.basename(f))[0] for f in LAB_SCRIPTS} | {"audible"}


def imports_of(path):
    names = set()
    for node in ast.walk(ast.parse(open(path, encoding="utf8").read())):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return {n for n in names if n.split(".")[0] not in LOCAL}


hidden = set(collect_submodules("rmtlib")) | {"rmt", "unittest", "unittest.__main__", "unittest.mock",
                                              "scipy.ndimage", "scipy.signal"}
for f in LAB_SCRIPTS:
    hidden |= imports_of(f)

datas = [(os.path.join(HERE, "addon"), "addon"), (os.path.join(HERE, "docs"), "docs"),
         (os.path.join(HERE, "README.md"), "."),
         (os.path.join(HERE, "rmtgui", "icon.ico"), "rmtgui"), (os.path.join(HERE, "rmtgui", "check.svg"), "rmtgui")]
datas += [(f, os.path.relpath(os.path.dirname(f), HERE)) for f in LAB_SCRIPTS]
for f in glob.glob(os.path.join(HERE, "audible", "*")):
    if not f.endswith(".py") and os.path.isfile(f) and os.path.basename(f) != "pakindex.json":
        datas.append((f, "audible"))

# Qt parts the app doesn't use: a smaller download.
EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore",
            "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D", "PySide6.QtMultimedia",
            "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth",
            "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
            "tkinter", "matplotlib"]

a = Analysis([os.path.join(HERE, "rmt_gui.py")], pathex=[HERE], datas=datas, hiddenimports=sorted(hidden),
             excludes=EXCLUDES, noarchive=False)
pyz = PYZ(a.pure)
icon = os.path.join(HERE, "rmtgui", "icon.ico")
window = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Reforger Map Tools", console=False, icon=icon,
             upx=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name="rmt", console=True, icon=icon, upx=False)
COLLECT(window, worker, a.binaries, a.datas, name="ReforgerMapTools", upx=False)
