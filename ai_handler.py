import json
import logging
import os
import re
import anthropic
import config

logger = logging.getLogger(__name__)

VALID_STATUSES = ["素材お渡し済", "編集中", "初稿提出", "修正中", "FIX", "着手不可"]


def load_template(filename: str) -> str:
    path = os.path.join("templates", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def determine_status(
    messages: list[str], video_number: int | str
) -> tuple[str | None, str | None]:
    """
    Slackのスレッドメッセージ群から、ロング動画・ショート動画のステータスをClaudeで判定する。
    返り値: (long_video_status, short_video_status)
    判断不能な場合は None を返す。
    """
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system_prompt = load_template("status_prompt.txt")

    messages_text = "\n".join(
        [f"[メッセージ{i + 1}] {msg}" for i, msg in enumerate(messages) if msg.strip()]
    )

    user_content = f"""以下は動画No.{video_number} に関するSlackのスレッドメッセージです。

--- メッセージ履歴 ---
{messages_text}
----------------------

ロング動画とショート動画それぞれの現在のステータスを判定してください。
以下のJSON形式のみで回答してください（他のテキストは不要です）:

{{
  "long_video_status": "ステータス名 or null",
  "short_video_status": "ステータス名 or null",
  "reasoning": "判断理由（簡潔に）"
}}

ステータスの選択肢: {", ".join(VALID_STATUSES)}
判断できない・情報が不十分な場合は null を入れてください。"""

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()
        logger.debug(f"AI応答 (動画{video_number}): {text}")

        # JSONを抽出してパース
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            logger.warning(f"AIの応答からJSONを抽出できませんでした: {text}")
            return None, None

        result = json.loads(json_match.group())

        long_status = result.get("long_video_status")
        short_status = result.get("short_video_status")

        # 有効なステータス値のみ採用（nullや無効値は None に変換）
        if long_status not in VALID_STATUSES:
            long_status = None
        if short_status not in VALID_STATUSES:
            short_status = None

        logger.info(
            f"動画{video_number} ステータス判定: ロング={long_status}, ショート={short_status} / 理由: {result.get('reasoning', '')}"
        )
        return long_status, short_status

    except json.JSONDecodeError as e:
        logger.error(f"AIの応答のJSONパースに失敗: {e}")
        return None, None
    except Exception as e:
        logger.error(f"ステータス判定中にエラー: {e}", exc_info=True)
        return None, None
