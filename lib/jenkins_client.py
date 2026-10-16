"""讀取 Jenkins job 資訊與建置紀錄（四台，依 IP 末碼定位）。

認證：同帳號 JENKINS_USER + 各台獨立 JENKINS_TOKEN_{ip}（Basic Auth）。
讀取一律走 GET，不需 CSRF crumb。
job_path 支援巢狀 Folder（如 team/sub/my-job），內部自動展開成 /job/.../job/...。
"""
import sys
from datetime import datetime, timedelta, timezone

import requests

import config

TPE = timezone(timedelta(hours=8))


def _job_url(ip, job_path):
    base, _ = config.jenkins_host(ip)
    segments = "/".join(f"job/{p}" for p in job_path.strip("/").split("/"))
    return f"{base}/{segments}"


def _get(ip, url, **kwargs):
    resp = requests.get(url, auth=config.jenkins_auth(ip),
                        timeout=30, **kwargs)
    resp.raise_for_status()
    return resp


def _crumb(ip):
    """取 CSRF crumb（POST 寫入需要）；未啟用 crumb 的 Jenkins 回空 dict。"""
    base, _ = config.jenkins_host(ip)
    try:
        data = _get(ip, f"{base}/crumbIssuer/api/json").json()
        return {data["crumbRequestField"]: data["crumb"]}
    except requests.HTTPError:
        return {}


def trigger_build(ip, job_path, parameters):
    """觸發一個帶參數的 build（POST buildWithParameters）。

    對外寫入動作。parameters 為 {名稱: 值} dict，會原樣送出。
    回傳 {"queue_url": ...}——Jenkins 觸發後先進 queue，稍後才配到 build 號，
    需再用 get_job 看最新 build 或輪詢 queue 取號。
    """
    url = f"{_job_url(ip, job_path)}/buildWithParameters"
    resp = requests.post(
        url, auth=config.jenkins_auth(ip),
        headers=_crumb(ip), data=parameters, timeout=30,
    )
    resp.raise_for_status()
    return {"queue_url": resp.headers.get("Location")}


def list_jobs(ip, folder=None, keyword=None):
    """列這台（或指定 folder 下）所有 job 名稱與狀態。

    folder 給巢狀路徑（如 team/sub）則列該 folder 下的 job；
    keyword 給關鍵字則只回名稱含該字（不分大小寫）的 job。
    """
    base, label = config.jenkins_host(ip)
    root = _job_url(ip, folder) if folder else base
    url = f"{root}/api/json"
    data = _get(ip, url, params={"tree": "jobs[name,color]"}).json()
    jobs = [{"name": j["name"], "color": j.get("color")}
            for j in data.get("jobs", [])]
    if keyword:
        kw = keyword.lower()
        jobs = [j for j in jobs if kw in j["name"].lower()]
    return {"ip": ip, "label": label, "folder": folder,
            "count": len(jobs), "jobs": jobs}


def get_job(ip, job_path):
    """job 概況：名稱、最近建置、近期 build 清單。"""
    url = f"{_job_url(ip, job_path)}/api/json"
    tree = ("displayName,url,buildable,color,"
            "lastBuild[number],lastSuccessfulBuild[number],"
            "lastFailedBuild[number],"
            "builds[number,timestamp,result,duration]")
    data = _get(ip, url, params={"tree": tree}).json()
    return {
        "ip": ip,
        "label": config.jenkins_host(ip)[1],
        "name": data.get("displayName"),
        "buildable": data.get("buildable"),
        "color": data.get("color"),
        "last_build": (data.get("lastBuild") or {}).get("number"),
        "builds": [_build_brief(b) for b in data.get("builds", [])],
    }


def _build_brief(b):
    ts = datetime.fromtimestamp(b["timestamp"] / 1000, TPE)
    return {
        "number": b["number"],
        "result": b.get("result"),
        "started": ts.isoformat(),
        "duration_sec": round(b.get("duration", 0) / 1000),
    }


def get_builds_by_date(ip, job_path, date):
    """指定日期（台北時間 YYYY-MM-DD）的建置清單。"""
    job = get_job(ip, job_path)
    return [b for b in job["builds"] if b["started"][:10] == date]


def get_build_detail(ip, job_path, number):
    """單一 build：結果/狀態、觸發者、參數、測試報告。"""
    url = f"{_job_url(ip, job_path)}/{number}/api/json"
    tree = ("number,result,timestamp,duration,"
            "actions[causes[userName,shortDescription],"
            "parameters[name,value]]")
    data = _get(ip, url, params={"tree": tree}).json()

    causes, params = [], {}
    for action in data.get("actions", []):
        for c in action.get("causes", []):
            causes.append(c.get("userName") or c.get("shortDescription"))
        for p in action.get("parameters", []):
            params[p["name"]] = p.get("value")

    started = datetime.fromtimestamp(data["timestamp"] / 1000, TPE)
    detail = {
        "number": data["number"],
        "result": data.get("result"),
        "started": started.isoformat(),
        "duration_sec": round(data.get("duration", 0) / 1000),
        "triggered_by": [c for c in causes if c],
        "parameters": params,
        # 兩個都帶：allure 結構化統計（可能 None）+ console 末段（一定有）
        "allure": get_allure_summary(ip, job_path, number),
        "console_tail": get_console(ip, job_path, number, tail=3000),
    }
    return detail


def get_allure_summary(ip, job_path, number):
    """Allure 測試統計；job 無 Allure 報告則回 None。"""
    url = f"{_job_url(ip, job_path)}/{number}/allure/widgets/summary.json"
    try:
        stat = _get(ip, url).json().get("statistic", {})
    except requests.HTTPError:
        return None
    return {
        "pass": stat.get("passed"),
        "fail": stat.get("failed"),
        "skip": stat.get("skipped"),
        "broken": stat.get("broken"),
        "total": stat.get("total"),
    }


def get_console(ip, job_path, number, tail=None):
    """console log 純文字；tail 給字元數則只回末段。"""
    url = f"{_job_url(ip, job_path)}/{number}/consoleText"
    text = _get(ip, url).text
    return text[-tail:] if tail else text


if __name__ == "__main__":
    ip, job_path = sys.argv[1], sys.argv[2]
    job = get_job(ip, job_path)
    print(f"[{ip} {job['label']}] {job['name']} (color={job['color']})")
    print(f"最近 build: #{job['last_build']}，近期 {len(job['builds'])} 筆")
    for b in job["builds"][:5]:
        print(f"  #{b['number']} {b['result']} "
              f"{b['started'][:16]} {b['duration_sec']}s")
