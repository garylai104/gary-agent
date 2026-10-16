"""抓取 TestRail 測試案例 / 測試回合（TestRail Cloud API v2）。

注意：TestRail API 路徑是 index.php?/api/v2/...，問號格式需保留。
對照表（狀態/優先/類型/自訂 tag 選項）一律 live 抓 + 快取，因這些是各
TestRail 專案特有的（同一個 tag ID 在不同專案代表不同意義），不寫死。
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

import config

_ATTACH = "attachments/get/"


def _get(endpoint):
    email, key = config.testrail_auth()
    url = f"{config.testrail_base_url()}/index.php?/api/v2/{endpoint}"
    resp = requests.get(
        url, auth=(email, key),
        headers={"Content-Type": "application/json"}, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# --- 對照表：live 抓一次後快取（id -> 名稱）---
_cache = {}


def _statuses():
    if "status" not in _cache:
        _cache["status"] = {s["id"]: s["label"] for s in _get("get_statuses")}
    return _cache["status"]


def _priorities():
    if "priority" not in _cache:
        _cache["priority"] = {
            p["id"]: p["name"] for p in _get("get_priorities")}
    return _cache["priority"]


def _case_types():
    if "ctype" not in _cache:
        _cache["ctype"] = {
            t["id"]: t["name"] for t in _get("get_case_types")}
    return _cache["ctype"]


def _field_options():
    """自訂欄位（tctag/situationtag…）的選項 id -> 文字。"""
    if "fields" in _cache:
        return _cache["fields"]
    out = {}
    for f in _get("get_case_fields"):
        cfgs = f.get("configs") or []
        if not cfgs:
            continue
        items = cfgs[0].get("options", {}).get("items", "")
        opts = {}
        for line in str(items).splitlines():
            if "," in line:
                k, v = line.split(",", 1)
                if k.strip().isdigit():
                    opts[int(k.strip())] = v.strip()
        out[f["system_name"]] = opts
    _cache["fields"] = out
    return out


def _user_name(uid):
    """user id -> 顯示名稱。get_users 權限被擋（403），只能逐一 get_user/{id}。
    抓過就快取；抓不到退回 #id。"""
    if uid is None:
        return ""
    users = _cache.setdefault("users", {})
    if uid not in users:
        try:
            users[uid] = _get(f"get_user/{uid}").get("name") or f"#{uid}"
        except Exception:
            users[uid] = f"#{uid}"
    return users[uid]


def _tags(item):
    """把 custom_tctag / custom_situationtag / labels 解析成 [{group,text}]。"""
    fo = _field_options()
    out = []
    for i in item.get("custom_tctag") or []:
        out.append({"group": "tc",
                    "text": fo.get("custom_tctag", {}).get(i, f"tag{i}")})
    for i in item.get("custom_situationtag") or []:
        out.append({"group": "sit",
                    "text": fo.get("custom_situationtag", {}).get(i, f"s{i}")})
    for lb in item.get("labels") or []:
        out.append({"group": "label", "text": lb["title"]})
    return out


def _steps(item):
    """回傳結構化步驟 [{content,expected,info}]；純文字格式退回單欄。"""
    seps = item.get("custom_steps_separated")
    if seps:
        return [{"content": s.get("content", "") or "",
                 "expected": s.get("expected", "") or "",
                 "info": s.get("additional_info", "") or ""} for s in seps]
    if item.get("custom_steps"):
        return [{"content": item["custom_steps"], "expected": "", "info": ""}]
    return []


def _case_view(item, status_id=None):
    """把一筆 case 或 run-test 整理成前端要的完整檢視。"""
    return {
        "case_id": item.get("case_id", item.get("id")),
        "test_id": item.get("id") if "case_id" in item else None,
        "title": item.get("title", ""),
        "type": _case_types().get(item.get("type_id"), ""),
        "priority": _priorities().get(item.get("priority_id"), ""),
        "status": _statuses().get(status_id, "") if status_id else "",
        "status_id": status_id,
        "preconds": item.get("custom_preconds") or "",
        "steps": _steps(item),
        "tags": _tags(item),
    }


def get_case_view(case_id):
    """單一 test case 完整檢視。"""
    return {"kind": "case", "base_url": config.testrail_base_url(),
            "case": _case_view(_get(f"get_case/{case_id}"))}


def get_run_view(run_id):
    """run 主體 + 統計 + 底下所有 test（每筆含完整內容、狀態、驗證結果）。

    驗證結果一次並行預抓齊：留言人過濾需要每筆 result 的 created_by，
    不預抓就只能在點開單筆後才知道是誰留的、無法做清單層級的留言人過濾。
    """
    run = _get(f"get_run/{run_id}")
    tests = _get(f"get_tests/{run_id}")
    items = tests["tests"] if isinstance(tests, dict) else tests
    views = [_case_view(t, t.get("status_id")) for t in items]

    def _attach(v):
        if v["test_id"]:
            try:
                v["results"] = get_test_results(v["test_id"])
            except Exception:
                v["results"] = []
        else:
            v["results"] = []
        return v

    with ThreadPoolExecutor(max_workers=8) as pool:
        views = list(pool.map(_attach, views))
    return {
        "kind": "run",
        "base_url": config.testrail_base_url(),
        "run": {
            "id": run["id"], "name": run["name"],
            "description": run.get("description") or "",
            "passed": run.get("passed_count", 0),
            "failed": run.get("failed_count", 0),
            "blocked": run.get("blocked_count", 0),
            "untested": run.get("untested_count", 0),
            "retest": run.get("retest_count", 0),
        },
        "tests": views,
    }


def get_test_results(test_id):
    """某 run-test 的驗證結果 [{status,status_id,comment,by,created_on}]。
    by = 留言人顯示名稱（created_by 對照 get_user）。"""
    res = _get(f"get_results/{test_id}")
    items = res["results"] if isinstance(res, dict) else res
    st = _statuses()
    return [{"status": st.get(r.get("status_id"), ""),
             "status_id": r.get("status_id"),
             "comment": r.get("comment") or "",
             "by": _user_name(r.get("created_by")),
             "created_on": r.get("created_on")} for r in items]


def get_attachment(attachment_id):
    """帶 key 代理抓 attachment（圖片），回傳 (bytes, content_type)。"""
    email, key = config.testrail_auth()
    url = (f"{config.testrail_base_url()}/index.php?"
           f"/api/v2/get_attachment/{attachment_id}")
    resp = requests.get(url, auth=(email, key), timeout=30)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "application/octet-stream")
    return resp.content, ctype


# --- 舊 function 保留（其他 skill 可能用到）---
def get_case(case_id):
    data = _get(f"get_case/{case_id}")
    return {
        "id": data["id"], "title": data["title"],
        "preconditions": data.get("custom_preconds", ""),
        "steps": data.get("custom_steps", ""),
        "expected": data.get("custom_expected", ""),
    }


def get_run(run_id):
    run = _get(f"get_run/{run_id}")
    tests = _get(f"get_tests/{run_id}")
    items = tests["tests"] if isinstance(tests, dict) else tests
    return {"id": run["id"], "name": run["name"],
            "tests": [{"id": t["id"], "title": t["title"]} for t in items]}


def fetch(ref):
    """ref 為 parse_links.parse_testrail 的輸出。"""
    if ref["type"] == "run":
        return get_run(ref["id"])
    return get_case(ref["id"])


if __name__ == "__main__":
    import json
    print(json.dumps(get_case_view(int(sys.argv[1])),
                     ensure_ascii=False, indent=2))
