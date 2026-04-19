import logging
import os
import re
from datetime import datetime, timedelta
from sheets_handler import get_videos_needing_schedule, mark_schedule_sent

logger = logging.getLogger(__name__)


def load_schedule_template() -> str:
    """
    日程調整メッセージの定型文テンプレートを読み込む。
    templates/schedule_message.txt を編集することで文面を変更できる。
    """
    path = os.path.join("templates", "schedule_message.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_all_channels() -> tuple[dict[str, str], list[str]]:
    """
    editor_channels.txt から全チャンネル情報を読み込む。
    返り値: (editor_channels dict, management_channel_ids list)
      - editor_channels: {編集者名: チャンネルID}
      - management_channel_ids: 動画管理チャンネルIDのリスト
    """
    editor_channels: dict[str, str] = {}
    management_channel_ids: list[str] = []

    path = "editor_channels.txt"
    if not os.path.exists(path):
        logger.warning("editor_channels.txt が見つかりません")
        return editor_channels, management_channel_ids

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[management]"):
                # 管理チャンネル: "[management] 名前=チャンネルID"
                parts = line[len("[management]"):].strip().split("=", 1)
                if len(parts) == 2:
                    ch_id = parts[1].strip()
                    if ch_id:
                        management_channel_ids.append(ch_id)
            elif "=" in line:
                # 編集者チャンネル: "編集者名=チャンネルID"
                parts = line.split("=", 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    ch_id = parts[1].strip()
                    if name and ch_id:
                        editor_channels[name] = ch_id

    return editor_channels, management_channel_ids


def load_editor_channels() -> dict[str, str]:
    """
    editor_channels.txt から 編集者名 → SlackチャンネルID のマッピングを読み込む。
    フォーマット: 編集者名=チャンネルID (例: 宮崎=C0APFS4EK7U)
    """
    path = "editor_channels.txt"
    mapping: dict[str, str] = {}
    if not os.path.exists(path):
        logger.warning("editor_channels.txt が見つかりません")
        return mapping

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("=", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                channel_id = parts[1].strip()
                if name and channel_id and not channel_id.startswith("C") is False:
                    mapping[name] = channel_id

    return mapping


def find_channel_by_name(client, editor_name: str) -> str | None:
    """
    「{編集者名}さん」という名前のSlackチャンネルを自動検索する。
    editor_channels.txt に登録がない場合のフォールバック。
    """
    target_name = f"{editor_name}さん"
    try:
        cursor = None
        while True:
            kwargs = {"types": "public_channel,private_channel", "limit": 200, "exclude_archived": True}
            if cursor:
                kwargs["cursor"] = cursor
            response = client.conversations_list(**kwargs)
            for ch in response.get("channels", []):
                if ch.get("name") == target_name or ch.get("name_normalized") == target_name:
                    logger.info(f"チャンネル自動検出: {editor_name} → #{target_name} ({ch['id']})")
                    return ch["id"]
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:
        logger.error(f"チャンネル自動検索エラー: {e}")
    return None


def get_editor_channel(client, editor: str, editor_channels: dict[str, str]) -> str | None:
    """
    編集者のチャンネルIDを取得する。
    1. editor_channels.txt の登録を優先
    2. なければ「{編集者名}さん」チャンネルを自動検索
    """
    # txtファイルに登録済みで CXXXXXXXXX でないもの
    channel_id = editor_channels.get(editor, "")
    if channel_id and not channel_id.startswith("CXXXXXXXXX") and channel_id != "CXXXXXXXXX":
        return channel_id

    # 自動検索
    logger.info(f"{editor} のチャンネルが未登録のため自動検索します")
    return find_channel_by_name(client, editor)


def parse_draft_date(date_str: str) -> datetime | None:
    """
    スプシの初稿日文字列（例: "4/30(木)", "1/25"）を datetime に変換する。
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
    日程調整が必要な動画を抽出し、各編集者のチャンネルにメッセージを送信する。
    返り値: 処理結果のリスト
    """
    videos = get_videos_needing_schedule()
    editor_channels = load_editor_channels()
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

        # 送信先チャンネルを取得
        channel_id = get_editor_channel(client, editor, editor_channels)
        if not channel_id:
            logger.warning(f"編集者 '{editor}' のチャンネルが見つかりません（editor_channels.txt に登録するか、'{editor}さん' チャンネルを作成してください）")
            results.append({
                "video_number": video_number,
                "editor": editor,
                "status": "error",
                "message": f"チャンネルが見つかりません: {editor}",
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

        message = template.format(
            video_number=video_number,
            draft_date=format_date_jp(draft_dt),
            draft_date_prev=format_date_jp(prev_dt),
            editor=editor,
        )

        # チャンネルにメッセージを送信
        try:
            client.chat_postMessage(
                channel=channel_id,
                text=message,
            )
            logger.info(f"動画{video_number} の日程調整メッセージを {editor} さんのチャンネル({channel_id})に送信しました")
            mark_schedule_sent(video["row"])
            results.append({
                "video_number": video_number,
                "editor": editor,
                "channel_id": channel_id,
                "status": "sent",
            })

        except Exception as e:
            logger.error(f"動画{video_number} のメッセージ送信に失敗 ({editor}, {channel_id}): {e}")
            results.append({
                "video_number": video_number,
                "editor": editor,
                "status": "error",
                "message": str(e),
            })

    return results
