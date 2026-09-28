"""Flask 服务：访问令牌鉴权、主题下发与 /type 粘贴接口。"""
import collections
import logging
import secrets
import threading
import time

from flask import Flask, request, Response

from appconfig import load_config, save_config
from platform_paste import paste_text
from settings import MAX_TYPE_CHARS, TYPE_RATE_LIMIT, TYPE_RATE_WINDOW
from themes import load_theme

# --- Flask 应用配置 ---
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

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

# --- /type 保护：滑动时间窗内的请求频率限制 ---
_type_stamps = collections.deque()
_type_lock = threading.Lock()


def type_rate_limited() -> bool:
    """窗口内请求超限则返回 True。

    判限总在粘贴之前执行，因此被限流的请求绝不会产生按键动作。
    """
    now = time.monotonic()
    with _type_lock:
        while _type_stamps and now - _type_stamps[0] > TYPE_RATE_WINDOW:
            _type_stamps.popleft()
        if len(_type_stamps) >= TYPE_RATE_LIMIT:
            return True
        _type_stamps.append(now)
    return False


def reset_type_rate_limit():
    """清空限流窗口（测试用）"""
    with _type_lock:
        _type_stamps.clear()


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
    if type_rate_limited():
        return {'success': False, 'error': 'too many requests'}, 429
    try:
        data = request.get_json(silent=True) or {}
        text = data.get('text', '')
        if not isinstance(text, str):
            return {'success': False, 'error': 'invalid text'}, 400
        if len(text) > MAX_TYPE_CHARS:
            return {'success': False, 'error': 'text too long'}, 413
        if text:
            paste_text(text)
            return {'success': True}
    except Exception as e:
        print(f"Error in type_text: {e}")
    return {'success': False}
