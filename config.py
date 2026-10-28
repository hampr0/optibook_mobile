import os

# 현재 앱 버전
CURRENT_APP_VERSION = "v1.2.0"

# 순번 구간 분할 기본 단위 (1,000권 단위)
DEFAULT_CHUNK_SIZE = 1000

# GitHub 저장소 정보 (자동 업데이트 확인용)
GITHUB_REPO_OWNER = "hampr0"
GITHUB_REPO_NAME = "optibook_mobile"

# TiDB Serverless 접속 정보
DB_HOST = "gateway01.ap-northeast-1.prod.aws.tidbcloud.com"
DB_PORT = 4000
DB_USER = "BdRX6BGKz6XdjZR.root"
DB_PASS = "tdDWd9VfrKNYXaa9"
DB_NAME = "bookst_db"

# 모바일 로컬 데이터 및 오프라인 캐시 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "local_cache.db")
OFFLINE_QUEUE_FILE = os.path.join(BASE_DIR, "offline_queue.json")