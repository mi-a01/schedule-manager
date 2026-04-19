import logging
import re
from slack_bolt import App
from ai_handler import determine_status
from sheets_handler import update_video_status
import config

logger = logging.getLogger(__name__)


def extract_video_number(text: str) -> str | None:
    """
    メッセージテキストから動画番号（A列のNo.）を抽出する。
    スレッドの最初のメッセージに「No.X」「No X」「動画X」などの形式で含まれることを想定。
    """
    patterns = [
        r'No[.\s]*(\d+)',   # No.1, No 1, No1
        r'NO[.\s]*(\d+)',   # NO.1
        r'no[.\s]*(\d+)',   # no.1
        r'動画\s*No[.\s]*(\d+)',
        r'動画番号\s*(\d+)',
        r'#(\d+)',
        r'^(\d+)[^\d]',     # 行頭の数字
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1)
    return None


def fetch_thread_messages(client, channel_id: str, thread_ts: str) -> list[str]:
    """スレッドのメッセージ履歴を取得してテキストのリストを返す（古い順）"""
    response = client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        limit=config.MESSAGE_FETCH_COUNT,
    )
    messages = response.get("messages", [])
    return [m.get("text", "") for m in messages if m.get("text")]


def fetch_dm_messages(client, channel_id: str, thread_ts: str | None) -> list[str]:
    """
    DMのメッセージ履歴を取得する。
    スレッドがある場合はスレッド内メッセージ、ない場合は最近のDM履歴を取得。
    """
    if thread_ts:
        response = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=config.MESSAGE_FETCH_COUNT,
        )
        messages = response.get("messages", [])
    else:
        response = client.conversations_history(
            channel=channel_id,
            limit=config.MESSAGE_FETCH_COUNT,
        )
        # conversations_history は新しい順なので反転して古い順にする
        messages = list(reversed(response.get("messages", [])))

    return [m.get("text", "") for m in messages if m.get("text")]


def register_handlers(app: App):

    @app.event("message")
    def handle_message(event, client, logger_arg):
        """
        管理チャンネルまたはDMへの新着メッセージを受信したら:
        1. スレッド/DM履歴を取得
        2. 最初のメッセージから動画番号を抽出
        3. Claudeでステータスを判定
        4. スプレッドシートを更新
        """
        # ボットメッセージや編集イベントは無視
        if event.get("bot_id") or event.get("subtype") in ("message_changed", "message_deleted"):
            return

        channel_id = event.get("channel", "")
        channel_type = event.get("channel_type", "")  # "im" = DM
        thread_ts = event.get("thread_ts")  # スレッド返信の場合に存在
        message_ts = event.get("ts", "")

        is_dm = channel_type == "im"
        is_management_channel = channel_id in config.MANAGEMENT_CHANNEL_IDS

        if not is_dm and not is_management_channel:
            return

        try:
            if is_dm:
                messages = fetch_dm_messages(client, channel_id, thread_ts)
                # DMでは最古のメッセージ（リストの先頭）に動画番号が入っている
                first_message = messages[0] if messages else ""
            else:
                # チャンネルのスレッド
                root_ts = thread_ts if thread_ts else message_ts
                messages = fetch_thread_messages(client, channel_id, root_ts)
                first_message = messages[0] if messages else ""

            if not messages:
                logger.info("メッセージが取得できませんでした")
                return

            # 動画番号を抽出
            video_number = extract_video_number(first_message)
            if not video_number:
                logger.info(f"動画番号が見つかりませんでした。最初のメッセージ: {first_message[:80]}")
                return

            logger.info(f"動画番号 {video_number} のステータス判定を開始")

            # Claudeでステータスを判定
            long_status, short_status = determine_status(messages, video_number)

            if long_status is None and short_status is None:
                logger.info(f"動画{video_number}: ステータス判定不能のためスキップ")
                return

            # スプレッドシートを更新
            success = update_video_status(video_number, long_status, short_status)
            if not success:
                logger.warning(f"動画{video_number}: スプレッドシートの更新に失敗")

        except Exception as e:
            logger.error(f"メッセージ処理中にエラー: {e}", exc_info=True)
