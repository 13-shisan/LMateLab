# backend/vasp_db.py
import sqlite3
from pathlib import Path

# 指向你现有的 log_vasp.db
# BASE_DIR = Path(__file__).resolve().parent.parent   # /home/software/LMateLab
LOG_DB_PATH = "/app/var/db/log_vasp.db"

def get_log_conn():
    """
    只读连接 log_vasp.db，row_factory 设置为 dict 风格访问。
    使用方法:
        with get_log_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT ...")
    """
    conn = sqlite3.connect(str(LOG_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn
