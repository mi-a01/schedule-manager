/**
 * sync_trigger.js
 * 既存の syncAndTransferVideos 関数が入っているGASプロジェクトに
 * このコードを追加してください。
 *
 * ── 追加手順 ──────────────────────────────────────────────────────────
 * 1. GASエディタで既存のコードの末尾にこのファイルの内容を貼り付ける
 * 2. メニュー「デプロイ」→「新しいデプロイ」
 * 3. 種類:「ウェブアプリ」を選択
 * 4. 実行ユーザー:「自分」
 *    アクセスできるユーザー:「全員」（Pythonからのリクエストを受け取るため）
 * 5. デプロイ → 表示されたウェブアプリのURLをコピー
 * 6. RenderのGAS_SYNC_URL環境変数にそのURLを設定する
 * ─────────────────────────────────────────────────────────────────────
 */

/**
 * PythonアプリからのPOSTリクエストを受け取り、
 * syncAndTransferVideos を実行する。
 * ロング動画・ショート動画が両方FIXになったときに呼ばれる。
 */
function doPost(e) {
  try {
    syncAndTransferVideos(null); // null を渡すとonEdit判定をスキップして全行処理
    return ContentService
      .createTextOutput(JSON.stringify({ success: true }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
