import logging
import os
import re
from datetime import datetime, timedelta
from sheets_handler import get_videos_needing_schedule, mark_schedule_sent

logger = logging.getLogger(__name__)


def load_schedule_template() -> str:
    """
    日程調整DMの定型文テンプレートを読み込む。
    templates/schedule_message.txt を編集することで文面を変更できる。
    """
    path = os.path.join("templates", "schedule_message.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_slack_users() -> dict[str, str]:
    """
    slack_users.txt から 編集者名 → Slack ユーザーID のマッピングを読み込む。
    フォーマット: 名前=SlackユーザーID (例: 玉木=U01234567)
    """
    path = "slack_users.txt"
    mapping: dict[str, str] = {}
    if not os.path.exists(path):
        logger.warning("slack_users.txt が見つかりません")
        return mapping

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("=", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                user_id = parts[1].strip()
                if name and user_id:
                    mapping[name] = user_id

    return mapping


def parse_draft_date(date_str: str) -> datetime | None:
    """
    スプシの初稿日文字列（例: "1/25(日)", "1/25"）を datetime に変換する。
    年は現在年を基準に、過去日付なら翌年と判断。
    """
    if not date_str:
        return None

    match = re.search(r'(\d{1,2})/(\d{1,2})', date_str)
    if not match:
        return None

    month = int(match.group(1))
    day = int(match.group(2))
    now = datetime.now()

    try:
        dt = datetime(now.year, month, day)
        # 既に2日以上過去なら翌年とみなす
        if dt < now - timedelta(days=2):
            dt = datetime(now.year + 1, month, day)
        return dt
    except ValueError:
        logger.warning(f"日付の変換に失敗: {date_str}")
        return None


def format_date_jp(dt: datetime) -> str:
    """datetime を日本語表記 "M/D(曜)" にフォーマットする"""
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{dt.month}/{dt.day}({weekdays[dt.weekday()]})"


def process_schedule_adjustment(client) -> list[dict]:
    """
    日程調整が必要な動画を抽出し、各編集者にSlack DMを送信する。
    返り値: 処理結果のリスト
    """
    videos = get_videos_needing_schedule()
    slack_users = load_slack_users()
    template = load_schedule_template()
    results = []

    if not videos:
        logger.info("日程調整が必要な動画はありませんでした")
        return results

    logger.info(f"日程調整対象の動画: {len(videos)}件")

    for video in videos:
        editor = video["editor"]
        video_number = video["video_number"]
        draft_date_str = video["first_draft_date"]

        # Slack ユーザーID を取得
        user_id = slack_users.get(editor)
        if not user_id:
            logger.warning(f"編集者 '{editor}' の Slack ユーザーID が slack_users.txt に登録されていません")
            results.append({
                "video_number": video_number,
                "editor": editor,
                "status": "error",
                "message": f"Slack ユーザーID 未登録: {editor}",
            })
            continue

        # 初稿日をパース
        draft_dt = parse_draft_date(draft_date_str)
        if not draft_dt:
            logger.warning(f"動画{video_number} の初稿日をパースできませんでした: '{draft_date_str}'")
            results.append({
                "video_number": video_number,
                "editor": editor,
                "status": "error",
                "message": f"初稿日のパース失敗: {draft_date_str}",
            })
            continue

        prev_dt = draft_dt - timedelta(days=1)

        # テンプレートに値を埋め込む
        message = template.format(
            video_number=video_number,
            draft_date=format_date_jp(draft_dt),
            draft_date_prev=format_date_jp(prev_dt),
            editor=editor,
        )

        # DM を送信
        try:
            dm_response = client.conversations_open(users=user_id)
            dm_channel_id = dm_response["channel"]["id"]

            client.chat_postMessage(
                channel=dm_channel_id,
                text=message,
            )

            logger.info(f"動画{video_number} の日程調整DMを {editor} さんに送信しました")
            # 送信済みをスプシに記録（重複送信防止）
            mark_schedule_sent(video["row"])
            results.append({
                "video_number": video_number,
                "editor": editor,
                "status": "sent",
            })

        except Exception as e:
            logger.error(f"動画{video_number} のDM送信に失敗 ({editor}): {e}")
            results.append({
                "video_number": video_number,
                "editor": editor,
                "status": "error",
                "message": str(e),
            })

    return results
