"""config.json 的读写：端口、网卡选择、访问令牌都存在这里。"""
import json
import os
import platform

# --- 配置文件 ---
def get_config_path():
    """获取配置文件路径"""
    if platform.system() == 'Windows':
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
