import os
import json
import base64
from config import BASE_DIR
from db_manager import get_tidb_connection

LOGIN_STATE_FILE = os.path.join(BASE_DIR, "login_state.json")
OFFLINE_AUTH_FILE = os.path.join(BASE_DIR, "offline_auth.json")

# 기본 오프라인 마스터 계정 세팅 (초기 파일 없을 시 백업용)
DEFAULT_OFFLINE_USERS = {
    "ssbs_master": {
        "user_pw": "ssbs3388!",
        "user_name": "총괄관리자",
        "role": "MASTER",
        "company_id": "ALL",
        "status": "APPROVED"
    }
}

def encode_pw(password: str) -> str:
    """Base64 비밀번호 암호화"""
    return base64.b64encode(password.encode("utf-8")).decode("utf-8")

def decode_pw(encoded_pw: str) -> str:
    """Base64 비밀번호 복호화"""
    try:
        return base64.b64decode(encoded_pw.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""

def load_saved_login():
    """자동 로그인용 저장된 계정 정보 로드"""
    if os.path.exists(LOGIN_STATE_FILE):
        try:
            with open(LOGIN_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("saved_id", ""), decode_pw(data.get("saved_pw", ""))
        except Exception:
            pass
    return "", ""

def save_login_state(user_id: str, password: str, remember: bool):
    """로그인 상태 저장 (체크 해제 시 파일 삭제)"""
    if remember:
        payload = {
            "saved_id": user_id,
            "saved_pw": encode_pw(password)
        }
        with open(LOGIN_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    else:
        if os.path.exists(LOGIN_STATE_FILE):
            os.remove(LOGIN_STATE_FILE)

def load_offline_users():
    """오프라인 캐시 사용자 목록 불러오기"""
    if os.path.exists(OFFLINE_AUTH_FILE):
        try:
            with open(OFFLINE_AUTH_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_OFFLINE_USERS

def authenticate(user_id: str, password: str):
    """
    온라인 우선 인증 -> 실패/오프라인 시 로컬 캐시 인증
    반환값: (성공 여부, 사용자 정보 딕셔너리, 온라인 여부)
    """
    conn = get_tidb_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                query = "SELECT user_id, user_pw, user_name, role, company_id, status FROM users WHERE user_id = %s LIMIT 1"
                cur.execute(query, (user_id,))
                user = cur.fetchone()
                if user and user["user_pw"] == password:
                    if user.get("status") == "APPROVED":
                        # 최신 인증 정보 로컬 캐시에 동기화
                        users_cache = load_offline_users()
                        users_cache[user_id] = user
                        with open(OFFLINE_AUTH_FILE, "w", encoding="utf-8") as f:
                            json.dump(users_cache, f, ensure_ascii=False, indent=4)
                        return True, user, True
        except Exception:
            pass
        finally:
            conn.close()

    # 오프라인 인증 분기
    offline_users = load_offline_users()
    if user_id in offline_users:
        user = offline_users[user_id]
        if user.get("user_pw") == password and user.get("status") == "APPROVED":
            return True, user, False

    return False, None, False