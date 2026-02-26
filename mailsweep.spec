# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for MailSweep (onefile mode, .app bundle on macOS)."""
import sys

import certifi

a = Analysis(
    ['mailsweep/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        (certifi.where(), 'certifi'),
        ('mailsweep/resources/icon.svg', 'mailsweep/resources'),
    ],
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
        'certifi',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthook_certifi.py'],
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

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='MailSweep.app',
        bundle_identifier='com.jitrc.mailsweep',
        info_plist={
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
            'CFBundleShortVersionString': '0.5.1',
        },
    )
