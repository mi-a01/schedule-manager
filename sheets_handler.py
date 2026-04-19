import json
import logging
import os
import requests
import gspread
from google.oauth2.service_account import Credentials
import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_credentials() -> Credentials:
    """
    Google認証情報を取得する。
    Renderなどのクラウド環境では環境変数 GOOGLE_CREDENTIALS_JSON（JSONの中身）を使用。
    ローカルでは credentials.json ファイルを使用。
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return Credentials.from_service_account_file(config.CREDENTIALS_FILE, scopes=SCOPES)


def get_sheet():
    creds = _get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.SPREADSHEET_ID)
    return spreadsheet.worksheet(config.SHEET_NAME)


def get_col_index_1based(headers: list[str], keyword: str, exclude: str = "") -> int | None:
    """
    ヘッダー行からキーワードを含む列のインデックス（1始まり）を返す。
    exclude が指定されている場合、その文字列を含む列はスキップする。
    """
    for i, h in enumerate(headers):
        if keyword in h:
            if exclude and exclude in h:
                continue
            return i + 1  # gspread は 1始まり
    return None


def update_video_status(video_number: int | str, long_status: str | None, short_status: str | None) -> bool:
    """
    動画番号（A列）に対応する行の ロング動画・ショート動画 のステータスを更新する。
    変更がある列のみ更新する。
    """
    sheet = get_sheet()
    headers = sheet.row_values(1)
    all_values = sheet.get_all_values()

    # A列で動画番号を検索
    target_row = None
    for i, row in enumerate(all_values):
        if row and str(row[0]).strip() == str(video_number).strip():
            target_row = i + 1  # 1始まり
            break

    if target_row is None:
        logger.warning(f"動画番号 {video_number} がスプレッドシートに見つかりませんでした")
        return False

    long_col = get_col_index_1based(headers, "ロング動画")
    short_col = get_col_index_1based(headers, "ショート動画")

    if long_status and long_col:
        sheet.update_cell(target_row, long_col, long_status)
        logger.info(f"動画{video_number} ロング動画ステータス更新: {long_status}")

    if short_status and short_col:
        sheet.update_cell(target_row, short_col, short_status)
        logger.info(f"動画{video_number} ショート動画ステータス更新: {short_status}")

    # 更新後に両方FIXになっていたらGASのsyncAndTransferVideosをトリガー
    _trigger_gas_if_both_fix(sheet, all_values, target_row, long_col, short_col,
                              long_status, short_status, video_number)
    return True


def _trigger_gas_if_both_fix(sheet, all_values, target_row, long_col, short_col,
                               new_long, new_short, video_number) -> None:
    """
    更新後の行でロング動画・ショート動画が両方FIXになっている場合、
    GASのsyncAndTransferVideosをHTTPで呼び出す。
    GAS_SYNC_URL が設定されていない場合は何もしない。
    """
    gas_url = os.getenv("GAS_SYNC_URL", "")
    if not gas_url:
        return

    row_data = all_values[target_row - 1] if target_row - 1 < len(all_values) else []

    # 更新後の値（新しいステータス優先、なければ既存値を参照）
    long_val  = new_long  if new_long  else (str(row_data[(long_col or 1) - 1]).strip()  if row_data else "")
    short_val = new_short if new_short else (str(row_data[(short_col or 1) - 1]).strip() if row_data else "")

    if long_val == "FIX" and short_val == "FIX":
        try:
            resp = requests.post(gas_url, timeout=15)
            logger.info(f"動画{video_number}: 両方FIX → GAS sync triggered (status={resp.status_code})")
        except Exception as e:
            logger.error(f"動画{video_number}: GAS sync trigger 失敗: {e}")


def get_videos_needing_schedule() -> list[dict]:
    """
    日程調整が必要な動画を抽出する。
    条件:
      - 編集者が入力済み
      - 「Slack送信済」列が空欄（送信済みはスキップ）
    """
    sheet = get_sheet()
    headers = sheet.row_values(1)
    all_values = sheet.get_all_values()

    # 列インデックス（0始まり）
    editor_col = (get_col_index_1based(headers, "編集者", exclude="初稿日") or 7) - 1
    draft_col  = (get_col_index_1based(headers, "初稿日", exclude="サムネ") or 10) - 1
    sent_col_1based = get_col_index_1based(headers, "送信済")
    sent_col = (sent_col_1based - 1) if sent_col_1based else None

    results = []
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) <= max(editor_col, draft_col):
            continue

        video_number  = str(row[0]).strip()
        editor        = str(row[editor_col]).strip() if editor_col < len(row) else ""
        draft_date    = str(row[draft_col]).strip()  if draft_col  < len(row) else ""
        already_sent  = str(row[sent_col]).strip()   if sent_col is not None and sent_col < len(row) else ""

        # 編集者あり & 未送信の行を抽出
        if video_number and editor and not already_sent:
            results.append({
                "row": i,
                "video_number": video_number,
                "editor": editor,
                "first_draft_date": draft_date,
            })

    return results


def mark_schedule_sent(row: int) -> None:
    """
    「送信済」列に送信日時を書き込む（重複送信防止）。
    スプシに「送信済」列がない場合は何もしない。
    """
    sheet = get_sheet()
    headers = sheet.row_values(1)
    sent_col = get_col_index_1based(headers, "送信済")
    if not sent_col:
        logger.warning("「送信済」列がスプレッドシートに見つかりません。スプシに列を追加してください。")
        return
    sheet.update_cell(row, sent_col, "済")
    logger.info(f"行{row} Slack送信済みに「済」を記録")
