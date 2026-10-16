"""解析 S3 上的 allure 報告：抓失敗 TC 的步驟、錯誤、attachment。

allure-report 內部結構（實測）：
  data/suites.json            測試樹，遞迴找 status==failed 的葉節點
  data/test-cases/{uid}.json  單一 TC 明細：steps / statusMessage / statusTrace
  data/attachments/{source}   步驟附件（API log、UI tree 等）

認證與 bucket 沿用 s3_report_client（同一套 AWS 金鑰）。
"""
import json

import s3_report_client

_ATTACH_LIMIT = 20000  # 單一 attachment 讀取上限（字元），避免超大 log 爆 token


def _report_prefix(report_url):
    """把 .../allure-report/index.html 這種連結轉回 S3 prefix（去掉 https 與 bucket）。

    相容兩種 host 格式：{bucket}.s3.{region}. 與 {bucket}.s3-{region}.
    """
    if ".amazonaws.com/" in report_url:
        key = report_url.split(".amazonaws.com/", 1)[1]
    else:
        key = report_url
    if key.endswith("index.html"):
        key = key[: -len("index.html")]
    return key.rstrip("/") + "/"


def _get_bytes(key):
    bucket = s3_report_client.config.aws_report_bucket()
    obj = s3_report_client._s3().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()


def _get_json(key):
    return json.loads(_get_bytes(key))


def _get_text(key):
    return _get_bytes(key).decode("utf-8", errors="replace")


def _walk_failed(node, out):
    if node.get("status") in ("failed", "broken"):
        if "children" not in node:  # 葉節點才是 TC
            out.append({
                "uid": node["uid"],
                "name": node["name"],
                "status": node["status"],
            })
    for child in node.get("children", []):
        _walk_failed(child, out)


def list_failed(report_url):
    """回傳該報告所有失敗/broken 的 TC：[{"uid","name","status"}]。"""
    prefix = _report_prefix(report_url)
    suites = _get_json(prefix + "data/suites.json")
    out = []
    for suite in suites.get("children", []):
        _walk_failed(suite, out)
    return out


def _read_attachments(prefix, atts):
    out = []
    for att in atts:
        try:
            text = _get_text(prefix + f"data/attachments/{att['source']}")
            out.append({
                "name": att.get("name", att["source"]),
                "content": text[:_ATTACH_LIMIT],
                "truncated": len(text) > _ATTACH_LIMIT,
            })
        except Exception as ex:
            out.append({"name": att.get("name", ""), "error": str(ex)})
    return out


def _collect_stage(prefix, stage, out):
    """把 stage（含其 steps）的 attachment 平鋪收進 out。

    log 可能掛在 stage 自身或失敗 step 上，兩處都撈。
    """
    out.extend(_read_attachments(prefix, stage.get("attachments", [])))
    for s in stage.get("steps", []):
        if s.get("status") in ("failed", "broken"):
            out.extend(_read_attachments(prefix, s.get("attachments", [])))


def get_case(report_url, uid, with_attachments=True):
    """抓單一失敗 TC 的完整明細（步驟、錯誤、attachment 內容）。"""
    prefix = _report_prefix(report_url)
    detail = _get_json(prefix + f"data/test-cases/{uid}.json")
    stage = detail.get("testStage", {})

    steps = [{"name": s.get("name", ""),
              "status": s.get("status", "unknown")}
             for s in stage.get("steps", [])]

    attachments = []
    if with_attachments:
        # log 可能在 beforeStages（fixture 失敗）、testStage、afterStages
        for st in detail.get("beforeStages", []):
            _collect_stage(prefix, st, attachments)
        _collect_stage(prefix, stage, attachments)
        for st in detail.get("afterStages", []):
            _collect_stage(prefix, st, attachments)

    return {
        "uid": uid,
        "name": detail.get("name", ""),
        "full_name": detail.get("fullName", ""),
        "status": detail.get("status", ""),
        "duration_sec": detail.get("time", {}).get("duration", 0) // 1000,
        "message": (detail.get("statusMessage")
                    or stage.get("statusMessage", "")),
        "trace": (detail.get("statusTrace")
                  or stage.get("statusTrace", "")),
        "steps": steps,
        "attachments": attachments,
    }


def get_summary(report_url):
    """讀 widgets/summary.json：整體統計（total/passed/failed/broken、起訖時間）。"""
    prefix = _report_prefix(report_url)
    data = _get_json(prefix + "widgets/summary.json")
    stat = data.get("statistic", {})
    total = stat.get("total", 0)
    fail = stat.get("failed", 0)
    broken = stat.get("broken", 0)
    return {
        "total": total,
        "passed": total - fail - broken - stat.get("skipped", 0),
        "failed": fail,
        "broken": broken,
        "skipped": stat.get("skipped", 0),
    }


def collect(report_url):
    """一次抓齊：報告內所有失敗 TC 的完整明細。給排查流程當入口。"""
    cases = [get_case(report_url, tc["uid"]) for tc in list_failed(report_url)]
    return {"report_url": report_url, "failed_count": len(cases), "cases": cases}


if __name__ == "__main__":
    import sys

    print(json.dumps(collect(sys.argv[1]), ensure_ascii=False, indent=2))
