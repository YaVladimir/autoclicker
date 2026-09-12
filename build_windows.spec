# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows executable.

Run on Windows with: pyinstaller --noconfirm build_windows.spec
The resulting application is placed in dist/Автокликер.exe.
"""


analysis = Analysis(
    ["autoclicker.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="Автокликер",
    console=False,
)
