"""平台适配：操作系统标识、辅助功能授权检测、真正的粘贴动作。"""
import ctypes
import platform
import subprocess
import time

import pyautogui
import pyperclip

from settings import DRY_RUN

# --- 平台标识 ---

IS_MAC = platform.system() == 'Darwin'
IS_WINDOWS = platform.system() == 'Windows'

# --- macOS 辅助功能权限 ---
# 打包成 .app 后权限主体从 Terminal 变成本应用，必须重新授予，
# 否则 pyautogui 的 Cmd+V 会静默失败、一个字都粘不进去。
_MAC_AS_FRAMEWORK = (
    '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices'
)
_MAC_ACCESSIBILITY_PANE = (
    'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'
)

def macos_accessibility_trusted() -> bool:
    """检测本进程是否拥有「辅助功能」权限。

    检测本身失败时返回 True —— 宁可让它自己表现出来，也不要误拦正常使用。
    """
    if not IS_MAC:
        return True
    try:
        handle = ctypes.cdll.LoadLibrary(_MAC_AS_FRAMEWORK)
        handle.AXIsProcessTrusted.restype = ctypes.c_bool
        handle.AXIsProcessTrusted.argtypes = []
        return bool(handle.AXIsProcessTrusted())
    except Exception:
        return True

def macos_open_accessibility_settings():
    """打开「系统设置 → 隐私与安全性 → 辅助功能」面板"""
    try:
        subprocess.run(['open', _MAC_ACCESSIBILITY_PANE], check=False)
    except Exception:
        pass

# Windows API 常量
if IS_WINDOWS:
    VK_SHIFT = 0x10
    VK_INSERT = 0x2D
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    MAPVK_VK_TO_VSC = 0

def send_shift_insert_windows():
    """使用 Windows API 发送 Shift+Insert 组合键（使用扫描码，兼容终端）"""
    if not IS_WINDOWS:
        return False

    try:
        user32 = ctypes.windll.user32

        # 获取扫描码（对于终端应用如 CMD/PowerShell 必须使用扫描码）
        shift_scan = user32.MapVirtualKeyW(VK_SHIFT, MAPVK_VK_TO_VSC)
        insert_scan = user32.MapVirtualKeyW(VK_INSERT, MAPVK_VK_TO_VSC)

        # 按下 Shift（使用扫描码）
        user32.keybd_event(VK_SHIFT, shift_scan, KEYEVENTF_SCANCODE, 0)
        time.sleep(0.05)

        # 按下 Insert（使用扫描码 + 扩展键标志）
        user32.keybd_event(VK_INSERT, insert_scan, KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY, 0)
        time.sleep(0.02)

        # 释放 Insert（使用扫描码 + 扩展键标志）
        user32.keybd_event(VK_INSERT, insert_scan, KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)

        # 释放 Shift（使用扫描码）
        user32.keybd_event(VK_SHIFT, shift_scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)

        return True
    except Exception as e:
        print(f"Windows API error: {e}")
        return False


def do_paste():
    """粘贴到当前焦点窗口（跨平台）。

    macOS 绝大多数应用不响应 Shift+Insert，标准粘贴是 Cmd+V，
    因此 Mac 分支使用 command+v；若 pyautogui 失败则回退到 AppleScript。
    """
    if DRY_RUN:
        return   # 测试模式：不产生真实按键
    if IS_WINDOWS:
        if send_shift_insert_windows():
            return
        pyautogui.hotkey('shift', 'insert')
    elif IS_MAC:
        try:
            pyautogui.hotkey('command', 'v')
        except Exception:
            import subprocess
            subprocess.run(
                ['osascript', '-e',
                 'tell application "System Events" to keystroke "v" using command down'],
                check=False,
            )
    else:
        pyautogui.hotkey('shift', 'insert')


def paste_text(text):
    """复制到剪切板并粘贴。QAA_DRY_RUN=1 时跳过真实动作，供测试覆盖成功路径"""
    if DRY_RUN:
        return
    pyperclip.copy(text)
    time.sleep(0.1)
    do_paste()
