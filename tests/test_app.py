"""QAA AirType 接口与资源测试。

用法：
    .venv/bin/python -m unittest discover -s tests -v

测试目标按优先级自动选择：
  1. 存在 dist/QAA AirType.app  ->  验证打包产物（走 sys._MEIPASS 资源路径）
  2. 否则                       ->  验证源码目录

覆盖：访问令牌鉴权、Cookie 鉴权、主题加载、路径穿越防护、
      资源落位（default.html / theme / 图标）、版本号一致性。

注意：`/type` 的「成功路径」故意不测 —— 它会真实触发一次 Cmd+V
粘贴到你当前焦点的窗口上，属于会打扰使用者的副作用。
"""
import os
import re
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')
BUNDLE_CONTENTS = os.path.join(PROJECT_ROOT, 'dist', 'QAA AirType.app', 'Contents')

# 必须在导入 remote_server 之前把源码目录加进搜索路径
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import remote_server as rs  # noqa: E402


def _setup_target():
    """决定测打包产物还是源码，返回模式描述字符串。"""
    if os.path.isdir(BUNDLE_CONTENTS):
        # 伪装成 PyInstaller 冻结环境，让 get_search_dirs() 走打包路径。
        # 必须放在 import 之后，否则 bootstrap.setup_log() 会把 stdout 接管到日志文件。
        sys.executable = os.path.join(BUNDLE_CONTENTS, 'MacOS', 'QAA AirType')
        sys._MEIPASS = os.path.join(BUNDLE_CONTENTS, 'Frameworks')
        sys.frozen = True
        return '打包产物'
    return '源码目录'


MODE = _setup_target()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mode = MODE
        cls.token = rs.AUTH_TOKEN
        cls.app = rs.app

    def client(self):
        """每次新建 client，避免上一个用例的 Cookie 串到下一个用例。"""
        return self.app.test_client()

    def target(self):
        return f'[{self.mode}]'


class TestAuth(Base):
    """访问令牌鉴权：没有有效令牌一律 403。"""

    def test_get_root_without_token_is_403(self):
        self.assertEqual(self.client().get('/').status_code, 403, self.target())

    def test_get_root_with_empty_token_is_403(self):
        self.assertEqual(self.client().get('/?t=').status_code, 403, self.target())

    def test_post_type_without_token_is_403(self):
        resp = self.client().post('/type', json={'text': 'hi'})
        self.assertEqual(resp.status_code, 403, self.target())

    def test_get_root_with_token_is_200_and_sets_cookie(self):
        resp = self.client().get(f'/?t={self.token}')
        self.assertEqual(resp.status_code, 200, self.target())
        self.assertIn('qaa_tok=', resp.headers.get('Set-Cookie', ''), self.target())

    def test_cookie_auth_is_accepted(self):
        c = self.client()
        c.set_cookie('qaa_tok', self.token, domain='localhost')
        self.assertEqual(c.get('/').status_code, 200, self.target())

    def test_type_with_query_token_is_not_403(self):
        # 喂坏 JSON 是故意的：只验证鉴权放行，不触发真实粘贴
        resp = self.client().post(f'/type?t={self.token}',
                                  data='{bad json',
                                  content_type='application/json')
        self.assertNotEqual(resp.status_code, 403, self.target())

    def test_type_with_cookie_is_not_403(self):
        c = self.client()
        c.set_cookie('qaa_tok', self.token, domain='localhost')
        resp = c.post('/type', data='{bad json', content_type='application/json')
        self.assertNotEqual(resp.status_code, 403, self.target())


class TestTheme(Base):
    """主题系统：三个主题都能加载，恶意参数不能穿透。"""

    def test_default_page_is_real_page_not_fallback(self):
        body = self.client().get(f'/?t={self.token}').get_data(as_text=True)
        self.assertNotIn('主题加载失败', body, self.target())
        self.assertGreater(len(body), 3000, self.target())
        self.assertIn('无线键盘', body, self.target())

    def test_bundled_themes_load(self):
        for name in ('auto', 'detect', 'light'):
            with self.subTest(theme=name):
                resp = self.client().get(f'/?t={self.token}&theme={name}')
                body = resp.get_data(as_text=True)
                self.assertEqual(resp.status_code, 200, self.target())
                self.assertGreater(len(body), 1000, self.target())
                self.assertNotIn('主题加载失败', body, self.target())

    def test_malicious_theme_names_do_not_escape(self):
        for bad in ('../', '../../etc/passwd', 'auto.html.html',
                    '..%2f', '<script>'):
            with self.subTest(theme=bad):
                resp = self.client().get(f'/?t={self.token}&theme={bad}')
                self.assertEqual(resp.status_code, 200, self.target())
                self.assertNotIn('主题加载失败',
                                 resp.get_data(as_text=True), self.target())


class TestResources(Base):
    """资源落位：打包最容易漏的就是这一步。"""

    def test_search_dirs_exist(self):
        dirs = rs.get_search_dirs()
        self.assertTrue(dirs, self.target())
        self.assertTrue(any(os.path.isdir(d) for d in dirs), self.target())

    def test_default_html_is_reachable(self):
        found = [d for d in rs.get_search_dirs()
                 if os.path.isfile(os.path.join(d, 'default.html'))]
        self.assertTrue(found, f'{self.target()} 找不到 default.html，'
                               f'已搜索 {rs.get_search_dirs()}')

    def test_themes_are_discovered(self):
        self.assertEqual(sorted(rs.list_themes()),
                         ['auto', 'detect', 'light'], self.target())

    def test_icon_file_is_present(self):
        self.assertTrue(rs.get_icon_path(), self.target())

    def test_load_theme_returns_real_content(self):
        auto = rs.load_theme('auto')
        self.assertIn('智能输入', auto, self.target())
        self.assertGreater(len(auto), 5000, self.target())


class TestIPEnumeration(Base):
    """IP 枚举不能依赖 DNS —— mDNS 曾让整个界面卡死。"""

    def test_get_ifaddrs_is_fast_and_real(self):
        import time
        start = time.time()
        ips = rs.get_ifaddrs()
        elapsed = time.time() - start
        self.assertLess(elapsed, 1.0, f'{self.target()} get_ifaddrs 耗时 {elapsed:.3f}s')
        if ips:
            for ip in ips:
                self.assertNotIn(ip, ('127.0.0.1', '0.0.0.0'), self.target())

    def test_get_all_ips_returns_valid_entry_list(self):
        ips = rs.get_all_ips()
        self.assertTrue(ips, self.target())
        self.assertEqual(ips[0], '0.0.0.0 (所有网卡)', self.target())
        # 不该再出现占位的回环地址
        self.assertNotIn('127.0.0.1', ips, self.target())


class TestVersion(unittest.TestCase):
    """版本号只定义一处，spec 与运行时必须读到同一个值。"""

    def test_version_format(self):
        self.assertRegex(rs.__version__, r'^\d+\.\d+\.\d+$')

    def test_spec_reads_same_version(self):
        path = os.path.join(PROJECT_ROOT, 'QAA-AirType.spec')
        with open(path, encoding='utf-8') as fh:
            spec = fh.read()
        self.assertNotRegex(spec, r"^VERSION\s*=\s*['\"]",
                            'spec 不应硬编码 VERSION，应从 src/remote_server.py 读取')
        src = os.path.join(SRC_DIR, 'remote_server.py')
        with open(src, encoding='utf-8') as fh:
            found = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]",
                              fh.read(), re.M)
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), rs.__version__)


if __name__ == '__main__':
    unittest.main(verbosity=2)
