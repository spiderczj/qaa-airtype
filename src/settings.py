"""运行配置：版本号与各处共用的常量。

__version__ 是全局唯一的版本来源 —— QAA-AirType.spec 用正则读取本文件，
GUI 标题栏与启动诊断日志也显示它。发版时只改这一行。
"""
import os

# 发版时只需改这一行。
__version__ = '1.1.0'

# 旧默认 5000 会被 macOS「AirPlay 接收器」占用，故改用冷门端口。
DEFAULT_PORT = 8765

# QAA_DRY_RUN=1 时不真正复制粘贴，供自动化测试覆盖 /type 成功路径。
DRY_RUN = os.environ.get('QAA_DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')

# /type 保护：单次文本长度上限与滑动时间窗内的请求次数上限。
MAX_TYPE_CHARS = 50_000
TYPE_RATE_LIMIT = 5
TYPE_RATE_WINDOW = 1.0

# 网卡变化轮询间隔（毫秒），用于刷新地址列表与二维码。
NETWORK_POLL_MS = 3000
