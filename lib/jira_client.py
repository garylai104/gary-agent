"""抓取 Jira issue 的需求內容（Jira Cloud REST API v3）。"""
import sys
from datetime import datetime, timedelta, timezone

import requests

import config

TPE = timezone(timedelta(hours=8))


def _adf_to_text(node):
    """把 Jira 的 ADF（Atlassian Document Format）描述攤平成純文字。"""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    parts = []
    if node.get("type") == "text":
        parts.append(node.get("text", ""))
    for child in node.get("content", []):
        parts.append(_adf_to_text(child))
    text = "".join(parts)
    if node.get("type") in ("paragraph", "heading", "listItem"):
        text += "\n"
    return text


def get_issue(issue_key):
    email, token = config.jira_auth()
    url = f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
    resp = requests.get(
        url,
        auth=(email, token),
        headers={"Accept": "application/json"},
        params={"fields": "summary,description,status,issuetype,labels"},
        timeout=30,
    )
    resp.raise_for_status()
    fields = resp.json()["fields"]
    return {
        "key": issue_key,
        "summary": fields["summary"],
        "description": _adf_to_text(fields.get("description")).strip(),
        "status": fields["status"]["name"],
        "issuetype": fields["issuetype"]["name"],
        "labels": fields.get("labels", []),
    }


def _text_to_adf(text):
    """純文字（多行）轉成 Jira worklog comment 需要的 ADF 結構。"""
    lines = text.splitlines() or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph",
             "content": [{"type": "text", "text": line}] if line else []}
            for line in lines
        ],
    }


def add_worklog(issue_key, time_spent, comment, started):
    """新增一筆 worklog。

    time_spent: 如 "2h 30m"
    comment:    純文字，內部轉 ADF
    started:    datetime（帶 tzinfo），格式化成 Jira 要求的毫秒+時區
    """
    email, token = config.jira_auth()
    url = f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}/worklog"
    # Jira 要求 .000+0800 形式：毫秒3位、時區無冒號
    started_str = started.strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{started.microsecond // 1000:03d}" + started.strftime("%z")
    payload = {
        "timeSpent": time_spent,
        "started": started_str,
        "comment": _text_to_adf(comment),
    }
    resp = requests.post(
        url, auth=(email, token),
        headers={"Accept": "application/json",
                 "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def update_worklog(issue_key, worklog_id, time_spent, comment):
    """修改既有 worklog 的工時與 comment（started 不動）。"""
    email, token = config.jira_auth()
    url = (f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
           f"/worklog/{worklog_id}")
    payload = {"timeSpent": time_spent, "comment": _text_to_adf(comment)}
    resp = requests.put(
        url, auth=(email, token),
        headers={"Accept": "application/json",
                 "Content-Type": "application/json"},
        json=payload, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def delete_worklog(issue_key, worklog_id):
    """從 Jira 移除一筆 worklog。"""
    email, token = config.jira_auth()
    url = (f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
           f"/worklog/{worklog_id}")
    resp = requests.delete(url, auth=(email, token), timeout=30)
    resp.raise_for_status()


def get_fields(issue_key, fields):
    """讀指定欄位原始值。fields 為欄位 id 清單（含自訂 customfield_xxxxx）。

    回傳 {field_id: 原始值}。自訂 ADF 欄位值為 ADF dict，可自行攤平。
    """
    email, token = config.jira_auth()
    url = f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
    resp = requests.get(
        url, auth=(email, token),
        headers={"Accept": "application/json"},
        params={"fields": ",".join(fields)}, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["fields"]


def set_fields(issue_key, fields):
    """寫入欄位。fields 為 {field_id: 值}。

    純文字欄位傳字串會自動轉 ADF；已是 ADF dict（含 doc/paragraph）則原樣送。
    支援自訂欄位（customfield_xxxxx）。回傳 True。
    """
    email, token = config.jira_auth()
    url = f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
    payload = {}
    for fid, val in fields.items():
        if isinstance(val, str):
            payload[fid] = _text_to_adf(val)
        else:
            payload[fid] = val
    resp = requests.put(
        url, auth=(email, token),
        headers={"Accept": "application/json",
                 "Content-Type": "application/json"},
        json={"fields": payload}, timeout=30,
    )
    resp.raise_for_status()
    return True


# 「自動化測試錯誤」單型的排查結果欄位（qa-diagnosis 回填用）
DIAGNOSIS_FIELDS = {
    "fail_reason": "customfield_17170",       # 失敗原因（下拉）
    "close_method": "customfield_17171",      # 結案方式（下拉）
    "fail_reason_desc": "customfield_19635",  # 失敗原因說明（文字/ADF）
    "close_method_desc": "customfield_19636",  # 結案方式說明（文字/ADF）
}
FAIL_REASON_OPTIONS = [
    "測試資料問題", "系統Bug", "腳本問題", "不穩定測試",
    "其他產品問題", "QA環境問題", "開單誤報", "規格異動", "其他",
]
CLOSE_METHOD_OPTIONS = [
    "調整腳本", "工程已修復Bug", "重跑後正常", "更正測試資料", "無需處理​",
]


def set_diagnosis_result(issue_key, fail_reason, close_method,
                         fail_reason_desc, close_method_desc):
    """一次回填排查結果四欄位（失敗原因/結案方式下拉 + 兩段說明）。

    fail_reason / close_method 傳 FAIL_REASON_OPTIONS /
    CLOSE_METHOD_OPTIONS 內的值。
    *_desc 傳純文字（自動轉 ADF）或已組好的 ADF dict（要放連結/多段時）。
    """
    assert fail_reason in FAIL_REASON_OPTIONS, f"失敗原因不合法：{fail_reason}"
    assert close_method in CLOSE_METHOD_OPTIONS, f"結案方式不合法：{close_method}"
    return set_fields(issue_key, {
        DIAGNOSIS_FIELDS["fail_reason"]: {"value": fail_reason},
        DIAGNOSIS_FIELDS["close_method"]: {"value": close_method},
        DIAGNOSIS_FIELDS["fail_reason_desc"]: fail_reason_desc,
        DIAGNOSIS_FIELDS["close_method_desc"]: close_method_desc,
    })


def get_issue_links(issue_key):
    """讀關聯票（relates to 等）。回傳 [{"relation","key","status","summary"}]。

    排查時用來追同 TC 近期是否出現過關聯單、當時怎麼結的。
    """
    email, token = config.jira_auth()
    url = f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
    resp = requests.get(
        url, auth=(email, token),
        headers={"Accept": "application/json"},
        params={"fields": "issuelinks"}, timeout=30,
    )
    resp.raise_for_status()
    result = []
    for link in resp.json()["fields"].get("issuelinks", []):
        if "outwardIssue" in link:
            issue, relation = link["outwardIssue"], link["type"]["outward"]
        else:
            issue, relation = link["inwardIssue"], link["type"]["inward"]
        result.append({
            "relation": relation,
            "key": issue["key"],
            "status": issue["fields"]["status"]["name"],
            "summary": issue["fields"]["summary"],
        })
    return result


def get_comments(issue_key):
    """讀所有 comment，攤平成純文字。回傳 [{"id","author","date","text"}]。

    date 為留言日（YYYY-MM-DD），排查看錯誤頻率用。
    """
    email, token = config.jira_auth()
    url = (f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
           f"/comment")
    resp = requests.get(
        url, auth=(email, token),
        headers={"Accept": "application/json"}, timeout=30,
    )
    resp.raise_for_status()
    out = []
    for c in resp.json().get("comments", []):
        out.append({
            "id": c["id"],
            "author": c["author"]["displayName"],
            "date": c["created"][:10],
            "text": _adf_to_text(c.get("body")).strip(),
        })
    return out


def _extract_error_reason(text):
    """從自動開單留言抽錯誤原因摘要行（description/AssertionError/Error）。

    抽不到就回第一行，讓排查端仍能大致比對；要精確判斷再看 text 全文。
    """
    for line in text.splitlines():
        s = line.strip().strip('",')
        if s.startswith('"description"') or "Error" in s or "Exception" in s:
            return s
    return text.splitlines()[0].strip() if text.strip() else ""


def get_diagnosis_context(issue_key):
    """排查用：一次取回單本身＋逐則留言（含錯誤原因）＋關聯票，供 Phase 0 建立假設。

    回傳 {
      "issue":         get_issue 的整理結果,
      "comment_count": 留言則數（自動開單「每天有錯才留言」→ 即錯誤頻率）,
      "comments":      [{"date","reason","text"}]，逐則含日期＋抽出的錯誤原因＋全文,
                       頻率高時還要逐則比對 reason 是否同因（同因反覆＝真問題）,
      "links":         get_issue_links 的關聯票（同 TC 近期單、前案結論）,
    }
    """
    raw = get_comments(issue_key)
    comments = [
        {"date": c["date"],
         "reason": _extract_error_reason(c["text"]),
         "text": c["text"]}
        for c in raw
    ]
    return {
        "issue": get_issue(issue_key),
        "comment_count": len(comments),
        "comments": comments,
        "links": get_issue_links(issue_key),
    }


def find_my_child_issues(parent_key, include_done=False):
    """查某張母票底下、指派給本人（.env 的 Jira 帳號）的子票。

    預設只回未結案（statusCategory != Done），即待排查清單；
    include_done=True 連已結案一起回。依建立時間新到舊。
    回傳 [{"key","summary","status","created"}]。
    """
    email, token = config.jira_auth()
    jql = f"parent = {parent_key} AND assignee = currentUser()"
    if not include_done:
        jql += " AND statusCategory != Done"
    jql += " ORDER BY created DESC"
    params = {"jql": jql, "fields": "summary,status,created",
              "maxResults": 100}
    out = []
    while True:
        resp = requests.get(
            f"{config.jira_base_url()}/rest/api/3/search/jql",
            auth=(email, token),
            headers={"Accept": "application/json"},
            params=params, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for i in data["issues"]:
            out.append({
                "key": i["key"],
                "summary": i["fields"]["summary"],
                "status": i["fields"]["status"]["name"],
                "created": i["fields"]["created"][:10],
            })
        if data.get("isLast", True):
            return out
        params["nextPageToken"] = data["nextPageToken"]


INVESTIGATING_STATUS = "Investigating 調查中"
# 轉 Closed 的「可結案」彈窗要填失敗原因/結案方式；API 不強制，
# 須先用 set_diagnosis_result 寫好再轉，否則會結出空欄位的單
CLOSED_STATUS = "Closed"


def transition_to(issue_key, target_status):
    """把單轉到指定狀態（依目標狀態名稱找可用 transition，不寫死 transition id）。

    已在目標狀態則不動作、回 False；轉換成功回 True。
    目前狀態走不到目標狀態時丟 ValueError，附上可用的目標狀態。
    """
    email, token = config.jira_auth()
    url = f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}/transitions"
    if get_issue(issue_key)["status"] == target_status:
        return False
    resp = requests.get(
        url, auth=(email, token),
        headers={"Accept": "application/json"}, timeout=30,
    )
    resp.raise_for_status()
    transitions = resp.json()["transitions"]
    match = [t for t in transitions if t["to"]["name"] == target_status]
    if not match:
        available = [t["to"]["name"] for t in transitions]
        raise ValueError(f"{issue_key} 無法轉到「{target_status}」，可用：{available}")
    resp = requests.post(
        url, auth=(email, token),
        headers={"Accept": "application/json",
                 "Content-Type": "application/json"},
        json={"transition": {"id": match[0]["id"]}}, timeout=30,
    )
    resp.raise_for_status()
    return True


def add_comment(issue_key, adf_or_text):
    """新增一則 comment。傳字串走純文字，傳 ADF dict 則原樣送。"""
    email, token = config.jira_auth()
    url = (f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}"
           f"/comment")
    body = (_text_to_adf(adf_or_text) if isinstance(adf_or_text, str)
            else adf_or_text)
    resp = requests.post(
        url, auth=(email, token),
        headers={"Accept": "application/json",
                 "Content-Type": "application/json"},
        json={"body": body}, timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


# --- ADF 建構小工具：組帶 inlineCard（智慧連結）的富文本 ---

# ADF 富文本 helper。用法重點（踩過的坑）：
# - adf_doc / adf_para 吃可變參數，傳位置參數勿包 list
#   （adf_doc([p]) 結構壞會 400）。
# - 可點連結用 adf_text(文字, href=url)（link mark），內外部 URL 皆通用。
# - adf_card（inlineCard）只對同站 Jira 票 URL 有效；
#   外部網址（GitHub 等）會 400，改用 adf_text href。
# - set_fields 對字串值會自動轉 ADF；要放連結就傳手組 ADF dict。
# - 路徑/呼叫鏈/指令用 adf_code（codeBlock），別塞在 adf_para 裡變一長串純文字。
# - 多點證據用 adf_list(..., ordered=True)，別用多個 adf_para 平行排。
def adf_doc(*paragraphs):
    """多個 paragraph 組成 ADF doc。paragraphs 為位置參數，勿傳 list。"""
    return {"type": "doc", "version": 1, "content": list(paragraphs)}


def adf_para(*inline):
    """組 paragraph。inline 傳 adf_text/adf_card，為位置參數，勿傳 list。"""
    return {"type": "paragraph", "content": list(inline)}


def adf_text(text, href=None):
    """一段文字；給 href 則為一般超連結。"""
    node = {"type": "text", "text": text}
    if href:
        node["marks"] = [{"type": "link", "attrs": {"href": href}}]
    return node


def adf_card(url):
    """inlineCard 智慧連結（Jira 票會顯示成票號+標題+狀態卡片）。"""
    return {"type": "inlineCard", "attrs": {"url": url}}


def adf_code(text):
    """codeBlock 等寬區塊。放路徑、呼叫鏈、指令、traceback。

    text 內的換行直接生效，不需拆多個節點。
    """
    return {"type": "codeBlock", "attrs": {},
            "content": [{"type": "text", "text": text}]}


def adf_list(*items, ordered=False):
    """條列。items 每項傳字串，或傳 tuple/list 表該項的多個 inline 節點。

    ordered=True 為編號清單（1. 2. 3.），否則為項目符號。
    需要在某項內放連結時，該項傳 (adf_text(...), adf_card(...)) 這種 tuple。
    """
    nodes = []
    for item in items:
        inline = [adf_text(item)] if isinstance(item, str) else list(item)
        nodes.append({"type": "listItem",
                      "content": [{"type": "paragraph", "content": inline}]})
    return {"type": "orderedList" if ordered else "bulletList",
            "attrs": {}, "content": nodes}


def _parse_jira_dt(value):
    """Jira 的 '2026-01-05T17:30:58.288+0800'（時區無冒號）轉 datetime。"""
    value = value.replace("Z", "+0000")
    if value[-5] in "+-" and value[-3] != ":":
        value = value[:-2] + ":" + value[-2:]
    return datetime.fromisoformat(value)


def find_worklog_issues_on(date_str):
    """查當天（台北時間 YYYY-MM-DD）由本人記過 worklog 的所有 issue key。

    用 JQL 找，不受本機常用名單限制——名單只用於「新增」的下拉候選，
    畫面顯示一律以 Jira 線上實際資料為準。
    """
    email, token = config.jira_auth()
    jql = f'worklogAuthor = currentUser() AND worklogDate = "{date_str}"'
    resp = requests.get(
        f"{config.jira_base_url()}/rest/api/3/search/jql",
        auth=(email, token),
        headers={"Accept": "application/json"},
        params={"jql": jql, "fields": "summary"}, timeout=30,
    )
    resp.raise_for_status()
    return [{"key": i["key"], "label": i["fields"]["summary"]}
            for i in resp.json().get("issues", [])]


def find_worklog_issues_between(start_date, end_date):
    """查區間內（含頭尾，台北時間 YYYY-MM-DD）由本人記過 worklog 的所有 issue key。

    一次 JQL 查完整段區間，避免逐天各打一次 API。用途同
    find_worklog_issues_on，只是擴充成範圍查詢（歷史紀錄區塊用）。
    """
    email, token = config.jira_auth()
    jql = (f'worklogAuthor = currentUser() AND '
           f'worklogDate >= "{start_date}" AND worklogDate <= "{end_date}"')
    resp = requests.get(
        f"{config.jira_base_url()}/rest/api/3/search/jql",
        auth=(email, token),
        headers={"Accept": "application/json"},
        params={"jql": jql, "fields": "summary"}, timeout=30,
    )
    resp.raise_for_status()
    return [{"key": i["key"], "label": i["fields"]["summary"]}
            for i in resp.json().get("issues", [])]


def _fetch_worklogs(issue_key):
    """取某張單全部 worklog，過濾出本人記的，回傳含台北時間日期。"""
    email, token = config.jira_auth()
    url = f"{config.jira_base_url()}/rest/api/3/issue/{issue_key}/worklog"
    resp = requests.get(
        url, auth=(email, token),
        headers={"Accept": "application/json"}, timeout=30,
    )
    resp.raise_for_status()
    out = []
    for wl in resp.json().get("worklogs", []):
        author = wl.get("author", {}).get("emailAddress", "")
        if author.lower() != email.lower():
            continue
        started = _parse_jira_dt(wl["started"]).astimezone(TPE)
        out.append({
            "id": wl["id"],
            "date": started.strftime("%Y-%m-%d"),
            "time_spent": wl["timeSpent"],
            "seconds": wl.get("timeSpentSeconds", 0),
            "comment": _adf_to_text(wl.get("comment")).strip(),
            "started": started.isoformat(),
        })
    return out


def get_worklogs_on(issue_key, date_str):
    """取某張單、某天（台北時間 YYYY-MM-DD）、由本人記的 worklog。

    回傳 [{"id","time_spent","seconds","comment","started"}]。
    """
    return [w for w in _fetch_worklogs(issue_key) if w["date"] == date_str]


def get_worklogs_between(issue_key, start_date, end_date):
    """取某張單、某區間（含頭尾，台北時間 YYYY-MM-DD）、由本人記的 worklog。

    回傳同 get_worklogs_on，每筆多帶 "date" 欄位方便呼叫端按日分組。
    """
    return [w for w in _fetch_worklogs(issue_key)
            if start_date <= w["date"] <= end_date]


if __name__ == "__main__":
    issue = get_issue(sys.argv[1])
    print(f"[{issue['key']}] {issue['summary']} ({issue['status']})")
    print(issue["description"][:500])
