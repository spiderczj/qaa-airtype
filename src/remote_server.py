# --- 运行引导：必须置于所有 import 之前 ---
# 打包后的 .app 无控制台，只有先把 stdout/stderr 接到日志文件，
# 后面任何 import 期异常才不会永久丢失。
from bootstrap import setup_log, crash_guard, is_frozen, log_path
setup_log()

# 单一版本号来源：QAA-AirType.spec 和启动诊断日志都从这里读取。
# 发版时只需改这一行。
__version__ = '1.0.0'

import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from flask import Flask, request, render_template_string, Response
import pyautogui
import pyperclip
import platform
import time
import logging
import qrcode
from PIL import Image, ImageTk
import io
import pystray
from pystray import MenuItem as item
import os
import sys
import tempfile
import ctypes
import asyncio
import hashlib
import json
import secrets
import subprocess
import traceback

# CF 模式依赖（可选）
try:
    import websockets
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CF_AVAILABLE = True
except (ImportError, RuntimeError):
    CF_AVAILABLE = False

# --- 配置文件 ---
def get_config_path():
    """获取配置文件路径"""
    if IS_WINDOWS:
        config_dir = os.path.join(os.environ.get('APPDATA', ''), 'QAA-AirType')
    else:
        config_dir = os.path.join(os.path.expanduser('~'), '.config', 'qaa-airtype')
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'config.json')

def load_config() -> dict:
    """加载配置"""
    try:
        config_path = get_config_path()
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_config(config: dict):
    """保存配置"""
    try:
        config_path = get_config_path()
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")

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

# --- Flask 应用配置 ---
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- 主题系统 ---

IS_MAC = platform.system() == 'Darwin'
IS_WINDOWS = platform.system() == 'Windows'
PASTE_KEY = 'command' if IS_MAC else 'ctrl'

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

# --- 访问令牌（持久化到配置文件） ---
TOKEN_COOKIE = 'qaa_tok'

def get_auth_token() -> str:
    """读取或生成访问令牌，写入 config.json 保证长期有效"""
    try:
        config = load_config()
        token = config.get('auth_token')
        if isinstance(token, str) and len(token) >= 16 and token.isprintable():
            return token
        token = secrets.token_urlsafe(16)
        config['auth_token'] = token
        save_config(config)
        return token
    except Exception:
        return secrets.token_urlsafe(16)

AUTH_TOKEN = get_auth_token()

def build_url(ip: str, port, theme: str = '') -> str:
    """拼出手机访问用的完整 URL，自动带上主题和访问令牌"""
    url = f"http://{ip}:{port}/"
    if theme:
        url += f"?theme={theme}"
    return with_token(url)

def with_token(url: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}t={AUTH_TOKEN}"

def auth_ok() -> bool:
    """校验请求携带的令牌（URL 参数或 Cookie）"""
    token = request.args.get('t') or request.cookies.get(TOKEN_COOKIE) or ''
    return bool(token) and token == AUTH_TOKEN

FORBIDDEN_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>访问受限</title></head>
<body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;color:#333">
<h1>403 · 链接已失效</h1>
<p>请回到电脑前重新扫描二维码获取新链接。</p>
</body></html>"""

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
    """复制到剪切板并粘贴"""
    pyperclip.copy(text)
    time.sleep(0.1)
    do_paste()


# --- CF 模式：cfchat 加密协议 ---
def derive_key_and_room(password: str) -> tuple:
    """从密码派生 AES 密钥和房间 ID"""
    password = password.strip() or 'noset'
    encoded = password.encode('utf-8')
    hash_bytes = hashlib.sha256(encoded).digest()
    room_id = hash_bytes.hex()
    return hash_bytes, room_id


def decrypt_message(key: bytes, iv_b64: str, data_b64: str) -> str:
    """AES-GCM 解密消息"""
    import base64
    iv = base64.b64decode(iv_b64)
    data = base64.b64decode(data_b64)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, data, None)
    return plaintext.decode('utf-8')


class CFChatClient:
    """CF 模式 WebSocket 客户端"""
    def __init__(self, worker_url: str, password: str, on_message=None, on_status=None):
        self.worker_url = worker_url.rstrip('/')
        self.password = password
        self.on_message = on_message
        self.on_status = on_status
        self.key, self.room_id = derive_key_and_room(password)
        self.ws = None
        self.running = False
        self._loop = None
        self._thread = None

    def _get_ws_url(self) -> str:
        """构建 WebSocket URL"""
        url = self.worker_url
        if url.startswith('https://'):
            url = 'wss://' + url[8:]
        elif url.startswith('http://'):
            url = 'ws://' + url[7:]
        elif not url.startswith('ws'):
            url = 'wss://' + url
        return f"{url}/ws/{self.room_id}"

    async def _connect(self):
        """连接并监听消息"""
        ws_url = self._get_ws_url()
        if self.on_status:
            self.on_status('connecting', '连接中...')

        try:
            async with websockets.connect(ws_url) as ws:
                self.ws = ws
                if self.on_status:
                    self.on_status('connected', '已连接 CF')

                while self.running:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        self._handle_message(raw)
                    except asyncio.TimeoutError:
                        continue
                    except websockets.ConnectionClosed:
                        break

        except Exception as e:
            if self.on_status:
                self.on_status('error', f'连接失败: {e}')

        finally:
            self.ws = None
            if self.on_status and self.running:
                self.on_status('disconnected', '已断开，重连中...')

    def _handle_message(self, raw: str):
        """处理收到的消息"""
        try:
            payload = json.loads(raw)
            msg_type = payload.get('type', 'text').lower()

            if msg_type != 'text':
                return

            iv = payload.get('iv')
            data = payload.get('data')
            if not iv or not data:
                return

            text = decrypt_message(self.key, iv, data)
            if self.on_message:
                self.on_message(text)

        except Exception as e:
            print(f"消息处理错误: {e}")

    def _run_loop(self):
        """在独立线程运行事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        while self.running:
            try:
                self._loop.run_until_complete(self._connect())
            except Exception as e:
                print(f"连接错误: {e}")

            if self.running:
                time.sleep(2)

        self._loop.close()

    def start(self):
        """启动客户端"""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止客户端"""
        self.running = False
        if self.ws and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self._loop)
            except:
                pass


@app.route('/')
def index():
    if not auth_ok():
        return Response(FORBIDDEN_HTML, status=403, mimetype='text/html')
    theme = request.args.get('theme')
    resp = Response(load_theme(theme), mimetype='text/html')
    # 下发 Cookie，让前端页面里的 fetch('/type') 自动带上令牌
    resp.set_cookie(TOKEN_COOKIE, AUTH_TOKEN, httponly=True,
                    samesite='Lax', max_age=30 * 24 * 3600, path='/')
    return resp

@app.route('/type', methods=['POST'])
def type_text():
    if not auth_ok():
        return {'success': False, 'error': 'unauthorized'}, 403
    try:
        data = request.get_json(silent=True) or {}
        text = data.get('text', '')
        if text:
            pyperclip.copy(text)
            time.sleep(0.1)
            do_paste()
            return {'success': True}
    except Exception as e:
        print(f"Error in type_text: {e}")
    return {'success': False}

def get_host_ip():
    """获取主要的本机 IP 地址"""
    ip = '127.0.0.1'
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        pass
    finally:
        if s is not None:
            s.close()
    return ip

def get_ifaddrs():
    """用 ioctl 直接读网卡 IPv4，不经过 DNS/mDNS，不会阻塞"""
    found = []
    try:
        import fcntl
        import struct as _struct

        # macOS 的 SIOCGIFADDR = _IOWR('i', 13, struct ifreq)
        SIOCGIFADDR = 0xC020690D
        # ifreq = 16 字节名字 + sockaddr；sockaddr_in 里 sin_addr 位于偏移 4，
        # 即整体偏移 20。
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for _idx, name in socket.if_nameindex():
                try:
                    request = _struct.pack('32s', name.encode('utf-8')[:15])
                    response = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, request)
                    ip = socket.inet_ntoa(response[20:24])
                except OSError:
                    continue
                if ip not in ('127.0.0.1', '0.0.0.0') and ip not in found:
                    found.append(ip)
    except Exception as e:
        print(f"get_ifaddrs 失败: {e!r}")
    return found


def get_all_ips(timeout: float = 3.0):
    """获取所有可用的本机 IP 地址。

    优先走 ioctl 枚举网卡（无 DNS、无阻塞）；拿不到再退回 getaddrinfo，
    而 macOS 的 getaddrinfo 遇到 .local 主机名会走 mDNS 并长时间挂死，
    所以放进工作线程加超时；最后 UDP 探测兜底，保证总能拿到真实局域网 IP。
    """
    ips = []
    errors = []

    def resolve():
        try:
            hostname = socket.gethostname()
            for addr in socket.getaddrinfo(hostname, None):
                ip = addr[4][0]
                # 只保留 IPv4 地址，排除回环地址
                if ':' not in ip and ip not in ('127.0.0.1', '0.0.0.0') and ip not in ips:
                    ips.append(ip)
        except Exception as e:
            errors.append(f"getaddrinfo 失败: {e!r}")

    ifaddrs = get_ifaddrs()
    if ifaddrs:
        ips.extend(ifaddrs)
    else:
        worker = threading.Thread(target=resolve, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            print(f"get_all_ips: DNS 解析超过 {timeout}s 未返回，改用 UDP 探测")

    for message in errors:
        print(f"get_all_ips: {message}")

    # UDP 探测不依赖主机名解析，作为兜底保证总能拿到真实局域网 IP
    try:
        primary = get_host_ip()
        if primary and ':' not in primary and primary not in ('127.0.0.1', '0.0.0.0') and primary not in ips:
            ips.append(primary)
    except Exception as e:
        print(f"get_all_ips: get_host_ip 失败: {e!r}")

    # 如果没有找到任何 IP，添加默认值
    if not ips:
        ips.append('127.0.0.1')

    # IP 分类排序
    # 优先级：192.168.x.x > 10.x.x.x > 其他 > 虚拟网卡
    priority_192 = []  # 192.168.x.x (家庭/办公网络)
    priority_10 = []   # 10.x.x.x (企业网络)
    other_ips = []     # 其他真实 IP
    virtual_ips = []   # 虚拟网卡 IP

    for ip in ips:
        if ip.startswith('192.168.'):
            priority_192.append(ip)
        elif ip.startswith('10.'):
            priority_10.append(ip)
        elif ip.startswith('172.'):
            # 检查是否是虚拟网卡
            parts = ip.split('.')
            if len(parts) >= 2:
                second = int(parts[1])
                # Docker: 172.17.x.x, 172.18.x.x
                # Windows 虚拟网卡: 172.16.x.x
                # 私有网络范围: 172.16-31.x.x
                if 16 <= second <= 31:
                    virtual_ips.append(ip)
                else:
                    other_ips.append(ip)
        elif ip.startswith('198.18.'):
            # Clash 等代理工具虚拟网卡
            virtual_ips.append(ip)
        else:
            other_ips.append(ip)

    # 重新组合：优先级从高到低
    ips = priority_192 + priority_10 + other_ips + virtual_ips

    # 将主要 IP 移到对应分类的第一位（保持分类顺序）
    main_ip = get_host_ip()
    if main_ip in ips:
        ips.remove(main_ip)
        # 根据主要 IP 的类型，插入到对应分类的开头
        if main_ip.startswith('192.168.'):
            insert_pos = 0
        elif main_ip.startswith('10.'):
            insert_pos = len(priority_192)
        else:
            insert_pos = len(priority_192) + len(priority_10)
        ips.insert(insert_pos, main_ip)

    # 在最前面添加 0.0.0.0（监听所有网卡）
    ips.insert(0, '0.0.0.0 (所有网卡)')

    return ips

# --- GUI 主程序 ---
class ServerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"QAA AirType {__version__}")
        # 增加高度以容纳二维码
        self.root.geometry("512x640")
        self.root.resizable(True, True)
        self.root.minsize(380, 480)  # 最小尺寸

        # 绑定窗口关闭事件（正常退出）
        self.root.protocol('WM_DELETE_WINDOW', self.quit_app)

        # 设置窗口图标
        # Tk 的 iconbitmap 在 macOS 上吃 .icns 时经常画成通用占位图，
        # 所以再用 iconphoto(png) 覆盖一次；两条路径的结果都记进日志方便排查。
        icon_notes = []
        try:
            icon_path = get_icon_path()
            if icon_path:
                self.root.iconbitmap(icon_path)
                icon_notes.append(f'iconbitmap={os.path.basename(icon_path)}')
        except Exception as e:
            icon_notes.append(f'iconbitmap FAIL {e!r}')
        try:
            png_path = _find_icon_file(('.png',))
            if png_path:
                self.root.iconphoto(True, tk.PhotoImage(file=png_path))
                icon_notes.append(f'iconphoto={os.path.basename(png_path)}')
            else:
                icon_notes.append('iconphoto 缺 icon.png')
        except Exception as e:
            icon_notes.append(f'iconphoto FAIL {e!r}')
        print('图标设置:', '; '.join(icon_notes))

        # 系统托盘图标
        self.tray_icon = None
        self.create_tray_icon()

        # 居中屏幕
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - 512) // 2
        y = (screen_height - 640) // 2
        self.root.geometry(f"512x640+{x}+{y}")

        self.all_ips = get_all_ips()
        self.ip_var = tk.StringVar(value=self.all_ips[0])
        self.is_running = False
        self.cf_client = None  # CF 模式客户端
        self.cf_mode = False   # 是否为 CF 模式

        # 加载配置
        self.config = load_config()
        saved_mode = self.config.get('mode', 'lan')  # lan 或 cf
        saved_port = self.config.get('port', '5000')
        saved_ip = self.config.get('ip', '')
        saved_cf_url = self.config.get('cf_url', '')
        saved_cf_key = self.config.get('cf_key', '')

        # 在 IP 列表末尾添加 CF 模式选项
        self.all_ips.append('Cloudflare Chat Workers')

        # 主容器
        main_frame = tk.Frame(root, padx=20, pady=20)
        main_frame.pack(expand=True, fill='both')

        # --- macOS 辅助功能权限横幅（仅未授权时显示） ---
        self.perm_frame = tk.Frame(main_frame, bg="#fff4f4", padx=10, pady=8,
                                   highlightbackground="#ffd6d6", highlightthickness=1)
        tk.Label(self.perm_frame,
                 text="⚠ 未授权「辅助功能」，手机发来的文字不会被粘贴到电脑上",
                 bg="#fff4f4", fg="#c0392b", font=("Arial", 9, "bold"),
                 justify='left', wraplength=440).pack(anchor='w')
        tk.Label(self.perm_frame,
                 text="打开系统设置 → 隐私与安全性 → 辅助功能，点 ➕ 加入 QAA AirType，再点「重新检测」",
                 bg="#fff4f4", fg="#8a4a4a", font=("Arial", 8),
                 justify='left', wraplength=440).pack(anchor='w', pady=(2, 0))
        perm_btn_row = tk.Frame(self.perm_frame, bg="#fff4f4")
        perm_btn_row.pack(anchor='w', pady=(6, 0))
        tk.Button(perm_btn_row, text="打开系统设置", command=macos_open_accessibility_settings,
                  font=("Arial", 9), relief="flat", bg="#ff3b30", fg="white",
                  padx=10, pady=3, cursor="hand2").pack(side='left')
        tk.Button(perm_btn_row, text="重新检测", command=self.refresh_permission_banner,
                  font=("Arial", 9), relief="flat", bg="#8e8e93", fg="white",
                  padx=10, pady=3, cursor="hand2").pack(side='left', padx=(8, 0))
        # 此时不 pack，位置交给 refresh_permission_banner 决定

        # 模式/IP 选择
        self.mode_label = tk.Label(main_frame, text="连接模式:", font=("Arial", 10, "bold"))
        self.mode_label.pack(anchor='w')
        self.ip_combo = ttk.Combobox(main_frame, textvariable=self.ip_var,
                                     values=self.all_ips, font=("Arial", 10), state='readonly')
        self.ip_combo.pack(fill='x', pady=(0, 10))
        self.ip_combo.bind('<<ComboboxSelected>>', self.on_mode_changed)

        # --- 局域网模式控件 ---
        self.lan_frame = tk.Frame(main_frame)
        self.lan_frame.pack(fill='x', pady=(0, 10))

        # 端口输入（标签和输入框在同一行）
        port_row = tk.Frame(self.lan_frame)
        port_row.pack(fill='x', pady=(0, 5))
        tk.Label(port_row, text="端口:", font=("Arial", 10, "bold"), width=10, anchor='w').pack(side='left')
        self.port_var = tk.StringVar(value=saved_port)
        self.port_entry = tk.Entry(port_row, textvariable=self.port_var, font=("Arial", 10))
        self.port_entry.pack(side='left', fill='x', expand=True)

        # 主题名称输入（标签和输入框在同一行）
        theme_row = tk.Frame(self.lan_frame)
        theme_row.pack(fill='x')
        tk.Label(theme_row, text="主题名称:", font=("Arial", 10, "bold"), width=10, anchor='w').pack(side='left')
        self.theme_var = tk.StringVar(value='')
        self.theme_entry = tk.Entry(theme_row, textvariable=self.theme_var, font=("Arial", 10))
        self.theme_entry.pack(side='left', fill='x', expand=True)
        self.theme_hint = tk.Label(theme_row, text="", font=("Arial", 8), fg="#888")
        self.theme_hint.pack(side='left', padx=(5, 0))
        available_themes = list_themes()
        self.theme_hint.config(
            text=("如: " + " / ".join(available_themes)) if available_themes else "如: 主题文件名"
        )

        # --- CF 模式控件 ---
        self.cf_frame = tk.Frame(main_frame)
        # 默认隐藏，选择 CF 模式时显示

        tk.Label(self.cf_frame, text="CF Worker 地址:", font=("Arial", 10, "bold")).pack(anchor='w')
        self.cf_url_var = tk.StringVar(value=saved_cf_url)
        self.cf_url_entry = tk.Entry(self.cf_frame, textvariable=self.cf_url_var, font=("Arial", 10))
        self.cf_url_entry.pack(fill='x', pady=(0, 10))

        tk.Label(self.cf_frame, text="共享密钥:", font=("Arial", 10, "bold")).pack(anchor='w')
        self.cf_key_var = tk.StringVar(value=saved_cf_key)
        self.cf_key_entry = tk.Entry(self.cf_frame, textvariable=self.cf_key_var, font=("Arial", 10), show="*")
        self.cf_key_entry.pack(fill='x')

        # 恢复保存的模式
        if saved_mode == 'cf':
            self.ip_var.set('Cloudflare Chat Workers')
            self.lan_frame.pack_forget()
            self.cf_frame.pack(fill='x', pady=(0, 10))
        elif saved_ip and saved_ip in self.all_ips:
            self.ip_var.set(saved_ip)

        # 按钮组
        self.button_frame = tk.Frame(main_frame)
        self.button_frame.pack(fill='x', pady=(0, 20))

        # 启动按钮
        self.btn_start = tk.Button(self.button_frame, text="启动服务", command=self.toggle_server,
                                   bg="#007AFF", fg="white", font=("Arial", 12, "bold"),
                                   relief="flat", pady=8, cursor="hand2")
        self.btn_start.pack(side='left', fill='x', expand=True, padx=(0, 5))

        # 最小化到托盘按钮
        self.btn_minimize = tk.Button(self.button_frame, text="🔽", command=self.hide_window,
                                      bg="#8e8e93", fg="white", font=("Arial", 12, "bold"),
                                      relief="flat", pady=8, cursor="hand2", width=3)
        self.btn_minimize.pack(side='right')

        # 二维码显示区域
        self.qr_label = tk.Label(main_frame, text="",
                                 bg="#e6e6e6", fg="#333", font=("Arial", 9),
                                 wraplength=460, justify='left', anchor='w')
        self.qr_label.pack(pady=5, fill='x')

        # 初始显示所有可用地址
        self.show_all_ips_display(5000)

        # 底部链接提示
        self.url_label = tk.Label(main_frame, text="", fg="blue", font=("Arial", 9, "underline"),
                                  cursor="hand2", wraplength=460, justify='left')
        self.url_label.pack(pady=(5, 0), fill='x')
        self.url_label.bind("<Button-1>", self.open_browser) # 点击用浏览器打开

        # 提示信息
        self.tip_label = tk.Label(main_frame, text="", fg="#888", font=("Arial", 8))
        self.tip_label.pack(pady=(5, 0))

        # 按当前授权状态决定是否显示权限横幅
        self.refresh_permission_banner()

    def refresh_permission_banner(self):
        """根据「辅助功能」授权状态显示或隐藏横幅"""
        if macos_accessibility_trusted():
            self.perm_frame.pack_forget()
        else:
            # 显式指定 before，保证重新 pack 时仍排在最上方
            self.perm_frame.pack(fill='x', pady=(0, 10), before=self.mode_label)

    def show_all_ips_display(self, port, started=False):
        """显示所有可用 IP 地址列表"""
        # 过滤掉 0.0.0.0 和 Cloudflare 选项
        all_ips = [ip for ip in self.all_ips if not ip.startswith('0.0.0.0') and not ip.startswith('Cloudflare')]
        theme = self.theme_var.get().strip()
        ip_list = '\n'.join([build_url(ip, port, theme) for ip in all_ips])

        if started:
            # 已启动状态
            title = "监听所有网卡"
            tip = "💡 切换到具体 IP 可显示二维码"
        else:
            # 未启动状态
            title = "可用地址"
            tip = "💡 点击启动服务开始使用"

        self.qr_label.config(
            text=f"{title}\n\n{ip_list}\n\n{tip}",
            image='',
            width=0,
            height=0,
            wraplength=460,
            justify='left',
            anchor='w',
            bg="#e6e6e6",
            fg="#333",
            font=("Arial", 9)
        )

    def run_flask(self, host, port):
        try:
            app.run(host=host, port=port, debug=False, use_reloader=False)
        except Exception as e:
            message = f"服务启动失败：{e}"
            # 绑成默认参数，避免 except 结束后 e 被删除导致回调取不到值
            self.root.after(0, lambda m=message: self._on_server_error(m))

    def _on_server_error(self, message):
        """服务启动失败时回滚界面状态"""
        self.is_running = False
        self.listen_on_all = False
        self.btn_start.config(text="启动服务", bg="#007AFF")
        self.port_entry.config(state='normal')
        self.ip_combo.config(state='readonly')
        if hasattr(self, 'current_url'):
            del self.current_url
        self.url_label.config(text="")
        self.tip_label.config(text="", fg="#888")
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = 5000
        self.show_all_ips_display(port, started=False)
        messagebox.showerror("启动失败", message)

    @staticmethod
    def _port_is_free(host, port) -> bool:
        """预先探测端口能否绑定，避免界面显示成已启动却没人监听"""
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def generate_qr(self, url, target_size=200):
        """生成二维码图像，自动调整大小以适应目标尺寸"""
        # 生成二维码图像
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')

        # 调整图像大小以适应显示区域
        img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)

        # 转换为 Tkinter 可用的格式
        img_tk = ImageTk.PhotoImage(img)
        return img_tk

    def toggle_server(self):
        if self.is_running:
            # 停止服务并退出
            self.quit_app()
            return

        selected = self.ip_var.get()

        # 判断模式并启动
        if selected == 'Cloudflare Chat Workers':
            # 保存 CF 配置
            self.config['mode'] = 'cf'
            self.config['cf_url'] = self.cf_url_var.get()
            self.config['cf_key'] = self.cf_key_var.get()
            save_config(self.config)
            self.start_cf_mode()
        else:
            # 保存局域网配置
            self.config['mode'] = 'lan'
            self.config['port'] = self.port_var.get()
            self.config['ip'] = selected
            save_config(self.config)
            self.start_lan_mode()

    def parse_cf_config(self, config: str) -> tuple:
        """解析 CF 配置：key@url（保留兼容）"""
        if '@' not in config:
            return '', config
        at_pos = config.find('@')
        key = config[:at_pos]
        url = config[at_pos + 1:]
        return key, url

    def start_cf_mode(self):
        """启动 CF 模式"""
        if not CF_AVAILABLE:
            messagebox.showerror("错误", "CF 模式需要安装依赖:\npip install websockets cryptography")
            return

        url = self.cf_url_var.get().strip()
        key = self.cf_key_var.get()

        if not url:
            messagebox.showerror("错误", "请输入 CF Worker 地址")
            return

        # 确保 URL 有协议
        if not url.startswith('http'):
            url = 'https://' + url

        self.cf_mode = True
        self.cf_url = url
        self.cf_key = key

        # 创建 CF 客户端
        self.cf_client = CFChatClient(
            worker_url=url,
            password=key,
            on_message=self.on_cf_message,
            on_status=self.on_cf_status
        )
        self.cf_client.start()

        self.is_running = True
        self.btn_start.config(text="停止服务并退出", bg="#ff3b30")
        self.cf_url_entry.config(state='disabled', bg="#f0f0f0")
        self.cf_key_entry.config(state='disabled', bg="#f0f0f0")
        self.ip_combo.config(state='disabled')

        # 显示 cfchat URL 的二维码
        self._show_qr(url)

        self.url_label.config(text=url)
        self.current_url = url
        self.tip_label.config(text="CF 模式：手机访问上方链接发送消息")

    def start_lan_mode(self):
        """启动局域网模式"""
        port_str = self.port_var.get().strip()

        if not port_str.isdigit():
            messagebox.showerror("错误", "端口必须是数字")
            return

        self.cf_mode = False
        port = int(port_str)
        host_ip = self.ip_var.get()

        # 确定监听地址
        if host_ip.startswith('0.0.0.0'):
            listen_host = '0.0.0.0'
        else:
            listen_host = host_ip

        # 先探测端口，避免界面变成"已启动"但实际没人监听
        if not self._port_is_free(listen_host, port):
            messagebox.showerror("错误", f"端口 {port} 已被占用，请更换端口后重试。")
            return

        # 启动 Flask 线程
        t = threading.Thread(target=self.run_flask, args=(listen_host, port), daemon=True)
        t.start()

        self.is_running = True
        self.listen_on_all = host_ip.startswith('0.0.0.0')
        self.btn_start.config(text="停止服务并退出", state='normal', bg="#ff3b30")
        self.port_entry.config(state='disabled', bg="#f0f0f0")

        if not self.listen_on_all:
            self.ip_combo.config(state='disabled')

        theme = self.theme_var.get().strip()

        if host_ip.startswith('0.0.0.0'):
            self.show_all_ips_display(port, started=True)
            all_ips = [ip for ip in self.all_ips if not ip.startswith('0.0.0.0') and not ip.startswith('Cloudflare')]
            self.url_label.config(text="请手动输入上方地址")
            self.current_url = build_url(all_ips[0], port, theme) if all_ips else ""
            self.tip_label.config(text="")
        else:
            url = build_url(host_ip, port, theme)
            self._show_qr(url)

            self.url_label.config(text=url)
            self.current_url = url
            self.tip_label.config(text="提示：如无法访问，请切换 IP 或端口重新扫码")

    def _show_qr(self, url):
        """在二维码区域渲染 URL 二维码"""
        qr_size = max(150, min(self.root.winfo_width() - 80, 250))
        try:
            self.qr_img = self.generate_qr(url, target_size=qr_size)
            self.qr_label.config(image=self.qr_img, width=qr_size, height=qr_size,
                                 bg="white", text='', font=("Arial", 10),
                                 anchor='center', wraplength=0, justify='left')
        except Exception as e:
            self.qr_label.config(image='', text=f"二维码生成失败\n{e}", width=0, height=0)

    def on_cf_message(self, text: str):
        """CF 模式收到消息回调"""
        self.root.after(0, lambda: self._handle_cf_message(text))

    def _handle_cf_message(self, text: str):
        """处理 CF 消息并粘贴"""
        paste_text(text)
        # 更新提示
        display = text[:30] + '...' if len(text) > 30 else text
        self.tip_label.config(text=f"已粘贴: {display}")

    def on_cf_status(self, state: str, text: str):
        """CF 模式状态回调"""
        self.root.after(0, lambda: self._update_cf_status(state, text))

    def _update_cf_status(self, state: str, text: str):
        """更新 CF 状态显示"""
        colors = {
            'connected': '#34c759',
            'connecting': '#f59e0b',
            'disconnected': '#888',
            'error': '#ff3b30'
        }
        self.tip_label.config(text=text, fg=colors.get(state, '#888'))

    def on_mode_changed(self, event=None):
        """模式/IP 改变时切换界面"""
        selected = self.ip_var.get()

        if selected == 'Cloudflare Chat Workers':
            # 切换到 CF 模式界面
            self.lan_frame.pack_forget()
            self.cf_frame.pack(fill='x', pady=(0, 10), before=self.button_frame)
        else:
            # 切换到局域网模式界面
            self.cf_frame.pack_forget()
            self.lan_frame.pack(fill='x', pady=(0, 10), before=self.button_frame)

            # 如果运行中且是 0.0.0.0 模式，更新二维码
            if self.is_running and hasattr(self, 'listen_on_all') and self.listen_on_all:
                self._update_lan_qr()

    def _update_lan_qr(self):
        """更新局域网模式二维码"""
        host_ip = self.ip_var.get()
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = 5000
        theme = self.theme_var.get().strip()

        if host_ip.startswith('0.0.0.0'):
            self.show_all_ips_display(port, started=True)
            all_ips = [ip for ip in self.all_ips if not ip.startswith('0.0.0.0') and not ip.startswith('Cloudflare')]
            self.url_label.config(text="请手动输入上方地址")
            self.current_url = build_url(all_ips[0], port, theme) if all_ips else ""
            self.tip_label.config(text="")
        else:
            url = build_url(host_ip, port, theme)
            self._show_qr(url)
            self.url_label.config(text=url)
            self.current_url = url
            self.tip_label.config(text="提示：如无法访问，请切换 IP 重新扫码")

    def create_tray_icon(self):
        """创建系统托盘图标"""
        # macOS 上 pystray 在后台线程运行会触发 AppKit 断言崩溃，禁用托盘，
        # 改用程序坞最小化（见 hide_window）
        if IS_MAC:
            self.tray_icon = None
            return
        # 尝试加载 icon.ico，保持与窗口图标一致
        try:
            icon_path = get_icon_path()
            if icon_path:
                icon_image = Image.open(icon_path)
            elif os.path.exists('icon.png'):
                icon_image = Image.open('icon.png')
            else:
                # 创建一个简单的蓝色图标
                icon_image = Image.new('RGB', (64, 64), color='#007AFF')
        except Exception:
            # 如果加载失败，创建简单图标
            icon_image = Image.new('RGB', (64, 64), color='#007AFF')

        # 创建托盘菜单
        menu = pystray.Menu(
            item('显示窗口', self.show_window),
            item('退出', self.quit_app)
        )

        # 创建托盘图标
        self.tray_icon = pystray.Icon("QAA-AirType", icon_image, "QAA AirType", menu)

        # 在后台线程运行托盘图标
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        """隐藏窗口"""
        if IS_MAC:
            # macOS 无系统托盘，改为最小化到程序坞（可从程序坞点回）
            self.root.iconify()
        else:
            self.root.withdraw()

    def show_window(self, icon=None, item=None):
        """显示窗口"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_app(self, icon=None, item=None):
        """退出应用"""
        # 停止 CF 客户端
        if self.cf_client:
            self.cf_client.stop()
            self.cf_client = None
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()

    def open_browser(self, event):
        if hasattr(self, 'current_url'):
            import webbrowser
            webbrowser.open(self.current_url)

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
    app_gui = ServerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()