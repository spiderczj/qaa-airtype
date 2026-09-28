"""手机页面主题：加载与文件名消毒（防 ../ 路径穿越）。"""
import os

from paths import get_search_dirs

def sanitize_theme_name(theme_name) -> str:
    """把 URL 参数归一化成主题文件名（不含 .html），非法输入返回空串"""
    if not theme_name:
        return ''
    name = str(theme_name).strip()
    if not name or name.lower() == 'default':
        return ''
    name = name.replace('\\', '/').split('/')[-1]          # 丢掉任何目录部分
    if name.lower().endswith('.html'):
        name = name[:-5]
    name = name.strip()
    if not name or name in ('.', '..'):
        return ''
    if not all(c.isalnum() or c in '-_.' for c in name):
        return ''
    return name


def list_themes() -> list:
    """扫描搜索目录，列出可用主题名（不含 default）"""
    names = set()
    for d in get_search_dirs():
        try:
            for fn in os.listdir(d):
                if fn.endswith('.html') and fn != 'default.html':
                    names.add(fn[:-5])
        except OSError:
            pass
    return sorted(names)


def load_theme(theme_name=None):
    """加载主题HTML文件"""
    search_dirs = get_search_dirs()

    # 优先级1: URL参数指定的主题（已消毒，避免 ../ 穿越和 auto.html.html）
    safe_name = sanitize_theme_name(theme_name)
    if safe_name:
        for d in search_dirs:
            theme_path = os.path.join(d, f"{safe_name}.html")
            if os.path.isfile(theme_path):
                try:
                    with open(theme_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception:
                    pass

    # 优先级2: custom.html，优先级3: default.html
    for filename in ('custom.html', 'default.html'):
        for d in search_dirs:
            default_path = os.path.join(d, filename)
            if os.path.isfile(default_path):
                try:
                    with open(default_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception:
                    pass

    # 回退到基本错误页面
    return """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>主题加载失败</title></head>
<body><h1>主题加载失败</h1><p>请检查主题文件是否存在</p></body>
</html>"""
