"""
运行环境引导：frozen（PyInstaller 打包）模式下的日志与崩溃兜底。

打包后的 .app 是 windowed 模式，没有控制台，run.sh 也不存在，
因此必须在解释器层面把 stdout/stderr 接到日志文件，否则任何异常都会永久丢失。
"""
import os
import platform
import sys
import time
import traceback

_CONFIG_SUBDIR = ('QAA-AirType',) if platform.system() == 'Windows' else ('qaa-airtype',)


def config_dir() -> str:
    if platform.system() == 'Windows':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.path.join(os.path.expanduser('~'), '.config')
    path = os.path.join(base, *_CONFIG_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def log_path() -> str:
    return os.path.join(config_dir(), 'qaa.log')


# 超过该大小就在下次启动时轮转成 qaa.log.1，避免日志无限增长
LOG_MAX_BYTES = 5 * 1024 * 1024


def _rotate_if_needed(path: str) -> None:
    """日志过大时轮转：qaa.log → qaa.log.1（覆盖旧备份）"""
    try:
        if not os.path.exists(path) or os.path.getsize(path) < LOG_MAX_BYTES:
            return
        backup = path + '.1'
        if os.path.exists(backup):
            os.remove(backup)
        os.rename(path, backup)
    except OSError:
        pass   # 轮转失败不该影响启动


def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def setup_log() -> bool:
    """把 stdout/stderr 接到日志文件。仅 frozen 模式生效，开发环境交给 run.sh。"""
    if not is_frozen():
        return False
    try:
        _rotate_if_needed(log_path())
        stamp = time.strftime('%a %b %d %H:%M:%S %Y')
        handle = open(log_path(), 'a', encoding='utf-8', buffering=1, errors='replace')
        handle.write(f"=== launch {stamp} ===\n")
        sys.stdout = handle
        sys.stderr = handle
        # windowed 模式没有真实 stdin，显式置空避免子进程/库误读阻塞
        if sys.stdin is None or sys.stdin.closed:
            sys.stdin = None
        return True
    except Exception:
        return False


def crash_guard(func):
    """包装 main：未捕获异常写入日志并弹框，避免 windowed 模式静默退出"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            detail = traceback.format_exc()
            try:
                with open(log_path(), 'a', encoding='utf-8', errors='replace') as fh:
                    fh.write(detail)
            except Exception:
                pass
            if is_frozen():
                try:
                    from tkinter import messagebox
                    messagebox.showerror(
                        "QAA AirType 启动失败",
                        f"发生未处理的异常，详情见：\n{log_path()}\n\n{detail[-800:]}"
                    )
                except Exception:
                    pass
                # 已经弹过框并写过日志，用非零退出码收尾，
                # 避免再抛原始异常让打包壳弹出第二个报错框。
                raise SystemExit(1)
            sys.stderr.write(detail)
            raise
    return wrapper
