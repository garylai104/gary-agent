"""工時 entries 的格式轉換：輸出成「小鬧鐘工具」的 timer_sessions.json。

entries 與 write_worklog 同格式：
  [{issue_key, time_spent, comment, started?}]
小鬧鐘格式：
  {"date": "YYYY-MM-DD",
   "sessions": [{issue_key, started, time_spent, comment}]}
其中 started 為 "HH:MM"。
"""
import json
from datetime import datetime
from pathlib import Path

# lib/ -> gary-agent/小鬧鐘工具/jira_api/timer_sessions.json
TIMER_SESSIONS = (Path(__file__).resolve().parents[1]
                  / "小鬧鐘工具" / "jira_api" / "timer_sessions.json")


def _to_hhmm(started):
    """started（ISO 或 HH:MM）統一轉成小鬧鐘要的 HH:MM。"""
    if not started:
        return "09:00"
    if "T" in started:
        return datetime.fromisoformat(started).strftime("%H:%M")
    return started[:5]


def _parse_seconds(time_spent: str) -> int:
    """'2h 30m' / '1h' / '45m' → seconds"""
    import re
    total = 0
    for h in re.findall(r'(\d+)\s*h', time_spent):
        total += int(h) * 3600
    for m in re.findall(r'(\d+)\s*m', time_spent):
        total += int(m) * 60
    return total


def _seconds_to_hm(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m = rem // 60
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def to_timer_sessions(entries, path=TIMER_SESSIONS):
    """把 entries 寫入小鬧鐘的 timer_sessions.json。

    相同 issue_key 已存在 → 工時加總、comment 合併條列。
    不同 issue_key → 新增一筆。
    不同日則清空重建。
    """
    today = datetime.now().strftime("%Y-%m-%d")

    path = Path(path)
    sessions: list = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("date") == today:
                sessions = data.get("sessions", [])
        except Exception:
            pass

    # index by issue_key（保留第一筆的 started）
    index = {s["issue_key"]: i for i, s in enumerate(sessions)}

    merged = 0
    added = 0
    for e in entries:
        key = e["issue_key"]
        new_time = e["time_spent"]
        new_comment = e.get("comment", "")
        new_started = _to_hhmm(e.get("started"))

        if key in index:
            existing = sessions[index[key]]
            if not existing.get("uploaded"):
                # 未上傳：工時加總
                total_sec = (
                    _parse_seconds(existing["time_spent"])
                    + _parse_seconds(new_time)
                )
                existing["time_spent"] = _seconds_to_hm(total_sec)
            # 已上傳或未上傳都合併 comment
            parts = [p for p in [existing.get("comment", ""), new_comment]
                     if p]
            existing["comment"] = "\n".join(parts)
            existing["uploaded"] = False  # 有新內容，重新標為待上傳
            merged += 1
        else:
            sessions.append({
                "issue_key": key,
                "started": new_started,
                "time_spent": new_time,
                "comment": new_comment,
                "uploaded": False,
            })
            index[key] = len(sessions) - 1
            added += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "sessions": sessions}, f,
                  ensure_ascii=False, indent=2)
    return {"merged": merged, "added": added}


if __name__ == "__main__":
    import sys
    result = to_timer_sessions(json.load(sys.stdin))
    print(f"已合併 {result['merged']} 筆、新增 {result['added']} 筆到 {TIMER_SESSIONS}")
