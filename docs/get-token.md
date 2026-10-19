# Moodleのトークンの取得

LMSのAPIを呼ぶための鍵(トークン)を取得する方法です。パスワードをファイルやコードに保存せず、トークンだけを使います。

## 先に確認すること

- 大学がモバイルアプリ用のAPIを許可している必要があります。許可されていないと、取得時に `Invalid service` などのエラーが返ります。この場合、このツールは使えません。
- 大学の情報システム利用規程に、自動アクセスや認証情報の取り扱いについての記載がないか確認してください。
- ログインにGoogleや学内SSOを使っている大学では、パスワードによる取得が使えないことがあります。その場合は、LMSの「ユーザメニュー → 設定 → ユーザアカウント → セキュリティキー」に「Moodle mobile web service」があるか探してください。ない大学も多くあります。

## 方法1: get_token.py を使う(推奨)

Pythonが使える場合です。`python/` フォルダで実行します。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate  /  Linux・macOS: source .venv/bin/activate
pip install -r requirements.txt
python get_token.py https://lms.example.ac.jp
```

ユーザー名とパスワードを聞かれます。パスワードは画面に表示されず、履歴にも残りません。成功すると、トークンだけが表示されます。

## 方法2: curl を使う(Linux・macOS・Git Bash)

```bash
read -p "LMS username: " U; read -s -p "LMS password: " P; echo
curl -s "https://lms.example.ac.jp/login/token.php" \
  --data-urlencode "username=$U" --data-urlencode "password=$P" -d "service=moodle_mobile_app"
unset P
```

## 方法3: PowerShell を使う(Windows)

```powershell
$u = Read-Host "LMS username"
$p = Read-Host "LMS password" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))
Invoke-RestMethod -Method Post -Uri "https://lms.example.ac.jp/login/token.php" -Body @{ username = $u; password = $plain; service = "moodle_mobile_app" } | ConvertTo-Json
$plain = $null
```

## 結果の見方

- `{"token":"..."}` が返れば成功です。使うのは `token` だけです。
- `privatetoken` も返ることがありますが、このツールでは使いません。保存せず、どこにも貼らないでください。
- `Invalid login` が返る場合は、ユーザー名かパスワードの誤りか、SSOでパスワード取得が使えない可能性があります。
- `Invalid service` が返る場合は、大学がモバイル用APIを許可していません。

## 取り扱いの注意

- トークンは、あなたのアカウントでAPIを呼べる鍵です。チャット、Issue、スクリーンショットに貼らないでください。
- 漏れた疑いがあれば、LMSのセキュリティキーの画面で再発行するか、大学の担当窓口に連絡してください。
- トークンは `.env`(Python版)かスクリプト プロパティ(GAS版)にだけ入れます。
