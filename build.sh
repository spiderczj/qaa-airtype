#!/usr/bin/env bash
#
# 一键打包 QAA AirType 为 macOS 可安装软件：
#   1. 生成图标（icon.png / icon.ico / icon.icns）
#   2. PyInstaller 构建 .app
#   3. ad-hoc 签名并校验（无 Apple 开发者证书）
#   4. 打包 DMG（内含 /Applications 软链，拖拽即可安装）
#
# 产物：
#   dist/QAA AirType.app
#   dist/QAA-AirType.dmg
#
set -euo pipefail

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    # 本地开发：固定用虚拟环境里的解释器
    PYTHON=".venv/bin/python"
    PYINSTALLER=".venv/bin/pyinstaller"
else
    # CI / 没建 .venv 的机器：用 PATH 里的解释器
    PYTHON="python3"
    PYINSTALLER="pyinstaller"
fi
APP_NAME="QAA AirType"
BUNDLE="dist/${APP_NAME}.app"
DMG="dist/QAA-AirType.dmg"
ONEDIR="dist/${APP_NAME}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "错误：找不到 Python（$PYTHON），请先安装或创建 .venv" >&2
    exit 1
fi
if ! command -v "$PYINSTALLER" >/dev/null 2>&1; then
    echo "错误：找不到 pyinstaller，请先执行 pip install -r requirements.txt" >&2
    exit 1
fi

echo "==> 1/4 生成图标"
"$PYTHON" src/generate_icon.py

echo "==> 2/4 PyInstaller 构建 .app"
"$PYINSTALLER" QAA-AirType.spec --noconfirm --clean

echo "==> 3/4 ad-hoc 签名并校验"
codesign --force --deep --sign - "$BUNDLE" >/dev/null 2>&1
codesign --verify --deep --strict "$BUNDLE"
echo "      签名校验通过"

echo "==> 4/4 打包 DMG"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp -R "$BUNDLE" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" -ov -format UDZO "$DMG" >/dev/null

# PyInstaller 的 onedir 中间产物，BUNDLE 已经拷走，留着只是白占空间
rm -rf "$ONEDIR" build

echo
echo "打包完成"
echo "  .app : $BUNDLE"
echo "  DMG  : $DMG"
du -sh "$BUNDLE" "$DMG"
echo
echo "提示：ad-hoc 签名的 app 每次重新打包 CDHash 都会变，"
echo "      系统会当作新 app，「辅助功能」权限需要重新授予一次。"
