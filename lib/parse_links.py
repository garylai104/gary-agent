"""從使用者提供的連結解析出各服務的識別碼。"""
import re

_JIRA_KEY = re.compile(r"([A-Z][A-Z0-9]+-\d+)")
_GITHUB_PR = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_TESTRAIL = re.compile(r"testrail[^?]*\?/?(?:.*&)?(?:cases/view|runs/view|tests/view)/(\d+)")
_TESTRAIL_TYPE = re.compile(r"(cases|runs|tests)/view/\d+")


def parse_jira(url):
    m = _JIRA_KEY.search(url)
    if not m:
        raise ValueError(f"無法從連結解析 Jira issue key：{url}")
    return m.group(1)


def parse_github_pr(url):
    m = _GITHUB_PR.search(url)
    if not m:
        raise ValueError(f"無法從連結解析 GitHub PR：{url}")
    owner, repo, number = m.group(1), m.group(2), int(m.group(3))
    return owner, repo.removesuffix(".git"), number


def parse_testrail(url):
    m = _TESTRAIL.search(url)
    if not m:
        raise ValueError(f"無法從連結解析 TestRail id：{url}")
    type_m = _TESTRAIL_TYPE.search(url)
    kind = {"cases": "case", "runs": "run", "tests": "test"}[type_m.group(1)]
    return {"type": kind, "id": int(m.group(1))}


def find_testrail_links(text):
    """從一段文字（如 PR 描述）掃出所有 TestRail 連結。"""
    return re.findall(r"https?://[^\s)]*testrail[^\s)]*", text or "")
