import urllib.request
import json
import re
import webbrowser
from config import CURRENT_APP_VERSION, GITHUB_REPO_OWNER, GITHUB_REPO_NAME

def parse_version(ver_str: str) -> tuple:
    """'v1.2.0' 문자열을 (1, 2, 0) 숫자 튜플로 변환하여 대소 비교"""
    nums = re.findall(r'\d+', str(ver_str))
    if not nums:
        return (0, 0, 0)
    return tuple(int(n) for n in nums[:3])

def check_for_updates():
    """
    GitHub 최신 Release 버전을 조회하여 현재 버전보다 높을 때만 업데이트 알림 반환
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "Optibook-Mobile-App",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                latest_tag = str(data.get("tag_name", "")).strip()

                if latest_tag and parse_version(latest_tag) > parse_version(CURRENT_APP_VERSION):
                    download_url = data.get("html_url", "")
                    assets = data.get("assets", [])
                    for asset in assets:
                        asset_name = str(asset.get("name", "")).lower()
                        if asset_name.endswith(".apk") or asset_name.endswith(".zip"):
                            download_url = asset.get("browser_download_url", download_url)
                            break
                    return True, latest_tag, download_url
    except Exception:
        pass
    return False, CURRENT_APP_VERSION, ""

def open_download_link(url: str, page=None):
    """안드로이드 Flet 앱 브라우저 및 일반 브라우저 통합 지원"""
    if not url:
        return
    try:
        if page is not None and hasattr(page, "launch_url"):
            page.launch_url(url)
            return
    except Exception:
        pass
    try:
        webbrowser.open(url)
    except Exception:
        pass