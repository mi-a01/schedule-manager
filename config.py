import os
from dotenv import load_dotenv

load_dotenv()

# Slack
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")  # Basic Information > Signing Secret

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Google Sheets
SPREADSHEET_ID = "1O4ydQcTkZsvIA4STKF9ZZpTVNOXuaij_e-F7qJWxWdo"
SHEET_NAME = "進捗管理シート1.0"
CREDENTIALS_FILE = "credentials.json"  # ローカル用（Renderでは GOOGLE_CREDENTIALS_JSON を使用）

# 動画管理チャンネルIDのリスト（スレッドで進捗管理）
# editor_channels.txt の [management] 行から起動時に自動追加される
MANAGEMENT_CHANNEL_IDS = [
    ch.strip()
    for ch in os.getenv("MANAGEMENT_CHANNEL_IDS", "").split(",")
    if ch.strip()
]

# 編集者チャンネルIDのリスト（日程調整・承諾確認）
# editor_channels.txt から起動時に自動追加される
EDITOR_CHANNEL_IDS: list[str] = []

# Flask (GASからのwebhook受信用)
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-this-secret")

# スレッドから取得するメッセージ件数
MESSAGE_FETCH_COUNT = int(os.getenv("MESSAGE_FETCH_COUNT", "15"))
