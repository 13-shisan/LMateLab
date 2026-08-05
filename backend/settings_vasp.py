# settings.py
import os, sqlite3
from pathlib import Path

# 1. SQLite 路径（容器内） ── 可用环境变量覆盖
DB_PATH = os.getenv('VASP_LOG_DB', '/app/db/log_vasp.db')

# 2. agent 递归监控的根目录
#   (1) 如果设置了环境变量 VASP_WATCH_DIR，就按冒号 : 切成列表
#   (2) 否则使用 DEFAULT_WATCH_DIR 里显式列出的目录
DEFAULT_WATCH_DIR = ['/home', '/storage']          # ← 这里写死想监听的根目录
_env_watch = os.getenv('VASP_WATCH_DIR')
WATCH_DIR  = _env_watch.split(':') if _env_watch else DEFAULT_WATCH_DIR

# 3. 打包 CONTCAR 的编号位数
SERIAL_WIDTH = int(os.getenv('CONTCAR_SERIAL_WIDTH', 6))

# 4. 统一获取 SQLite 连接，自动开启 WAL
def get_db_connection(path: str = DB_PATH):
    conn = sqlite3.connect(path,
                           timeout=30,
                           isolation_level=None,
                           check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn

# ─────────────────────────────────────────────────────────────
# 调试信息（可选）
if __name__ == '__main__':
    print('DB_PATH   =', DB_PATH)
    print('WATCH_DIR =', WATCH_DIR)# settings.py
import os, sqlite3
from pathlib import Path

# 1. SQLite 路径（容器内） ── 可用环境变量覆盖
DB_PATH = os.getenv('VASP_LOG_DB', '/app/db/log_vasp.db')

# 2. agent 递归监控的根目录
#   (1) 如果设置了环境变量 VASP_WATCH_DIR，就按冒号 : 切成列表
#   (2) 否则使用 DEFAULT_WATCH_DIR 里显式列出的目录
DEFAULT_WATCH_DIR = ['/home', '/storage']          # ← 这里写死想监听的根目录
_env_watch = os.getenv('VASP_WATCH_DIR')
WATCH_DIR  = _env_watch.split(':') if _env_watch else DEFAULT_WATCH_DIR

# 3. 打包 CONTCAR 的编号位数
SERIAL_WIDTH = int(os.getenv('CONTCAR_SERIAL_WIDTH', 6))

# 4. 统一获取 SQLite 连接，自动开启 WAL
def get_db_connection(path: str = DB_PATH):
    conn = sqlite3.connect(path,
                           timeout=30,
                           isolation_level=None,
                           check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn

# ─────────────────────────────────────────────────────────────
# 调试信息（可选）
if __name__ == '__main__':
    print('DB_PATH   =', DB_PATH)
    print('WATCH_DIR =', WATCH_DIR)
