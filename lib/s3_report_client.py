"""列出 / 導覽 S3 上的 allure 自動化測試報告。

Bucket 層級（同一路徑深度不固定，中間可能夾 report/、seleniumReport/）：
  jenkins/{env}/{category}/.../{JOB}/.../{build#}/.../allure-report/index.html
    env      : prod / stg / lab                 —— 執行環境
    category : api / app / web                  —— 測試類型（app 下再分 iOS/android…）
    specific : 手動獨立執行的報告（jenkins/specific/{env}/... 或 {env}/specific/...）

本模組只做「唯讀導覽」：逐層列出子資料夾、定位某 build 的 index.html 連結。
不下載報告內容。認證走 config 的 AWS 金鑰。
"""
import ssl

import boto3
import botocore.httpsession

import config

# config 全域注入 truststore（給 requests 過公司 SSL Inspection），會把
# ssl.SSLContext 換成 truststore 版；botocore 用它建連線時 options setter
# 會無限遞迴（RecursionError）。boto3 連的是 AWS 公網、用內建 certifi 即可，
# 故把 botocore 這條路徑的 SSLContext 釘回原生，不影響 requests 的全域注入。
botocore.httpsession.SSLContext = ssl.SSLContext

_client = None


def _s3():
    global _client
    if _client is None:
        key, secret, region = config.aws_s3_auth()
        _client = boto3.client(
            "s3",
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region,
        )
    return _client


def _folders(prefix):
    """列 prefix 底下的直接子資料夾（CommonPrefixes），回傳完整 prefix 字串。"""
    bucket = config.aws_report_bucket()
    paginator = _s3().get_paginator("list_objects_v2")
    out = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            out.append(cp["Prefix"])
    return out


def _https_url(key):
    bucket = config.aws_report_bucket()
    _, _, region = config.aws_s3_auth()
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def list_folders(prefix=""):
    """列某層的子資料夾。回傳 [{"name","prefix"}]，name 是最後一段。

    prefix 空字串即 bucket 根層（jenkins/ specific 等最上層）。
    """
    result = []
    for full in _folders(prefix):
        name = full[len(prefix):].rstrip("/")
        result.append({"name": name, "prefix": full})
    return result


def find_report(prefix, max_depth=6):
    """從 prefix 往下找第一個 allure-report/ 目錄，回傳 index.html 的 https 連結。

    build 底下不一定直接是 allure-report/（可能夾 seleniumReport/），
    所以逐層 BFS 找，吃掉中間層。找不到回傳 None。
    """
    queue = [(prefix, 0)]
    while queue:
        current, depth = queue.pop(0)
        subs = _folders(current)
        for sub in subs:
            if sub.rstrip("/").endswith("allure-report"):
                return _https_url(sub + "index.html")
        if depth < max_depth:
            queue.extend((s, depth + 1) for s in subs)
    return None


def list_builds(job_prefix):
    """列某個 JOB 底下的 build（含中間的 report/ 層自動下探）。

    回傳 [{"build","report_url","prefix"}]，build 依數字新到舊排序。
    job_prefix 例：jenkins/prod/api/AC_P0/
    """
    subs = _folders(job_prefix)
    # API 型態：JOB/report/{build#}/...，先下探 report/ 這種非數字中間層
    build_dirs = []
    for sub in subs:
        last = sub.rstrip("/").rsplit("/", 1)[-1]
        if last.isdigit():
            build_dirs.append(sub)
        else:
            build_dirs.extend(
                s for s in _folders(sub)
                if s.rstrip("/").rsplit("/", 1)[-1].isdigit()
            )

    builds = []
    for b in build_dirs:
        num = b.rstrip("/").rsplit("/", 1)[-1]
        builds.append({
            "build": int(num),
            "prefix": b,
            "report_url": find_report(b),
        })
    builds.sort(key=lambda x: x["build"], reverse=True)
    return builds


def allure_url_from_console(console_text):
    """從 Jenkins console 文字反推 allure 報告 index.html 連結。

    console 內有 S3 上傳行：`bucket={bucket}/jenkins/.../{build}, file=...`，
    取其 key 前綴，再用 find_report BFS 定位 allure-report（吃中間層）。
    找不到回傳 None。
    """
    import re

    bucket = config.aws_report_bucket()
    m = re.search(rf"bucket={re.escape(bucket)}/(\S+?),", console_text)
    if not m:
        return None
    prefix = m.group(1).rstrip("/") + "/"
    return find_report(prefix)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print(json.dumps(list_folders(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(list_folders(sys.argv[1]),
                         ensure_ascii=False, indent=2))
