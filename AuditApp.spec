# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PROJECT = Path(SPECPATH)
datas = [
    (str(PROJECT / "app.py"), "."),
    (str(PROJECT / "db.py"), "."),
    (str(PROJECT / "access.py"), "."),
    (str(PROJECT / "iso_loader.py"), "."),
    (str(PROJECT / "report.py"), "."),
    (str(PROJECT / "app_paths.py"), "."),
]
datas += [(str(pad), ".") for pad in PROJECT.glob("*.xlsx") if not pad.name.startswith("~$")]

binaries: list = []
hiddenimports = [
    "streamlit",
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "streamlit.runtime.credentials",
    "streamlit.runtime.runtime",
    "streamlit.components.v1",
    "pandas",
    "openpyxl",
    "access",
    "db",
    "iso_loader",
    "report",
    "app_paths",
]

for package in ("streamlit", "altair"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(PROJECT / "launch_auditapp.py")],
    pathex=[str(PROJECT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter", "IPython", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AuditApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AuditApp",
)
