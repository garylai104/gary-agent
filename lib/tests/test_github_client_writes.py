"""lib/github_client.py 寫入型 function 的 mock 測試。

不打真實 GitHub API，只驗證：送出的 URL/method 對不對、payload 組裝對不對。
跑法（從 gary-agent 根目錄）：
    .venv/bin/python -m pytest lib/tests/ -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import github_client  # noqa: E402


def _mock_response(json_data=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data or {}
    return resp


@patch("github_client.config")
@patch("github_client.requests")
def test_post_comment_sends_to_issues_comments_endpoint(mock_requests, mock_config):
    mock_config.github_token.return_value = "gh-token"
    mock_requests.post.return_value = _mock_response(
        {"html_url": "https://github.com/o/r/pull/1#comment-1"})

    url = github_client.post_comment("owner", "repo", 1, "審查內容")

    assert url == "https://github.com/o/r/pull/1#comment-1"
    args, kwargs = mock_requests.post.call_args
    assert args[0] == "https://api.github.com/repos/owner/repo/issues/1/comments"
    assert kwargs["json"]["body"] == "審查內容"
    assert kwargs["headers"]["Authorization"] == "Bearer gh-token"


@patch("github_client.config")
@patch("github_client.requests")
def test_create_pull_request_sends_correct_payload(mock_requests, mock_config):
    mock_config.github_token.return_value = "gh-token"
    mock_requests.post.return_value = _mock_response(
        {"number": 42, "html_url": "https://github.com/o/r/pull/42"})

    result = github_client.create_pull_request(
        "owner", "repo", "[Fix] xxx", "fix/xxx", "master", "body 內容")

    assert result == {"number": 42, "html_url": "https://github.com/o/r/pull/42"}
    args, kwargs = mock_requests.post.call_args
    assert args[0] == "https://api.github.com/repos/owner/repo/pulls"
    assert kwargs["json"] == {
        "title": "[Fix] xxx", "head": "fix/xxx", "base": "master", "body": "body 內容",
    }


@patch("github_client.config")
@patch("github_client.requests")
def test_update_pull_request_body_only(mock_requests, mock_config):
    mock_config.github_token.return_value = "gh-token"
    mock_requests.patch.return_value = _mock_response(
        {"number": 253, "html_url": "https://github.com/o/r/pull/253"})

    result = github_client.update_pull_request(
        "owner", "repo", 253, body="新內文")

    assert result == {"number": 253, "html_url": "https://github.com/o/r/pull/253"}
    args, kwargs = mock_requests.patch.call_args
    assert args[0] == "https://api.github.com/repos/owner/repo/pulls/253"
    # 只送 body，未給 title 不應出現在 payload（避免清空標題）
    assert kwargs["json"] == {"body": "新內文"}


@patch("github_client.config")
@patch("github_client.requests")
def test_update_pull_request_title_and_body(mock_requests, mock_config):
    mock_config.github_token.return_value = "gh-token"
    mock_requests.patch.return_value = _mock_response(
        {"number": 253, "html_url": "https://github.com/o/r/pull/253"})

    github_client.update_pull_request(
        "owner", "repo", 253, title="[Fix] 新標題", body="新內文")

    args, kwargs = mock_requests.patch.call_args
    assert kwargs["json"] == {"title": "[Fix] 新標題", "body": "新內文"}


def test_update_pull_request_requires_at_least_one_field():
    import pytest
    with pytest.raises(ValueError):
        github_client.update_pull_request("owner", "repo", 253)


@patch("github_client.config")
@patch("github_client.requests")
def test_post_review_comment_pins_to_diff_line(mock_requests, mock_config):
    mock_config.github_token.return_value = "gh-token"
    mock_requests.post.return_value = _mock_response(
        {"html_url": "https://github.com/o/r/pull/1#discussion_r1"})

    url = github_client.post_review_comment(
        "owner", "repo", 1, "sha123", "a.py", 42, "留言內容")

    assert url == "https://github.com/o/r/pull/1#discussion_r1"
    args, kwargs = mock_requests.post.call_args
    assert args[0] == "https://api.github.com/repos/owner/repo/pulls/1/comments"
    assert kwargs["json"] == {
        "commit_id": "sha123", "path": "a.py", "line": 42,
        "side": "RIGHT", "body": "留言內容",
    }
