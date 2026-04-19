"""
動画制作スケジュール管理アプリ

機能1: ステータス自動更新
  - Slackの管理チャンネル・DMで新着メッセージを受信
  - スレッド履歴をClaudeで分析し、ロング/ショート動画のステータスを判定
  - スプレッドシートの該当行を自動更新

機能2: 日程調整DM送信
  - GASのボタンから /trigger-schedule エンドポイントを呼び出す
  - 編集者が決まりロング/ショートが未設定の動画を抽出
  - 各編集者にSlack DMで日程調整メッセージを送信

起動:
  ローカル: python main.py
  本番:     gunicorn main:flask_app --bind 0.0.0.0:$PORT  (Renderが自動実行)
"""

import logging
import os
from flask import Flask, request, jsonify
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_handler import register_handlers
from schedule_handler import process_schedule_adjustment
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Slack Bot ────────────────────────────────────────────
slack_app = App(
    token=config.SLACK_BOT_TOKEN,
    signing_secret=config.SLACK_SIGNING_SECRET,
)
register_handlers(slack_app)
slack_handler = SlackRequestHandler(slack_app)

# ── Flask ─────────────────────────────────────────────────
flask_app = Flask(__name__)


@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    """Slack Events API のエンドポイント（Slackからのメッセージを受信）"""
    return slack_handler.handle(request)


@flask_app.route("/trigger-schedule", methods=["POST"])
def trigger_schedule():
    """GASのボタンから呼ばれるエンドポイント（日程調整DMを一括送信）"""
    data = request.get_json(silent=True)
    if not data or data.get("secret") != config.WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        results = process_schedule_adjustment(slack_app.client)
        sent = [r for r in results if r["status"] == "sent"]
        errors = [r for r in results if r["status"] == "error"]
        logger.info(f"日程調整完了: 送信={len(sent)}件, エラー={len(errors)}件")
        return jsonify({"success": True, "sent": sent, "errors": errors})
    except Exception as e:
        logger.error(f"日程調整処理中にエラー: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@flask_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ローカル起動用（本番はgunicornが flask_app を直接使う）
if __name__ == "__main__":
    port = int(os.environ.get("PORT", config.FLASK_PORT))
    flask_app.run(host="0.0.0.0", port=port, debug=False)
