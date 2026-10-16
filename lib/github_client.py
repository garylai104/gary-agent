"""抓取 GitHub PR 內容並可回貼 review comment（GitHub.com REST API）。"""
import sys

import requests

import config

_API = "https://api.github.com"


def _headers(accept="application/vnd.github+json"):
    return {
        "Authorization": f"Bearer {config.github_token()}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_pr(owner, repo, number):
    base = f"{_API}/repos/{owner}/{repo}/pulls/{number}"
    pr = requests.get(base, headers=_headers(), timeout=30)
    pr.raise_for_status()
    pr = pr.json()

    files = requests.get(f"{base}/files", headers=_headers(),
                         params={"per_page": 100}, timeout=30)
    files.raise_for_status()

    diff = requests.get(base, headers=_headers("application/vnd.github.v3.diff"),
                        timeout=30)
    diff.raise_for_status()

    return {
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": pr["title"],
        "body": pr.get("body") or "",
        "state": pr["state"],
        "base_branch": pr["base"]["ref"],
        "head_branch": pr["head"]["ref"],
        "files": [
            {"filename": f["filename"], "status": f["status"],
             "additions": f["additions"], "deletions": f["deletions"],
             "patch": f.get("patch", "")}
            for f in files.json()
        ],
        "diff": diff.text,
    }


def create_pull_request(owner, repo, title, head, base, body):
    """建立 PR。僅在使用者明確同意後呼叫（對外寫入）。

    head: 來源 branch（已 push 到遠端）；base: 目標 branch（如 master）。
    回傳 {"number", "html_url"}。
    """
    url = f"{_API}/repos/{owner}/{repo}/pulls"
    payload = {"title": title, "head": head, "base": base, "body": body}
    resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    pr = resp.json()
    return {"number": pr["number"], "html_url": pr["html_url"]}


def update_pull_request(owner, repo, number, *, title=None, body=None):
    """編輯既有 PR 的標題／內文。僅在使用者明確同意後呼叫（對外寫入）。

    title / body 為選填，只送有給的欄位——未給的不動，避免清空另一個。
    兩者皆未給則直接報錯（沒有要改的東西）。回傳 {"number", "html_url"}。
    """
    payload = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if not payload:
        raise ValueError("update_pull_request 需至少提供 title 或 body 其一")

    url = f"{_API}/repos/{owner}/{repo}/pulls/{number}"
    resp = requests.patch(url, headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    pr = resp.json()
    return {"number": pr["number"], "html_url": pr["html_url"]}


def post_comment(owner, repo, number, body):
    """回貼 PR comment。僅在使用者明確同意後呼叫。"""
    url = f"{_API}/repos/{owner}/{repo}/issues/{number}/comments"
    resp = requests.post(url, headers=_headers(), json={"body": body}, timeout=30)
    resp.raise_for_status()
    return resp.json()["html_url"]


def latest_commit_sha(owner, repo, number):
    """取得 PR 最新 commit 的 sha（逐行 review comment 需要）。"""
    url = f"{_API}/repos/{owner}/{repo}/pulls/{number}/commits"
    resp = requests.get(url, headers=_headers(), params={"per_page": 100}, timeout=30)
    resp.raise_for_status()
    return resp.json()[-1]["sha"]


def post_review_comment(owner, repo, number, commit_sha, path, line, body, side="RIGHT"):
    """把留言掛在 PR diff 的某一行。line 為 PR 新版行號；僅在使用者明確同意後呼叫。

    只能掛在此 PR 有改動到的行，否則 GitHub 回 422。
    """
    url = f"{_API}/repos/{owner}/{repo}/pulls/{number}/comments"
    payload = {"commit_id": commit_sha, "path": path, "line": line,
               "side": side, "body": body}
    resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["html_url"]


if __name__ == "__main__":
    owner, repo, number = sys.argv[1], sys.argv[2], int(sys.argv[3])
    pr = get_pr(owner, repo, number)
    print(f"[{pr['state']}] {pr['title']}（{len(pr['files'])} 個檔案變更）")
