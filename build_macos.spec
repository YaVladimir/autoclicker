# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the macOS application bundle.

Run with: pyinstaller --noconfirm build_macos.spec
The resulting application is placed in dist/Автокликер.app.
"""

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = (
    ["macos_cocoa_ui"]
    + collect_submodules("AppKit")
    + collect_submodules("Foundation")
    + collect_submodules("Quartz")
)

analysis = Analysis(
    ["autoclicker_macos.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
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
app = BUNDLE(
    exe,
    name="Автокликер.app",
    bundle_identifier="io.github.yavladimir.autoclicker",
    info_plist={
        "CFBundleDisplayName": "Автокликер",
        "CFBundleShortVersionString": "1.1.0",
        "CFBundleVersion": "1.1.0",
        "NSAppleEventsUsageDescription": "Автокликер отправляет клики только по команде пользователя.",
    },
)
