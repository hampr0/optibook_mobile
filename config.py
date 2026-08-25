import os

CURRENT_APP_VERSION = "1.0.0"

# TiDB Serverless 접속 정보
DB_HOST = "gateway01.ap-northeast-1.prod.aws.tidbcloud.com"
DB_PORT = 4000
DB_USER = "BdRX6BGKz6XdjZR.root"
DB_PASS = "tdDWd9VfrKNYXaa9"
DB_NAME = "bookst_db"

# 모바일 로컬 SQLite 및 캐시 파일 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "local_cache.db")