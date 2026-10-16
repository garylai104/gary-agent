"""lib/jira_client.py 寫入型 function 的 mock 測試。

不打真實 Jira API，只驗證：送出的 URL/method 對不對、payload 組裝對不對。
跑法（從 gary-agent 根目錄）：
    .venv/bin/python -m pytest lib/tests/ -v
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jira_client  # noqa: E402

TPE = timezone(timedelta(hours=8))


def _mock_response(json_data=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data or {}
    return resp


@patch("jira_client.config")
@patch("jira_client.requests")
def test_add_worklog_sends_correct_payload(mock_requests, mock_config):
    mock_config.jira_auth.return_value = ("a@b.com", "token")
    mock_config.jira_base_url.return_value = "https://jira.example.com"
    mock_requests.post.return_value = _mock_response({"id": "12345"})

    started = datetime(2026, 7, 13, 9, 0, 0, tzinfo=TPE)
    result = jira_client.add_worklog("ITQAWORK-1", "2h 30m", "測試 comment", started)

    assert result == "12345"
    args, kwargs = mock_requests.post.call_args
    assert args[0] == "https://jira.example.com/rest/api/3/issue/ITQAWORK-1/worklog"
    assert kwargs["json"]["timeSpent"] == "2h 30m"
    assert kwargs["json"]["started"].startswith("2026-07-13T09:00:00.000")
    # comment 應轉成 ADF doc 結構，不是純字串
    assert kwargs["json"]["comment"]["type"] == "doc"
    assert kwargs["auth"] == ("a@b.com", "token")


@patch("jira_client.config")
@patch("jira_client.requests")
def test_update_worklog_uses_put_and_does_not_touch_started(mock_requests, mock_config):
    mock_config.jira_auth.return_value = ("a@b.com", "token")
    mock_config.jira_base_url.return_value = "https://jira.example.com"
    mock_requests.put.return_value = _mock_response({"id": "999"})

    result = jira_client.update_worklog("ITQAWORK-1", "999", "1h", "改過的 comment")

    assert result == "999"
    args, kwargs = mock_requests.put.call_args
    assert args[0] == "https://jira.example.com/rest/api/3/issue/ITQAWORK-1/worklog/999"
    assert kwargs["json"]["timeSpent"] == "1h"
    assert "started" not in kwargs["json"]


@patch("jira_client.config")
@patch("jira_client.requests")
def test_delete_worklog_uses_delete_method(mock_requests, mock_config):
    mock_config.jira_auth.return_value = ("a@b.com", "token")
    mock_config.jira_base_url.return_value = "https://jira.example.com"
    mock_requests.delete.return_value = _mock_response()

    jira_client.delete_worklog("ITQAWORK-1", "999")

    args, kwargs = mock_requests.delete.call_args
    assert args[0] == "https://jira.example.com/rest/api/3/issue/ITQAWORK-1/worklog/999"


@patch("jira_client.config")
@patch("jira_client.requests")
def test_set_fields_converts_plain_string_to_adf(mock_requests, mock_config):
    mock_config.jira_auth.return_value = ("a@b.com", "token")
    mock_config.jira_base_url.return_value = "https://jira.example.com"
    mock_requests.put.return_value = _mock_response()

    jira_client.set_fields("ITQAWORK-1", {"customfield_10001": "純文字內容"})

    args, kwargs = mock_requests.put.call_args
    sent = kwargs["json"]["fields"]["customfield_10001"]
    assert sent["type"] == "doc"


@patch("jira_client.config")
@patch("jira_client.requests")
def test_set_fields_passes_through_existing_adf_dict(mock_requests, mock_config):
    mock_config.jira_auth.return_value = ("a@b.com", "token")
    mock_config.jira_base_url.return_value = "https://jira.example.com"
    mock_requests.put.return_value = _mock_response()

    adf = {"type": "doc", "version": 1, "content": []}
    jira_client.set_fields("ITQAWORK-1", {"customfield_10001": adf})

    args, kwargs = mock_requests.put.call_args
    assert kwargs["json"]["fields"]["customfield_10001"] is adf


@patch("jira_client.config")
@patch("jira_client.requests")
def test_add_comment_accepts_plain_string(mock_requests, mock_config):
    mock_config.jira_auth.return_value = ("a@b.com", "token")
    mock_config.jira_base_url.return_value = "https://jira.example.com"
    mock_requests.post.return_value = _mock_response({"id": "555"})

    result = jira_client.add_comment("ITQAWORK-1", "純文字留言")

    assert result == "555"
    args, kwargs = mock_requests.post.call_args
    assert args[0] == "https://jira.example.com/rest/api/3/issue/ITQAWORK-1/comment"
    assert kwargs["json"]["body"]["type"] == "doc"
