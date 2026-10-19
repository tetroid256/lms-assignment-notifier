"""LMS(Moodle)の未提出課題を取得し、Discord Webhookへ送る。

使い方:
    python notify.py --check     # トークンが有効か確認(送信しない)
    python notify.py --dry-run   # 本文を表示するだけ(送信しない)
    python notify.py             # Discordへ送信
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = "月火水木金土日"
DISCORD_LIMIT = 1900


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def call_api(base: str, token: str, function: str, **params):
    response = requests.post(
        f"{base}/webservice/rest/server.php",
        data={"wstoken": token, "wsfunction": function, "moodlewsrestformat": "json", **params},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and "exception" in data:
        raise RuntimeError(f"{data.get('errorcode')}: {data.get('message')}")
    return data


def fetch_tasks(
    base: str, token: str, days: int, excludes: list[str], only_non_assign: bool = False
) -> list[dict]:
    now = int(time.time())
    data = call_api(
        base,
        token,
        "core_calendar_get_action_events_by_timesort",
        timesortfrom=now,
        timesortto=now + days * 86400,
        limitnum=50,
    )
    tasks = []
    for event in data.get("events", []):
        action = event.get("action") or {}
        if not action.get("actionable", True):
            continue
        if only_non_assign and event.get("modulename") == "assign":
            continue
        name = clean_name(event.get("name", ""))
        if any(word and word in name for word in excludes):
            continue
        tasks.append(
            {
                "name": name,
                "due": datetime.fromtimestamp(event["timesort"], JST),
                "course": (event.get("course") or {}).get("fullname", ""),
                "url": event.get("url", ""),
            }
        )
    return sorted(tasks, key=lambda t: t["due"])


def dump_everything(base: str, token: str) -> dict:
    """取得できる範囲を全部集める。権限のないAPIはエラー内容を残して続行する。"""
    result: dict = {}

    def attempt(label: str, function: str, **params):
        try:
            result[label] = call_api(base, token, function, **params)
        except Exception as error:
            result[label] = {"error": str(error)}

    attempt("site_info", "core_webservice_get_site_info")
    site = result["site_info"] if "error" not in result["site_info"] else {}
    userid = site.get("userid")

    courses = []
    if userid:
        attempt("courses", "core_enrol_get_users_courses", userid=userid)
        if isinstance(result["courses"], list):
            courses = result["courses"]

    # 過去も未来も、期限の絞り込みなしで全ページ取得する(aftereventidで続きを読む)
    pages, after = [], 0
    while True:
        params = {"timesortfrom": 0, "limitnum": 50}
        if after:
            params["aftereventid"] = after
        try:
            page = call_api(base, token, "core_calendar_get_action_events_by_timesort", **params)
        except Exception as error:
            pages.append({"error": str(error)})
            break
        events = page.get("events", [])
        pages.extend(events)
        if len(events) < 50:
            break
        after = events[-1]["id"]
    result["action_events_all"] = pages

    # 提出済み・過去のものを含む通常のカレンダーイベント
    params = {
        "options[userevents]": 1,
        "options[siteevents]": 1,
        "options[timestart]": 0,
        "options[timeend]": int(time.time()) + 3 * 365 * 86400,
    }
    for i, course in enumerate(courses):
        params[f"events[courseids][{i}]"] = course["id"]
    attempt("calendar_events_all", "core_calendar_get_calendar_events", **params)

    # 参考: このトークンで呼べるAPI関数名の一覧
    result["available_functions"] = [f["name"] for f in site.get("functions", [])]
    result["site_info"].pop("functions", None)
    return result


def clean_name(name: str) -> str:
    name = re.sub(r"の(提出期限|期限|終了)$", "", name.strip())
    return name.strip("「」 ")


def build_message(tasks: list[dict], days: int) -> str:
    now = datetime.now(JST)
    header = f"{now:%m/%d}({WEEKDAYS[now.weekday()]}) 課題の通知 / {days}日以内の未提出"
    if not tasks:
        return f"{header}\n未提出の課題はありません。"
    lines = [header, ""]
    for task in tasks:
        due = task["due"]
        left = (due.date() - now.date()).days
        when = "今日" if left == 0 else "明日" if left == 1 else f"{left}日後"
        if left < 0:
            when = "期限超過"
        lines.append(f"・{task['name']}")
        lines.append(f"　{due:%m/%d}({WEEKDAYS[due.weekday()]}) {due:%H:%M} ({when})  {task['course']}")
    text = "\n".join(lines)
    return text if len(text) <= DISCORD_LIMIT else text[:DISCORD_LIMIT] + "\n…(省略)"


def post_discord(webhook: str, content: str) -> None:
    response = requests.post(webhook, json={"content": content}, timeout=30)
    response.raise_for_status()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="トークンの有効性だけ確認する")
    parser.add_argument("--dry-run", action="store_true", help="送信せず本文を表示する")
    parser.add_argument("--raw", action="store_true", help="APIが返したJSON全文を表示する")
    args = parser.parse_args()

    load_env(Path(__file__).with_name(".env"))
    base = os.environ.get("LMS_BASE", "").rstrip("/")
    token = os.environ.get("LMS_TOKEN", "")
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    days = int(os.environ.get("DAYS_AHEAD", "7"))
    excludes = [w.strip() for w in os.environ.get("EXCLUDE_KEYWORDS", "").split(",")]

    if not base or not token:
        print(".env に LMS_BASE と LMS_TOKEN を設定してください。", file=sys.stderr)
        return 2

    try:
        if args.check:
            info = call_api(base, token, "core_webservice_get_site_info")
            print(f"OK: {info.get('sitename')} / ユーザーID {info.get('userid')}")
            return 0
        if args.raw:
            print(json.dumps(dump_everything(base, token), ensure_ascii=False, indent=2))
            return 0
        message = build_message(fetch_tasks(base, token, days, excludes), days)
    except Exception as error:
        if webhook and not args.dry_run:
            post_discord(webhook, f"課題通知の取得に失敗しました: {error}")
        print(f"失敗: {error}", file=sys.stderr)
        return 1

    if args.dry_run or not webhook:
        print(message)
        if not args.dry_run:
            print("\nDISCORD_WEBHOOK_URL が未設定のため送信していません。", file=sys.stderr)
        return 0
    post_discord(webhook, message)
    print("送信しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
