"""Tk 图形界面：连接模式、二维码展示、服务启停与网卡切换跟随。"""
import os
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import pystray
import qrcode
from PIL import Image, ImageTk
from pystray import MenuItem as item

from appconfig import load_config, save_config
from netinfo import get_all_ips
from paths import _find_icon_file, get_icon_path
from platform_paste import (IS_MAC, macos_accessibility_trusted,
                            macos_open_accessibility_settings)
from server import app, build_url
from settings import DEFAULT_PORT, NETWORK_POLL_MS, __version__
from themes import list_themes


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
        # 默认选中第一个真实网卡 IP（多网卡时避免手机走错口），
        # 需要全网通吃时可在列表里手动选 0.0.0.0；一个真实 IP 都没有才退回 0.0.0.0。
        default_ip = next(
            (ip for ip in self.all_ips
             if not ip.startswith('0.0.0.0') and ip != '127.0.0.1'),
            self.all_ips[0],
        )
        self.ip_var = tk.StringVar(value=default_ip)
        self.is_running = False
        self._httpd = None        # werkzeug 服务器句柄，供网卡变化时重启
        self._httpd_thread = None
        self._bound_host = None

        # 加载配置
        self.config = load_config()
        saved_ip = self.config.get('ip', '')
        # 旧版本默认 5000 会撞 AirPlay，顺手迁移成新默认端口
        saved_port = str(self.config.get('port', '') or DEFAULT_PORT)
        if saved_port == '5000':
            saved_port = str(DEFAULT_PORT)
            self.config['port'] = saved_port
            save_config(self.config)
        if not saved_port.isdigit():
            saved_port = str(DEFAULT_PORT)

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

        # 恢复保存的网卡选择
        if saved_ip and saved_ip in self.all_ips:
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
        self.show_all_ips_display(int(saved_port))

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

        # 轮询网卡变化：切 Wi-Fi / 插网线 / 开关 VPN 后自动刷新地址与二维码
        self.root.after(NETWORK_POLL_MS, self._poll_network)

    def _poll_network(self):
        """每 NETWORK_POLL_MS 比对一次网卡，IP 集合变了就刷新界面，必要时换绑监听地址"""
        try:
            fresh = get_all_ips()
            if fresh != self.all_ips:
                self._on_network_changed(fresh)
        except Exception as e:
            print(f"网卡轮询失败: {e!r}")
        # 未启动时也要刷新地址列表，因此无论运行与否都继续轮询
        try:
            self.root.after(NETWORK_POLL_MS, self._poll_network)
        except tk.TclError:
            pass   # 窗口已销毁

    def _on_network_changed(self, fresh: list):
        """网卡列表变化：更新下拉框与地址区，服务在跑时自动换绑新 IP"""
        previous_ip = self.ip_var.get()
        self.all_ips = fresh
        self.ip_combo.config(values=self.all_ips)

        # 原选中的 IP 没了就退到新的首选真实 IP
        if previous_ip not in self.all_ips:
            previous_ip = next(
                (ip for ip in self.all_ips
                 if not ip.startswith('0.0.0.0') and ip != '127.0.0.1'),
                self.all_ips[0],
            )
            self.ip_var.set(previous_ip)

        try:
            port = int(self.port_var.get())
        except ValueError:
            port = DEFAULT_PORT

        if not self.is_running:
            self.show_all_ips_display(port, started=False)
            return

        # 服务在跑：0.0.0.0 绑定不受影响，只需刷新地址区
        if self._bound_host == '0.0.0.0':
            self.show_all_ips_display(port, started=True)
            self.tip_label.config(text="💡 网络已变化，地址列表已更新", fg="#888")
            return

        # 绑的是具体 IP，且它已经消失 → 换绑到新 IP 并刷新二维码
        if self._bound_host not in self.all_ips:
            self._rebind_to(previous_ip, port)
        else:
            self.show_all_ips_display(port, started=True)
            self.tip_label.config(text="💡 网络已变化，地址列表已更新", fg="#888")

    def _rebind_to(self, host_ip: str, port: int):
        """把正在运行的服务换绑到新的网卡 IP，成功后重画二维码"""
        if host_ip.startswith('0.0.0.0'):
            host_ip = '0.0.0.0'
        print(f"网络切换：监听地址 {self._bound_host} → {host_ip}")
        self._stop_http()
        if not self._start_http(host_ip, port):
            self._on_server_error(f"网络切换后端口 {port} 绑定失败，请检查端口占用。")
            return
        if host_ip == '0.0.0.0':
            self.listen_on_all = True
            self.show_all_ips_display(port, started=True)
            self.url_label.config(text="请手动输入上方地址")
            self.tip_label.config(text="💡 网络已切换，地址列表已更新", fg="#888")
        else:
            self.listen_on_all = False
            theme = self.theme_var.get().strip()
            url = build_url(host_ip, port, theme)
            self._show_qr(url)
            self.url_label.config(text=url)
            self.current_url = url
            self.tip_label.config(text=f"💡 网络已切换到 {host_ip}，请重新扫码", fg="#34c759")

    def refresh_permission_banner(self):
        """根据「辅助功能」授权状态显示或隐藏横幅"""
        if macos_accessibility_trusted():
            self.perm_frame.pack_forget()
        else:
            # 显式指定 before，保证重新 pack 时仍排在最上方
            self.perm_frame.pack(fill='x', pady=(0, 10), before=self.mode_label)

    def show_all_ips_display(self, port, started=False):
        """显示所有可用 IP 地址列表"""
        all_ips = [ip for ip in self.all_ips if not ip.startswith('0.0.0.0')]
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

    def _start_http(self, host: str, port: int):
        """在后台线程启动 werkzeug 服务器，成功返回 None，失败返回错误信息。

        用 make_server 而不是 app.run，是为了拿到 shutdown() 句柄 ——
        网卡切换时可以先停再换绑到新 IP，不必重启整个应用。
        """
        if not self._port_is_free(host, port):
            return f"端口 {port} 已被占用，请更换端口后重试。"
        try:
            from werkzeug.serving import make_server
            self._httpd = make_server(host, port, app, threaded=True)
        except Exception as e:
            self._httpd = None
            self._bound_host = None
            return f"服务启动失败：{e}"
        self._bound_host = host
        self._httpd_thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name='qaa-httpd')
        self._httpd_thread.start()
        return None

    def _stop_http(self):
        """停掉正在运行的 HTTP 服务（幂等）"""
        httpd, self._httpd = self._httpd, None
        thread, self._httpd_thread = self._httpd_thread, None
        self._bound_host = None
        if httpd is None:
            return
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception as e:
            print(f"停止 HTTP 服务失败: {e!r}")
        if thread is not None:
            thread.join(timeout=3)

    def _on_server_error(self, message):
        """服务启动失败时回滚界面状态"""
        self._stop_http()
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
            port = DEFAULT_PORT
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

        # 保存局域网配置
        self.config['port'] = self.port_var.get()
        self.config['ip'] = self.ip_var.get()
        save_config(self.config)
        self.start_lan_mode()

    def start_lan_mode(self):
        """启动服务：只监听下拉框里选中的那个地址"""
        port_str = self.port_var.get().strip()

        if not port_str.isdigit():
            messagebox.showerror("错误", "端口必须是数字")
            return

        port = int(port_str)
        selected = self.ip_var.get()
        listen_host = '0.0.0.0' if selected.startswith('0.0.0.0') else selected

        error = self._start_http(listen_host, port)
        if error:
            messagebox.showerror("错误", error)
            return

        self.is_running = True
        self.listen_on_all = listen_host == '0.0.0.0'
        self.btn_start.config(text="停止服务并退出", state='normal', bg="#ff3b30")
        self.port_entry.config(state='disabled', bg="#f0f0f0")

        if not self.listen_on_all:
            self.ip_combo.config(state='disabled')

        theme = self.theme_var.get().strip()

        if self.listen_on_all:
            self.show_all_ips_display(port, started=True)
            real_ips = [ip for ip in self.all_ips
                        if not ip.startswith('0.0.0.0') and ip != '127.0.0.1']
            self.url_label.config(text="请手动输入上方地址")
            self.current_url = build_url(real_ips[0], port, theme) if real_ips else ""
            self.tip_label.config(text="")
        else:
            url = build_url(listen_host, port, theme)
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

    def on_mode_changed(self, event=None):
        """选中的 IP 改变时刷新二维码/地址区"""
        if not self.is_running or not getattr(self, 'listen_on_all', False):
            return
        # 0.0.0.0 监听下切到具体 IP：改为显示该 IP 的二维码
        self._update_lan_qr()

    def _update_lan_qr(self):
        """切换 IP 后更新显示"""
        host_ip = self.ip_var.get()
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = DEFAULT_PORT
        theme = self.theme_var.get().strip()

        if host_ip.startswith('0.0.0.0'):
            self.show_all_ips_display(port, started=True)
            real_ips = [ip for ip in self.all_ips
                        if not ip.startswith('0.0.0.0') and ip != '127.0.0.1']
            self.url_label.config(text="请手动输入上方地址")
            self.current_url = build_url(real_ips[0], port, theme) if real_ips else ""
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
        self._stop_http()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()

    def open_browser(self, event):
        if hasattr(self, 'current_url'):
            import webbrowser
            webbrowser.open(self.current_url)
