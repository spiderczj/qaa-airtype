# QAA AirType

把手机变成电脑的无线键盘：电脑上启动服务 → 手机扫码 → 在手机上打字，文字直接粘贴到电脑当前的输入框里。

支持 macOS（已打包为 `.app` / `DMG`），源码层面也留有 Windows 分支。

---

## 它能做什么

- **扫码即连**：启动服务后生成二维码，手机浏览器打开即可用，无需装 App
- **文字直出**：手机上敲的内容通过 `Cmd+V` 粘贴到电脑当前焦点窗口
- **三套主题**：`auto`（智能输入）/ `detect` / `light`
- **访问令牌鉴权**：二维码 URL 里带一次性令牌，没有令牌一律 `403`，别人扫到旧链接也进不来
- **系统托盘 / 剪贴板回退**：粘贴失败时自动改走剪贴板
- **两种连接方式**：同一局域网直连；跨网络时可切 Cloudflare 中转模式

---

## 快速开始

### 方式一：直接用打包版（推荐，不用装 Python）

双击 `dist/QAA AirType.app`，或者挂载 `dist/QAA-AirType.dmg` 后把应用拖进 `Applications`。

> `dist/` 是构建产物，从源码跑需要先执行 `./build.sh` 生成。

### 方式二：从源码运行

```bash
# 1. 装 Tk —— Homebrew 的 Python 默认不带，缺了会报 No module named 'tkinter'
brew install python-tk@3.14

# 2. 建虚拟环境并装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. 启动
./run.sh
```

Ubuntu 上把第 1 步换成 `sudo apt install python3-tk`。

---

## 首次使用：授权「辅助功能」

这是**必须**的一步 —— 不授权的话，手机发来的文字不会被粘贴到电脑上。

1. 启动应用，顶部会出现红色提示条
2. 点 **打开系统设置**
3. 系统设置 → 隐私与安全性 → 辅助功能 → 点 **+** 加入 **QAA AirType**
4. 回到应用点 **重新检测**

> **为什么每次重装后要再授权一次？** 本项目用 ad-hoc 签名（没有 Apple 开发者证书），
> 每次重新打包产物的 CDHash 都会变，系统会把它当成一个新应用。

---

## 日常使用

1. 应用里选好 **连接模式**（通常就是你的局域网 IP）、**端口**（默认 `5000`）、**主题**
2. 点 **启动服务**
3. 用手机扫码，或把「可用地址」里的链接发到手机上打开
4. 在手机页面里打字 → 电脑上即刻粘贴

停止服务：点应用里的停止按钮，或直接退出应用。

---

## 主题

把 HTML 文件放进 `theme/` 目录，重启服务即可在「主题名称」里选用：

```
theme/auto.html    智能输入（推荐）
theme/detect.html  自动检测
theme/light.html   浅色
```

留空则回退到 `src/default.html`。

---

## 打包成 .app / DMG

```bash
./build.sh
```

一条命令完成：生成图标 → PyInstaller 构建 → ad-hoc 签名校验 → 打 DMG → 清理中间产物。

产物：

| 文件 | 说明 |
|---|---|
| `dist/QAA AirType.app` | 约 60M，可直接双击运行 |
| `dist/QAA-AirType.dmg` | 约 28M，含 `/Applications` 软链，拖拽安装 |

---

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

19 条用例，覆盖访问令牌鉴权、Cookie 鉴权、主题加载、路径穿越防护、资源落位、IP 枚举、版本号一致性。

测试目标会自动选择：**存在 `dist/QAA AirType.app` 就验证打包产物**（走 `sys._MEIPASS` 资源路径），否则验证源码目录。

> `/type` 的「成功路径」故意不测 —— 它会真实触发一次 `Cmd+V`，粘贴到你当时焦点所在的窗口上。

---

## 项目结构

```
src/remote_server.py    主程序（GUI + Flask 服务 + 平台适配）
src/bootstrap.py        打包后的日志重定向与崩溃兜底
src/generate_icon.py    生成 icon.png / icon.ico / icon.icns
src/default.html        默认手机页面
theme/                  手机页面主题
assets/                 图标资源
tests/                  接口与资源测试
QAA-AirType.spec        PyInstaller 打包配置
build.sh                一键打包
run.sh                  开发环境启动脚本
```

另外桌面上有个 `QAA AirType.command`（双击即从终端跑 `run.sh`），它指向本项目目录、不在仓库里。

---

## 版本号

**只定义一处**：`src/remote_server.py` 顶部的 `__version__`。

```python
__version__ = '1.0.0'
```

`QAA-AirType.spec` 用正则从这里读取（避免执行业务代码），GUI 标题栏和启动诊断日志都会显示它。发版时只改这一行。

---

## 常见问题

**连不上 / 扫码打不开**
检查电脑和手机是否在同一个 Wi-Fi；看应用里的「可用地址」是否列出了正确的局域网 IP。

**端口被占用**
默认 `5000`。macOS 开了「AirPlay 接收器」会占用这个端口，换成别的端口即可，应用会在启动前预检并提示。

**打出来的字没粘贴到**
九成是没授权「辅助功能」，按上面的步骤重新授权。

**日志在哪**

| 运行方式 | 日志位置 |
|---|---|
| 打包后的 `.app` | `~/.config/qaa-airtype/qaa.log` |
| `./run.sh` 开发运行 | 项目根目录 `qaa.log` |

打包版还会在日志里打印一段 `--- diagnostics begin ---`，包含版本号、资源搜索路径、检测到的 IP、辅助功能状态，排查问题先看它。

**访问令牌**
运行时随机生成，保存在 `~/.config/qaa-airtype/config.json`。二维码 URL 里的 `?t=` 就是它，不进版本库。
