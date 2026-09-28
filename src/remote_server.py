"""QAA AirType 入口：组装各模块、输出启动诊断并拉起 GUI。

本文件是打包入口（QAA-AirType.spec 指向这里），同时充当公共门面 ——
把各子模块中测试与诊断会用到的名字再导出一次。
"""

# --- 运行引导：必须置于其它 import 之前 ---
# 打包后的 .app 无控制台，只有先把 stdout/stderr 接到日志文件，
# 后面任何 import 期异常才不会永久丢失。
from bootstrap import setup_log, crash_guard, is_frozen, log_path

setup_log()

import os
import socket
import sys
import traceback

import tkinter as tk

from gui import ServerApp
from netinfo import get_all_ips, get_host_ip, get_ifaddrs
from paths import get_icon_path, get_search_dirs
from platform_paste import macos_accessibility_trusted
from server import AUTH_TOKEN, app, reset_type_rate_limit
from settings import (DEFAULT_PORT, DRY_RUN, MAX_TYPE_CHARS,
                      TYPE_RATE_LIMIT, TYPE_RATE_WINDOW, __version__)
from themes import list_themes, load_theme

__all__ = [
    '__version__',
    'AUTH_TOKEN',
    'DEFAULT_PORT',
    'DRY_RUN',
    'MAX_TYPE_CHARS',
    'TYPE_RATE_LIMIT',
    'TYPE_RATE_WINDOW',
    'app',
    'get_all_ips',
    'get_host_ip',
    'get_ifaddrs',
    'get_icon_path',
    'get_search_dirs',
    'list_themes',
    'load_theme',
    'macos_accessibility_trusted',
    'reset_type_rate_limit',
]


def log_startup_diagnostics():
    """frozen 模式下把关键运行时信息写进日志，便于排查资源路径与 IP 枚举问题"""
    if not is_frozen():
        return

    def append(text):
        # 每次都开新句柄并 fsync，保证即便后续步骤卡死，前面的内容也已落盘
        with open(log_path(), 'a', encoding='utf-8', errors='replace') as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())

    try:
        append("--- diagnostics begin ---\n")
        sample = load_theme('auto')
        info = [
            f"version       = {__version__}",
            f"dry_run       = {DRY_RUN}",
            f"default_port  = {DEFAULT_PORT}",
            f"type_limit    = {TYPE_RATE_LIMIT} req / {TYPE_RATE_WINDOW}s, max {MAX_TYPE_CHARS} chars",
            f"python        = {sys.version.split()[0]}",
            f"executable    = {sys.executable}",
            f"_MEIPASS      = {getattr(sys, '_MEIPASS', '(n/a)')}",
            f"search_dirs   = {get_search_dirs()}",
            f"themes        = {list_themes()}",
            f"icon          = {get_icon_path()}",
            f"hostname      = {socket.gethostname()}",
            f"host_ip       = {get_host_ip()}",
            f"all_ips       = {get_all_ips()}",
            f"accessibility = {macos_accessibility_trusted()}",
            f"theme=auto    = {len(sample)} bytes, 智能输入={'智能输入' in sample}",
            f"default       = {len(load_theme())} bytes",
            "--- diagnostics end ---",
            "",
        ]
        append("\n".join(info) + "\n")
    except Exception:
        append(traceback.format_exc())


@crash_guard
def main():
    log_startup_diagnostics()
    root = tk.Tk()
    # 挂在 root 上保留引用，避免 ServerApp 被垃圾回收
    root.server_app = ServerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
