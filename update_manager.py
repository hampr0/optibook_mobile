import urllib.request
import json
import webbrowser

# 현재 설치된 앱 버전 (반드시 대문자로 정의)
CURRENT_APP_VERSION = "v1.0.0"

# GitHub 저장소 정보
GITHUB_REPO_OWNER = "hampr0"
GITHUB_REPO_NAME = "optibook_mobile"

def check_for_updates():
    """
    GitHub 최신 Release 버전을 조회하여 새 버전 여부와 다운로드 URL을 반환
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
    try:
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Optibook-Mobile-App"}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                latest_tag = data.get("tag_name", "")
                
                # 현재 버전과 다르면 새 버전 존재
                if latest_tag and latest_tag != CURRENT_APP_VERSION:
                    download_url = data.get("html_url", "")
                    assets = data.get("assets", [])
                    for asset in assets:
                        if asset.get("name", "").endswith(".apk"):
                            download_url = asset.get("browser_download_url", download_url)
                            break
                    
                    return True, latest_tag, download_url
    except Exception:
        pass
    return False, CURRENT_APP_VERSION, ""

def open_download_link(url: str):
    try:
        webbrowser.open(url)
    except Exception:
        pass

