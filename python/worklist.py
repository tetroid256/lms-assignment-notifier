"""課題の提出済み/未提出を一覧にする。

単体実行で動作確認できる(Discordには送らない):
    python worklist.py            # 未提出と提出済みの両方
    python worklist.py todo       # 未提出だけ
    python worklist.py done       # 提出済みだけ
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from notify import JST, WEEKDAYS, call_api, fetch_tasks, load_env

DISCORD_LIMIT = 1900


def short_course(name: str) -> str:
    """「科目名（年度_曜日限…）」の括弧以降を落とす。"""
    for mark in ("（", "("):
        name = name.split(mark)[0]
    return name.strip()


def is_submitted(status: dict) -> tuple[bool, int]:
    """(提出済みか, 提出日時) を返す。個人提出とチーム提出の両方を見る。"""
    attempt = status.get("lastattempt") or {}
    best_time = 0
    submitted = bool(attempt.get("submitted"))
    for key in ("submission", "teamsubmission"):
        sub = attempt.get(key) or {}
        if sub.get("status") == "submitted":
            submitted = True
            best_time = max(best_time, sub.get("timemodified", 0))
    return submitted, best_time


def fetch_worklist(base: str, token: str, past_days: int, future_days: int, excludes: list[str]) -> dict:
    """{"todo": [...], "done": [...], "note": str} を返す。"""
    now = int(time.time())
    window_from = now - past_days * 86400
    window_to = now + future_days * 86400
    note = ""
    todo: list[dict] = []
    done: list[dict] = []

    def excluded(name: str) -> bool:
        return any(word and word in name for word in excludes)

    try:
        userid = call_api(base, token, "core_webservice_get_site_info")["userid"]
        courses = call_api(base, token, "core_enrol_get_users_courses", userid=userid)
        courses = [c for c in courses if not c.get("enddate") or c["enddate"] > window_from]
        params = {f"courseids[{i}]": c["id"] for i, c in enumerate(courses)}
        listing = call_api(base, token, "mod_assign_get_assignments", **params)

        for course in listing.get("courses", []):
            for assign in course.get("assignments", []):
                due = assign.get("duedate", 0)
                name = assign.get("name", "").strip()
                if not due or not (window_from <= due <= window_to) or excluded(name):
                    continue
                status = call_api(base, token, "mod_assign_get_submission_status", assignid=assign["id"])
                submitted, submitted_at = is_submitted(status)
                item = {
                    "name": name,
                    "due": datetime.fromtimestamp(due, JST),
                    "course": short_course(course.get("fullname", "")),
                    "submitted_at": datetime.fromtimestamp(submitted_at, JST) if submitted_at else None,
                }
                (done if submitted else todo).append(item)

        # 課題以外(小テストなど)は、未提出としてカレンダーの行動イベントから補う
        extra = fetch_tasks(base, token, future_days, excludes, only_non_assign=True)
        todo.extend(extra)
    except Exception as error:
        # 課題APIが使えない場合は、未提出の一覧だけでも出す
        note = f"提出済みの取得に失敗したため、未提出のみ表示しています ({error})"
        done = []
        todo = fetch_tasks(base, token, future_days, excludes)

    todo.sort(key=lambda t: t["due"])
    done.sort(key=lambda t: t["due"], reverse=True)
    return {"todo": todo, "done": done, "note": note}


def format_worklist(data: dict, past_days: int, future_days: int, show: str = "both") -> list[str]:
    """Discordの文字数制限に収まるよう、複数メッセージに分けて返す。"""
    now = datetime.now(JST)
    lines = [f"{now:%m/%d}({WEEKDAYS[now.weekday()]}) 課題一覧"]
    if data["note"]:
        lines.append(f"注意: {data['note']}")

    if show in ("both", "todo"):
        lines += ["", f"【未提出】{len(data['todo'])}件 (今後{future_days}日以内 / 期限超過を含む)"]
        if not data["todo"]:
            lines.append("なし")
        for task in data["todo"]:
            due = task["due"]
            left = (due.date() - now.date()).days
            when = "期限超過" if due < now else "今日" if left == 0 else "明日" if left == 1 else f"{left}日後"
            lines.append(f"・{task['name']}")
            lines.append(f"　{due:%m/%d}({WEEKDAYS[due.weekday()]}) {due:%H:%M} ({when})  {task['course']}")

    if show in ("both", "done"):
        lines += ["", f"【提出済み】{len(data['done'])}件 (期限が過去{past_days}日〜今後{future_days}日のもの)"]
        if not data["done"]:
            lines.append("なし")
        for task in data["done"]:
            due = task["due"]
            lines.append(f"・{task['name']}")
            lines.append(f"　期限 {due:%m/%d}({WEEKDAYS[due.weekday()]}) {due:%H:%M}  {task['course']}")

    chunks, current = [], ""
    for line in lines:
        if len(current) + len(line) + 1 > DISCORD_LIMIT:
            chunks.append(current)
            current = ""
        current += line + "\n"
    chunks.append(current)
    return chunks


def settings() -> dict:
    return {
        "base": os.environ.get("LMS_BASE", "").rstrip("/"),
        "token": os.environ.get("LMS_TOKEN", ""),
        "past_days": int(os.environ.get("WORKLIST_PAST_DAYS", "14")),
        "future_days": int(os.environ.get("WORKLIST_FUTURE_DAYS", "30")),
        "excludes": [w.strip() for w in os.environ.get("EXCLUDE_KEYWORDS", "").split(",")],
    }


def build_reply(show: str = "both") -> list[str]:
    s = settings()
    data = fetch_worklist(s["base"], s["token"], s["past_days"], s["future_days"], s["excludes"])
    return format_worklist(data, s["past_days"], s["future_days"], show)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    load_env(Path(__file__).with_name(".env"))
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    print("\n".join(build_reply(mode)))
