# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/Giuseppe Falliti/Desktop/Spoofer/main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/Giuseppe Falliti/Desktop/Spoofer/config.json', '.')],
    hiddenimports=['PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'core', 'core.mac_spoofer', 'core.hwid_spoofer', 'core.registry_utils', 'core.driver_utils', 'core.smbios_type1', 'gui', 'gui.main_window', 'gui.config_dialog', 'winreg', 'ctypes', 'win32service', 'win32file', 'win32con', 'pywintypes', 'win32api'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='HWIDSpoofer',
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
)
