"""
MySQL 连接配置
默认连接本地 MySQL，可通过环境变量覆盖
"""
import os

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", 3306)),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "123456"),
    "db": os.getenv("MYSQL_DB", "novel_creator"),
    "charset": "utf8mb4",
    "autocommit": True,
    "minsize": 1,
    "maxsize": 10,
}
