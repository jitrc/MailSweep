# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for MailSweep (onefile mode)."""

a = Analysis(
    ['mailsweep/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'imapclient',
        'squarify',
        'keyring',
        'keyring.backends.SecretService',
        'keyring.backends.fail',
        'google.auth',
        'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'msal',
        'chardet',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MailSweep',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
