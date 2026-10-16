"""撈取 Claude Code jsonl 紀錄，依台北時間歸日，按專案聚合並推算工時。

事實依據與時間規則見使用端 skill：jira-worklog-104 / ai-usage-record-104。
工時推算為「首筆～末筆時間戳」的區間，屬估計值，需人工確認。
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
TPE = timezone(timedelta(hours=8))

# 活躍時段偵測：相鄰訊息間隔 > IDLE_GAP 視為離開、斷開區間；
# 每個活躍區間末尾補 TAIL 分鐘（看回覆/消化）。
IDLE_GAP_MIN = 30
TAIL_MIN = 5


def _active_minutes(timestamps):
    """把時間戳切成活躍區間，回傳 (總分鐘, 區間明細)。

    間隔 > IDLE_GAP_MIN 就斷開；每個區間長度 = (末-首) + TAIL_MIN。
    """
    ts = sorted(timestamps)
    segments = []
    seg_start = seg_end = ts[0]
    for t in ts[1:]:
        if (t - seg_end).total_seconds() / 60 > IDLE_GAP_MIN:
            segments.append((seg_start, seg_end))
            seg_start = t
        seg_end = t
    segments.append((seg_start, seg_end))

    total = 0
    detail = []
    for s, e in segments:
        mins = round((e - s).total_seconds() / 60) + TAIL_MIN
        total += mins
        detail.append({"start": s.strftime("%H:%M"),
                       "end": e.strftime("%H:%M"), "minutes": mins})
    return total, detail


def _to_tpe(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TPE)


def _project_name(jsonl_path):
    # 資料夾名形如 -Users-gary-lai-Documents-104qa-104qa-pytest-ios
    return jsonl_path.parent.name


def _extract_actions(content):
    """從 assistant content list 抽出實際動作（改檔、Bash commit）。"""
    actions = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name", "")
        inp = block.get("input", {})
        if name in ("Edit", "Write", "NotebookEdit"):
            actions.append(f"{name}: {inp.get('file_path', '')}")
        elif name == "Bash":
            cmd = inp.get("command", "")
            if "git commit" in cmd:
                actions.append(f"commit: {_commit_message(cmd)}")
    return actions


def _commit_message(cmd):
    """從 git commit 指令抽出訊息標題行，過濾 heredoc/語法雜訊。"""
    import re
    lines = cmd.splitlines()
    # heredoc 形態：git commit -m "$(cat <<'EOF' 換行後才是真正訊息
    for i, line in enumerate(lines):
        if "<<" in line and "EOF" in line:
            for nxt in lines[i + 1:]:
                nxt = nxt.strip()
                if nxt and nxt != "EOF" and not nxt.startswith(("Co-Authored", "🤖")):
                    return nxt[:100]
    # 一般 -m "..." 形態
    m = re.search(r'-m\s+["\']([^"\']+)', cmd)
    if m:
        return m.group(1).strip()[:100]
    return "(git commit)"


# 這些開頭一律視為雜訊：系統標記、slash 指令、被中斷、context 續接、
# skill 觸發語（jira-worklog 自己的觸發 prompt 不算當天工作內容）。
_NOISE_PREFIXES = (
    "<", "[Request interrupted", "Caveat:", "This session is being continued",
    "Base directory for this skill", "執行 jira-worklog-104 skill",
)


def _user_text(content):
    """user 訊息的 content 可能是 str 或 list（含 text block），統一抽成純文字。
    tool_result（工具回傳）不算使用者意圖，略過。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(p for p in parts if p)
    return ""


def _is_real_intent(content):
    """判斷這則 user 訊息是否為真正的工作對話（歸單依據），濾掉系統/工具雜訊。"""
    t = content.strip()
    if len(t) < 3:
        return False
    return not t.startswith(_NOISE_PREFIXES)


def _agent_first_line(content):
    """抽 assistant 回覆的第一句非空文字（通常是結論句），濃縮上下文用。
    只取首句、砍掉程式碼/log，讓 dialogue 保留一來一回骨架又不爆 token。"""
    if not isinstance(content, list):
        return ""
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            for ln in b.get("text", "").strip().splitlines():
                if ln.strip():
                    return ln.strip()
    return ""


def collect(target_date):
    """target_date: 'YYYY-MM-DD'（台北時間）。回傳 {project: 任務聚合}。"""
    cutoff = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)
              ).strftime("%Y-%m-%d")
    projects = defaultdict(lambda: {
        "messages": [], "user_intents": [], "actions": [], "timestamps": [],
        "dialogue": [],  # [(tpe, "U"/"A", text)]，按時間交錯呈現一來一回
    })

    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        # 粗篩：檔案近期有改動才掃（縮小範圍，真正歸日仍逐行算）
        mtime = datetime.fromtimestamp(jsonl.stat().st_mtime)
        if mtime.strftime("%Y-%m-%d") < cutoff:
            continue
        proj = _project_name(jsonl)
        for line in jsonl.read_text(errors="ignore").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ts = d.get("timestamp")
            if not ts:
                continue
            tpe = _to_tpe(ts)
            if tpe.strftime("%Y-%m-%d") != target_date:
                continue
            bucket = projects[proj]
            bucket["timestamps"].append(tpe)
            msg = d.get("message", {})
            if d.get("type") == "user":
                text = _user_text(msg.get("content"))
                if text and _is_real_intent(text):
                    text = text.strip()[:600]
                    bucket["user_intents"].append(text)
                    bucket["dialogue"].append((tpe, "U", text))
            elif d.get("type") == "assistant":
                content = msg.get("content")
                if isinstance(content, list):
                    bucket["actions"].extend(_extract_actions(content))
                    line = _agent_first_line(content)
                    if line:
                        bucket["dialogue"].append((tpe, "A", line[:200]))

    return {p: _summarize(p, b)
            for p, b in projects.items() if b["timestamps"]}


def _summarize(project, bucket):
    ts = sorted(bucket["timestamps"])
    active, segments = _active_minutes(ts)
    # 去重並統計次數，避免截斷漏檔（同檔多次編輯只佔一列、附次數）
    action_counts = Counter(bucket["actions"])
    return {
        "project": project,
        "first": ts[0].isoformat(),
        "last": ts[-1].isoformat(),
        # active_minutes：活躍區間加總（扣掉長空檔），工時推估用這個
        "active_minutes": active,
        "segments": segments,
        # span_minutes：首到末（含空檔），僅供對照，勿當工時
        "span_minutes": round((ts[-1] - ts[0]).total_seconds() / 60),
        "user_intents": bucket["user_intents"][:50],
        # dialogue：user 全文 + agent 首句，按時間交錯，看得出一來一回的上下文。
        # 歸單時讀這個比 user_intents 更能判斷工作線；HH:MM U:/A: 前綴。
        "dialogue": [f"{t.strftime('%H:%M')} {who}: {tx}"
                     for t, who, tx in sorted(bucket["dialogue"],
                                              key=lambda x: x[0])][:100],
        "actions": [{"action": a, "count": c}
                    for a, c in action_counts.most_common()],
        "message_count": len(ts),
    }


if __name__ == "__main__":
    import sys
    result = collect(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
