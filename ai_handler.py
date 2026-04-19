import json
import logging
import os
import re
import anthropic
import config

logger = logging.getLogger(__name__)

VALID_STATUSES = ["素材お渡し済", "編集中", "初稿提出", "修正中", "FIX", "着手不可", "日程調整"]
VALID_EDITOR_STATUSES = {"素材お渡し済", "日程調整"}


def load_template(filename: str) -> str:
    path = os.path.join("templates", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def determine_status(
    messages: list[str], video_number: int | str
) -> tuple[str | None, str | None]:
    """
    【動画管理チャンネル用】
    Slackスレッドのメッセージ群から、ロング・ショート動画のステータスをClaudeで判定する。
    出力形式はtemplates/status_prompt.txt で定義。
    返り値: (long_video_status, short_video_status) ※判断不能はNone
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    messages_text = "\n".join(
        [f"[メッセージ{i + 1}] {msg}" for i, msg in enumerate(messages) if msg.strip()]
    )

    user_content = f"""以下は動画No.{video_number} に関するSlackのスレッドメッセージです。

--- メッセージ履歴 ---
{messages_text}
----------------------

ロング動画とショート動画それぞれの現在のステータスを判定してください。"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            system=load_template("status_prompt.txt"),
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()
        logger.debug(f"AI応答 (動画{video_number}): {text}")

        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            logger.warning(f"AIの応答からJSONを抽出できませんでした: {text}")
            return None, None

        result = json.loads(json_match.group())
        long_status = result.get("long_video_status")
        short_status = result.get("short_video_status")

        # 有効なステータス値のみ採用（null・無効値はNoneに変換）
        if long_status not in VALID_STATUSES:
            long_status = None
        if short_status not in VALID_STATUSES:
            short_status = None

        logger.info(
            f"動画{video_number} ステータス判定: ロング={long_status}, ショート={short_status}"
            f" / 理由: {result.get('reasoning', '')}"
        )
        return long_status, short_status

    except json.JSONDecodeError as e:
        logger.error(f"AIの応答のJSONパースに失敗: {e}")
        return None, None
    except Exception as e:
        logger.error(f"ステータス判定中にエラー: {e}", exc_info=True)
        return None, None


def determine_editor_channel_status(messages: list[str]) -> dict[str, str]:
    """
    【編集者チャンネル用】
    会話履歴全体から各動画の状況をClaudeで判定する。
    出力形式はtemplates/editor_channel_prompt.txt で定義。
    返り値: {動画No.: ステータス}  例: {"79": "日程調整", "80": "素材お渡し済"}
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    messages_text = "\n".join(
        [f"[{i + 1}] {msg}" for i, msg in enumerate(messages) if msg.strip()]
    )

    user_content = f"""以下はSlackの編集者チャンネルのメッセージ履歴です（古い順）。

--- メッセージ履歴 ---
{messages_text}
----------------------

各動画のステータスを判定してください。"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            system=load_template("editor_channel_prompt.txt"),
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()
        logger.debug(f"AI応答（編集者チャンネル）: {text}")

        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            logger.warning(f"AIの応答からJSONを抽出できませんでした: {text}")
            return {}

        result = json.loads(json_match.group())
        videos = result.get("videos", [])

        status_map: dict[str, str] = {}
        for v in videos:
            num = str(v.get("video_number", "")).strip()
            status = v.get("status", "")
            reasoning = v.get("reasoning", "")
            if num and status in VALID_EDITOR_STATUSES:
                status_map[num] = status
                logger.info(f"動画No.{num} → {status} / 理由: {reasoning}")
            elif num and status:
                logger.warning(f"動画No.{num}: 無効なステータス '{status}' は無視します")

        return status_map

    except json.JSONDecodeError as e:
        logger.error(f"AIの応答のJSONパースに失敗: {e}")
        return {}
    except Exception as e:
        logger.error(f"編集者チャンネルのステータス判定中にエラー: {e}", exc_info=True)
        return {}
