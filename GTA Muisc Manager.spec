# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = []
binaries = []
hiddenimports = []

datas += collect_data_files("customtkinter")
datas += collect_data_files("mutagen")
datas += collect_data_files("yt_dlp")
datas += collect_data_files("pygame", excludes=["**/tests/*", "**/examples/*"])

binaries += collect_dynamic_libs("pygame")

hiddenimports += collect_submodules("customtkinter")
hiddenimports += collect_submodules("mutagen")
hiddenimports += collect_submodules("yt_dlp")
hiddenimports += [
    name for name in collect_submodules("pygame")
    if not name.startswith(("pygame.tests", "pygame.examples"))
]

if os.path.exists("ffmpeg.exe"):
    binaries += [("ffmpeg.exe", ".")]
if os.path.exists("ffprobe.exe"):
    binaries += [("ffprobe.exe", ".")]
if os.path.exists("app.ico"):
    datas += [("app.ico", ".")]

icon_path = "app.ico" if os.path.exists("app.ico") else None

a = Analysis(
    ["gta_usermusic_manager.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pygame.tests", "pygame.examples"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GTA Muisc Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    onefile=True,
)
