#!/bin/bash
# QAA AirType 启动脚本（macOS）
# 用法: ./run.sh
cd "$(dirname "$0")" || exit 1
LOG="qaa.log"

fail() {
  echo "$1" | tee -a "$LOG"
  [ -t 0 ] && read -r -p "按回车键关闭..."
  exit 1
}

[ -d .venv ] || fail "未找到 .venv，请先创建虚拟环境并安装依赖。"

# 确保使用虚拟环境里的 python
. .venv/bin/activate

echo "=== launch $(date) ===" >> "$LOG"

# 同时输出到窗口和 qaa.log：窗口闪退后 traceback 仍保留在日志里
python -u src/remote_server.py 2>&1 | tee -a "$LOG"
