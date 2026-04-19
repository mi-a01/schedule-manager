import logging
import re
from slack_bolt import App
from ai_handler import determine_status, determine_schedule_confirmed
from sheets_handler import update_video_status
import config

logger = logging.getLogger(__name__)


def extract_video_number(text: str) -> str | None:
    """メッセージテキストから動画番号を抽出する"""
    patterns = [
        r'No[.\s]*(\d+)',
        r'NO[.\s]*(\d+)',
        r'no[.\s]*(\d+)',
        r'動画\s*No[.\s]*(\d+)',
        r'動画番号\s*(\d+)',
        r'#(\d+)',
        r'^(\d+)[^\d]',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1)
    return None


def fetch_thread_messages(client, channel_id: str, thread_ts: str) -> list[str]:
    """スレッドのメッセージ履歴を取得（古い順）"""
    response = client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        limit=config.MESSAGE_FETCH_COUNT,
    )
    messages = response.get("messages", [])
    return [m.get("text", "") for m in messages if m.get("text")]


def fetch_channel_history(client, channel_id: str) -> list[str]:
    """チャンネルの最近のメッセージ履歴を取得（古い順）"""
    response = client.conversations_history(
        channel=channel_id,
        limit=config.MESSAGE_FETCH_COUNT,
    )
    messages = list(reversed(response.get("messages", [])))
    return [m.get("text", "") for m in messages if m.get("text")]


def handle_management_channel(event, client):
    """
    【動画管理チャンネル】スレッドごとに動画を管理。
    スレッド内のメッセージ履歴からロング/ショート動画のステータスを判定してスプシを更新。
    """
    channel_id = event.get("channel", "")
    thread_ts = event.get("thread_ts")
    message_ts = event.get("ts", "")

    root_ts = thread_ts if thread_ts else message_ts
    messages = fetch_thread_messages(client, channel_id, root_ts)

    if not messages:
        return

    first_message = messages[0]
    video_number = extract_video_number(first_message)
    if not video_number:
        logger.info(f"[管理CH] 動画番号が見つかりません: {first_message[:80]}")
        return

    logger.info(f"[管理CH] 動画No.{video_number} のステータス判定を開始")
    long_status, short_status = determine_status(messages, video_number)

    if long_status is None and short_status is None:
        logger.info(f"[管理CH] 動画{video_number}: ステータス判定不能のためスキップ")
        return

    success = update_video_status(video_number, long_status, short_status)
    if not success:
        logger.warning(f"[管理CH] 動画{video_number}: スプレッドシートの更新に失敗")


def handle_editor_channel(event, client):
    """
    【編集者チャンネル（〇〇さんチャンネル）】スレッド管理なし。
    チャンネルの会話履歴全体から、日程調整が承諾された動画を判定し
    ステータスを「素材お渡し済」に更新する。
    """
    channel_id = event.get("channel", "")

    messages = fetch_channel_history(client, channel_id)
    if not messages:
        return

    logger.info(f"[編集者CH] {channel_id} の承諾確認を開始 ({len(messages)}件のメッセージ)")
    confirmed_video_numbers = determine_schedule_confirmed(messages)

    if not confirmed_video_numbers:
        logger.info(f"[編集者CH] 承諾確認された動画なし")
        return

    for video_number in confirmed_video_numbers:
        logger.info(f"[編集者CH] 動画No.{video_number} が承諾 → ステータスを「素材お渡し済」に更新")
        success = update_video_status(video_number, long_status="素材お渡し済", short_status="素材お渡し済")
        if not success:
            logger.warning(f"[編集者CH] 動画{video_number}: スプレッドシートの更新に失敗")


def register_handlers(app: App):

    @app.event("message")
    def handle_message(event, client, logger_arg):
        # ボットメッセージや編集・削除イベントは無視
        if event.get("bot_id") or event.get("subtype") in ("message_changed", "message_deleted"):
            return

        channel_id = event.get("channel", "")

        try:
            if channel_id in config.EDITOR_CHANNEL_IDS:
                # ① 編集者チャンネル: 会話全体から承諾確認 → 素材お渡し済
                handle_editor_channel(event, client)

            elif channel_id in config.MANAGEMENT_CHANNEL_IDS:
                # ② 動画管理チャンネル: スレッドからステータス判定
                handle_management_channel(event, client)

        except Exception as e:
            logger.error(f"メッセージ処理中にエラー (channel={channel_id}): {e}", exc_info=True)
