"""MoodleのAPIトークンを取得して表示する。

    python get_token.py https://lms.example.ac.jp

ユーザー名とパスワードは対話入力で、画面にもシェルの履歴にも残らない。
表示するのは token のみ。privatetoken は取得しても表示しない。
"""
import getpass
import sys

import requests


def main() -> int:
    if len(sys.argv) != 2:
        print("使い方: python get_token.py https://lms.example.ac.jp", file=sys.stderr)
        return 2
    base = sys.argv[1].rstrip("/")
    username = input("LMS username: ")
    password = getpass.getpass("LMS password: ")
    response = requests.post(
        f"{base}/login/token.php",
        data={"username": username, "password": password, "service": "moodle_mobile_app"},
        timeout=30,
    )
    data = response.json()
    if "token" not in data:
        print(f"取得できませんでした: {data.get('error') or data}", file=sys.stderr)
        return 1
    print(data["token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
