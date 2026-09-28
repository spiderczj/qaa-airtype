# -*- mode: python ; coding: utf-8 -*-
"""
QAA AirType 打包配置（PyInstaller）

构建：  .venv/bin/pyinstaller QAA-AirType.spec --noconfirm --clean
产物：  dist/QAA AirType.app

关键点：
  - datas 必须把 default.html / theme/*.html / icon.* 打进去，
    否则 load_theme() 和 get_icon_path() 在打包后找不到文件。
  - websockets 与 pystray 依赖各自的 hook（lazy import），由 PyInstaller 自动收集。
  - 无 Apple 开发者证书 → ad-hoc 签名，每次重建后需重新授予「辅助功能」权限。
"""
import glob
import os
import re

PROJECT = os.path.abspath(SPECPATH)
SRC = os.path.join(PROJECT, 'src')
ASSETS = os.path.join(PROJECT, 'assets')

APP_NAME = 'QAA AirType'
BUNDLE_ID = 'com.qaa.airtype'


def _read_version() -> str:
    """版本号的唯一来源是 src/remote_server.py 里的 __version__。

    这里用文本正则读取而不是 import，避免执行业务代码（它会连带启动
    setup_log、创建 Flask app 等），也就不怕 spec 跑在没有依赖的环境里。
    """
    path = os.path.join(SRC, 'remote_server.py')
    with open(path, encoding='utf-8') as fh:
        found = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", fh.read(), re.M)
    if not found:
        raise RuntimeError(f'未能在 {path} 中找到 __version__ 定义')
    return found.group(1)


VERSION = _read_version()

# --- 打包进去的资源文件：(源路径, 包内目标目录) ---
datas = [
    (os.path.join(SRC, 'default.html'), 'src'),
    (os.path.join(ASSETS, 'icon.ico'), '.'),
    (os.path.join(ASSETS, 'icon.icns'), '.'),
    (os.path.join(ASSETS, 'icon.png'), '.'),   # Tk iconphoto 只认 PNG
]
datas += [
    (path, 'theme')
    for path in sorted(glob.glob(os.path.join(PROJECT, 'theme', '*.html')))
]

# 静态模块图扫不到、但运行时确实会 import 的模块
hiddenimports = [
    'qrcode.image.pil',   # qrcode 在函数体内按需 import
    'PIL.ImageTk',        # QR 码显示用
    'websockets.asyncio.client',  # websockets.connect 的真实指向
]

# 只保留 macOS 用得到的后端，减少构建噪音和体积
excludes = [
    'tkinter.test',
    'unittest',
    'pydoc',
    'pystray._gtk',
    'pystray._xorg',
    'pystray._win32',
    'pystray._appindicator',
]

a = Analysis(
    [os.path.join(SRC, 'remote_server.py')],
    pathex=[SRC],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ASSETS, 'icon.icns'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f'{APP_NAME}.app',
    icon=os.path.join(ASSETS, 'icon.icns'),
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'CFBundleShortVersionString': VERSION,
        'NSPrincipalClass': 'NSApplication',
    },
)
