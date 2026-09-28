"""资源路径：开发环境与 PyInstaller 打包后都能找到主题与图标。"""
import os
import platform
import sys

# --- 资源路径处理 ---
def get_base_path():
    """获取基础路径，支持开发环境和打包后的环境"""
    if getattr(sys, 'frozen', False):
        # 打包后的exe文件
        return os.path.dirname(sys.executable)
    else:
        # 开发环境
        return os.path.dirname(os.path.abspath(__file__))

def get_search_dirs() -> list:
    """主题文件搜索目录，按优先级排列。

    打包后 PyInstaller 把 datas 放在 sys._MEIPASS 下（.app 中为 Contents/Frameworks），
    其中 default.html 在 `<_MEIPASS>/src/`、主题在 `<_MEIPASS>/theme/`，
    是「子目录」而不是根目录 —— 因此每个根都必须展开出 /src 和 /theme，
    只加 _MEIPASS 本身是扫不到的。
    """
    roots = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        roots.append(sys._MEIPASS)
    roots.append(get_base_path())                      # 开发环境=src/；打包=Contents/MacOS
    roots.append(os.path.dirname(get_base_path()))     # 开发环境=项目根；打包=Contents

    dirs = []
    for root in roots:
        dirs.append(root)
        dirs.append(os.path.join(root, 'theme'))
        dirs.append(os.path.join(root, 'src'))

    seen, ordered = set(), []
    for d in dirs:
        d = os.path.normpath(d)
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    return ordered


def _icon_search_dirs() -> list:
    """图标文件的搜索目录，兼容开发环境与打包后的环境"""
    dirs = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        dirs.append(sys._MEIPASS)
        dirs.append(os.path.dirname(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    dirs += [os.getcwd(), here, project_root, os.path.join(project_root, 'assets')]

    seen, ordered = set(), []
    for d in dirs:
        d = os.path.normpath(d)
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    return ordered


def _find_icon_file(exts) -> str:
    """按扩展名优先级在搜索目录里找 icon 文件，找不到返回 None"""
    for ext in exts:
        for d in _icon_search_dirs():
            icon_path = os.path.join(d, 'icon' + ext)
            if os.path.isfile(icon_path):
                return icon_path
    return None


def get_icon_path():
    """获取图标路径。

    macOS 的 Tk 走 iconbitmap 时用 .icns，Windows 用 .ico。
    """
    exts = ('.icns',) if platform.system() == 'Darwin' else ('.ico',)
    return _find_icon_file(exts)
