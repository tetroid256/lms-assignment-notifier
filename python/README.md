# Python版

定時通知はcronで、`!worklist` コマンドはDiscord botで動かします。常時稼働のPCかサーバー(Ubuntuなど)が必要です。

## 準備

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windowsは .venv\Scripts\pip
cp .env.example .env
```

Ubuntuでvenvが作れないときは、`sudo apt install python3-venv` を入れてください。

`.env` に次の値を入れます。

| 項目 | 内容 |
|---|---|
| LMS_BASE | LMSのURL(例: https://lms.example.ac.jp) |
| LMS_TOKEN | [取得したトークン](../docs/get-token.md) |
| DISCORD_WEBHOOK_URL | 定時通知を送るWebhook URL |
| DAYS_AHEAD | 定時通知で何日先まで出すか(既定 7) |
| EXCLUDE_KEYWORDS | 名前に含まれていたら除外する語(カンマ区切り) |

Ubuntuでは `chmod 600 .env` にしてください。

## 動作確認

```bash
.venv/bin/python notify.py --check      # トークンが有効か
.venv/bin/python notify.py --dry-run    # 送信せず本文を表示
.venv/bin/python worklist.py            # 未提出と提出済みの一覧を表示
.venv/bin/python notify.py              # Discordへ送信
.venv/bin/python notify.py --raw        # APIが返す情報の全体(調査用)
```

## 毎朝の定時通知(cron)

`deploy/crontab.txt` の1行を `crontab -e` に貼り、`YOUR_USER` と場所を書き換えます。時刻はOSのタイムゾーンで動くので、`timedatectl` で `Asia/Tokyo` を確認してください。変更するときは次のコマンドです。

```bash
sudo timedatectl set-timezone Asia/Tokyo
sudo systemctl restart cron
```

## Discord bot(`!worklist`)

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリを作り、「Bot」でトークンを取得します。
2. 同じ画面で **Message Content Intent** をオンにします。
3. OAuth2のURL生成で、スコープ `bot`、権限「メッセージの閲覧・送信・履歴の閲覧」を選び、botをサーバーに招待します。
4. Discordの設定で開発者モードをオンにし、自分のアイコンを右クリックして「ユーザーIDをコピー」します。
5. `.env` に次を入れます。

| 項目 | 内容 |
|---|---|
| DISCORD_BOT_TOKEN | botのトークン(Webhook URLとは別物) |
| DISCORD_ALLOWED_USER_IDS | 応答を許可するユーザーID(カンマ区切り。必須) |
| WORKLIST_PAST_DAYS | 提出済みを何日前まで遡るか(既定 14) |
| WORKLIST_FUTURE_DAYS | 何日先まで出すか(既定 30) |

6. `.venv/bin/python bot.py` で起動し、Discordで確認します。

| コマンド | 内容 |
|---|---|
| `!worklist` | 未提出と提出済みの両方 |
| `!worklist todo` | 未提出だけ |
| `!worklist done` | 提出済みだけ |

`!workls` と `!課題` も同じ動きです。

### 常時起動(systemd)

```bash
sudo cp deploy/lms-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/lms-bot.service   # YOUR_USER とパスを書き換える
sudo systemctl daemon-reload
sudo systemctl enable --now lms-bot
journalctl -u lms-bot -f
```

`.env` を変えたら `sudo systemctl restart lms-bot` で再起動します。
