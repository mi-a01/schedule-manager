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
from schedule_handler import process_schedule_adjustment, load_editor_channels
from sheets_handler import get_videos_needing_schedule
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

# editor_channels.txt に登録されたチャンネルを監視対象に追加
# （編集者のチャンネルへの返信もステータス更新の対象にする）
_editor_channels = load_editor_channels()
for _ch_id in _editor_channels.values():
    if _ch_id and not _ch_id.startswith("CXXXXXXXXX") and _ch_id not in config.MANAGEMENT_CHANNEL_IDS:
        config.MANAGEMENT_CHANNEL_IDS.append(_ch_id)
logger.info(f"監視チャンネル: {config.MANAGEMENT_CHANNEL_IDS}")

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


@flask_app.route("/debug/schedule", methods=["GET"])
def debug_schedule():
    """
    日程調整の対象動画と、slack_users.txt の登録状況を確認するデバッグ用エンドポイント。
    ブラウザで https://schedule-manager-50pu.onrender.com/debug/schedule を開くだけで確認できる。
    動作確認後は削除してもOK。
    """
    import os
    from schedule_handler import load_slack_users

    try:
        from sheets_handler import get_sheet, get_col_index_1based
        from schedule_handler import load_slack_users

        sheet = get_sheet()
        headers = sheet.row_values(1)
        slack_users = load_slack_users()

        # 列検出状況
        editor_col = get_col_index_1based(headers, "編集者", exclude="初稿日")
        draft_col  = get_col_index_1based(headers, "初稿日", exclude="サムネ")
        long_col   = get_col_index_1based(headers, "ロング動画")
        short_col  = get_col_index_1based(headers, "ショート動画")
        sent_col   = get_col_index_1based(headers, "送信済")

        col_info = {
            "編集者列": f"{editor_col}列目 / ヘッダー名: '{headers[editor_col-1] if editor_col else 'なし'}'",
            "初稿日列": f"{draft_col}列目 / ヘッダー名: '{headers[draft_col-1] if draft_col else 'なし'}'",
            "ロング動画列": f"{long_col}列目 / ヘッダー名: '{headers[long_col-1] if long_col else '❌ 見つからない'}'",
            "ショート動画列": f"{short_col}列目 / ヘッダー名: '{headers[short_col-1] if short_col else '❌ 見つからない'}'",
            "送信済み列": f"{sent_col}列目 / ヘッダー名: '{headers[sent_col-1] if sent_col else '❌ 見つからない'}'",
            "全ヘッダー": headers,
        }

        # 対象行の検索
        videos = get_videos_needing_schedule()
        result = []
        for v in videos:
            editor = v["editor"]
            user_id = slack_users.get(editor)
            result.append({
                "video_number": v["video_number"],
                "editor": editor,
                "first_draft_date": v["first_draft_date"],
                "slack_user_id": user_id or "❌ slack_users.txt に未登録",
                "will_send": bool(user_id and not user_id.startswith("UXXXXXXXXX")),
            })

        # 最初の5行のサンプルデータ（編集者・ロング・ショートの実際の値を確認）
        all_values = sheet.get_all_values()
        sample_rows = []
        for row in all_values[1:6]:
            sample_rows.append({
                "No": row[0] if len(row) > 0 else "",
                "編集者": row[(editor_col or 7)-1] if len(row) >= (editor_col or 7) else "",
                "ロング動画": row[(long_col or 11)-1] if len(row) >= (long_col or 11) else "",
                "ショート動画": row[(short_col or 12)-1] if len(row) >= (short_col or 12) else "",
                "送信済": row[(sent_col or 99)-1] if sent_col and len(row) >= sent_col else "",
            })

        return jsonify({
            "列検出結果": col_info,
            "対象動画数": len(videos),
            "対象動画リスト": result,
            "先頭5行のサンプル": sample_rows,
        }), 200

    except Exception as e:
        logger.error(f"デバッグエンドポイントエラー: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@flask_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ローカル起動用（本番はgunicornが flask_app を直接使う）
if __name__ == "__main__":
    port = int(os.environ.get("PORT", config.FLASK_PORT))
    flask_app.run(host="0.0.0.0", port=port, debug=False)
