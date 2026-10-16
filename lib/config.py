"""集中管理 Jira / TestRail / GitHub 三家認證設定。

token 一律由 gary-agent/.env 讀取，程式碼不出現任何硬編碼值。
"""
import os
from pathlib import Path

import truststore

# 公司 VPN 對外部 HTTPS 做 SSL Inspection（用內部 CA 104 Forward-Trust-CA
# 重簽憑證），該 CA 只裝在 macOS 系統鑰匙圈，requests 預設用的 certifi 靜態
# 清單不認得，會噴 SSLCertVerificationError。改用系統信任庫驗證（跟瀏覽器/
# curl 行為一致），要在其他模組 import requests 前注入才生效。
truststore.inject_into_ssl()

# lib/ -> gary-agent/.env
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env():
    if not ENV_PATH.exists():
        raise FileNotFoundError(
            f"找不到設定檔 {ENV_PATH}，請複製 env.example 並填入 token。"
        )
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # .env 為唯一權威來源，直接覆寫 shell / launchctl 殘留的舊值
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


_load_env()


def _require(key):
    value = os.environ.get(key, "")
    if not value:
        raise ValueError(f"{ENV_PATH} 缺少 {key}，請填入後再執行。")
    return value


def jira_base_url():
    return _require("JIRA_BASE_URL").rstrip("/")


def jira_auth():
    return _require("JIRA_EMAIL"), _require("JIRA_API_TOKEN")


def testrail_base_url():
    return _require("TESTRAIL_BASE_URL").rstrip("/")


def testrail_auth():
    return _require("TESTRAIL_EMAIL"), _require("TESTRAIL_API_KEY")


def github_token():
    return _require("GITHUB_TOKEN")


# Jenkins 主機全由 .env 控制，每台一組（{ip} 為 IP 末碼）：
#   JENKINS_URL_{ip}=base url、JENKINS_LABEL_{ip}=語意標籤、JENKINS_TOKEN_{ip}=token
_JENKINS_URL_PREFIX = "JENKINS_URL_"


def jenkins_ips():
    return [k[len(_JENKINS_URL_PREFIX):] for k in os.environ
            if k.startswith(_JENKINS_URL_PREFIX)]


def jenkins_user():
    return _require("JENKINS_USER")


def jenkins_host(ip):
    """回傳 (base_url, 語意標籤)。"""
    if ip not in jenkins_ips():
        raise ValueError(f"未知的 Jenkins IP 末碼：{ip}，可用：{jenkins_ips()}")
    url = _require(f"{_JENKINS_URL_PREFIX}{ip}").rstrip("/")
    return url, os.environ.get(f"JENKINS_LABEL_{ip}", "")


def skills_crypt_key():
    return _require("SKILLS_CRYPT_KEY")


def jenkins_auth(ip):
    """同帳號、各台 token 不同。回傳 (user, token)。"""
    return jenkins_user(), _require(f"JENKINS_TOKEN_{ip}")


def aws_s3_auth():
    """回傳 (access_key_id, secret_access_key, region)。"""
    return (_require("AWS_ACCESS_KEY_ID"),
            _require("AWS_SECRET_ACCESS_KEY"),
            _require("AWS_S3_REGION"))


def aws_report_bucket():
    return _require("AWS_REPORT_BUCKET")


def local_repo_root():
    default = str(Path.home() / "Documents" / "104qa")
    return os.environ.get("LOCAL_REPO_ROOT", default)


# 排查「是否缺 key」時用這個，不要直接讀 .env 原文——避免 token 值進入對話 context。
_ALL_KEYS = [
    "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN",
    "TESTRAIL_BASE_URL", "TESTRAIL_EMAIL", "TESTRAIL_API_KEY",
    "GITHUB_TOKEN",
    "JENKINS_USER",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_S3_REGION", "AWS_REPORT_BUCKET",
    "AI_PERF_TOKEN",
    "SKILLS_CRYPT_KEY",
]


def check():
    """只回報每個 key 存在/缺少/空值，絕不印出值本身。"""
    result = {}
    jenkins_keys = [f"JENKINS_{kind}_{ip}" for ip in jenkins_ips()
                    for kind in ("URL", "TOKEN")]
    if not jenkins_keys:
        jenkins_keys = ["JENKINS_URL_{末碼}"]
    for key in _ALL_KEYS + jenkins_keys:
        value = os.environ.get(key, "")
        result[key] = "OK" if value else "MISSING"
    return result


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        report = check()
        missing = [k for k, v in report.items() if v == "MISSING"]
        for k, v in report.items():
            print(f"{v:8s} {k}")
        if missing:
            print(f"\n缺少 {len(missing)} 個 key：{', '.join(missing)}")
            sys.exit(1)
        print("\n全部 key 都已設定")
