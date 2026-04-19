/**
 * Google Apps Script - 日程調整送信ボタンのトリガー
 *
 * ── セットアップ手順 ──────────────────────────────────────────────────
 * 1. スプレッドシートのメニュー「拡張機能」→「Apps Script」を開く
 * 2. このファイルの内容を貼り付けて保存（Ctrl+S）
 * 3. SERVER_URL と WEBHOOK_SECRET を設定する（下記参照）
 * 4. 「実行」→「sendScheduleAdjustment」を一度実行し、権限を付与する
 * 5. スプレッドシートに戻り「挿入」→「図形描画」でボタンを作成
 * 6. ボタンを右クリック →「スクリプトを割り当て」→「sendScheduleAdjustment」を入力
 *
 * ── SERVER_URL の設定 ─────────────────────────────────────────────────
 * Pythonアプリをローカルで動かしている場合は ngrok で外部公開が必要です。
 *   1. ngrok をインストール: https://ngrok.com/download
 *   2. コマンドプロンプトで: ngrok http 5000
 *   3. 表示された "Forwarding" の https URL をコピー
 *   4. SERVER_URL に貼り付ける（例: "https://xxxx.ngrok-free.app/trigger-schedule"）
 *
 * ── WEBHOOK_SECRET ───────────────────────────────────────────────────
 * .env の WEBHOOK_SECRET と同じ値にしてください。
 * ─────────────────────────────────────────────────────────────────────
 */

// ▼ここを編集してください▼
var SERVER_URL = "https://5e3a-240b-c010-4c3-a90-543b-52f9-2d8-ea8.ngrok-free.app/trigger-schedule";
var WEBHOOK_SECRET = "change-this-secret"; // .env の WEBHOOK_SECRET と合わせる
// ▲ここまで▲

function sendScheduleAdjustment() {
  var ui = SpreadsheetApp.getUi();

  // 確認ダイアログ
  var confirm = ui.alert(
    "日程調整DM送信",
    "編集者が決まりロング/ショート動画が未設定の動画に、日程調整DMを送信します。よろしいですか？",
    ui.ButtonSet.YES_NO
  );
  if (confirm !== ui.Button.YES) return;

  try {
    var options = {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify({ secret: WEBHOOK_SECRET }),
      muteHttpExceptions: true,
    };

    var response = UrlFetchApp.fetch(SERVER_URL, options);
    var code = response.getResponseCode();
    var body = response.getContentText();

    if (code === 200) {
      var result = JSON.parse(body);
      var sentCount = (result.sent || []).length;
      var errors = result.errors || [];

      var msg = sentCount + " 件の日程調整DMを送信しました。";
      if (errors.length > 0) {
        msg += "\n\n⚠️ エラーが発生した動画:\n";
        errors.forEach(function (e) {
          msg += "  No." + e.video_number + " (" + e.editor + "): " + e.message + "\n";
        });
      }
      ui.alert("送信完了", msg, ui.ButtonSet.OK);

    } else if (code === 401) {
      ui.alert("認証エラー", "WEBHOOK_SECRET が一致しません。GASとPythonアプリの設定を確認してください。", ui.ButtonSet.OK);
    } else {
      ui.alert("エラー", "サーバーエラー (HTTP " + code + "):\n" + body, ui.ButtonSet.OK);
    }

  } catch (e) {
    ui.alert(
      "接続エラー",
      "Pythonアプリに接続できませんでした。\n\n" +
      "確認事項:\n" +
      "・Pythonアプリ（main.py）が起動しているか\n" +
      "・ngrok が起動しているか\n" +
      "・SERVER_URL が正しいか\n\n" +
      "エラー詳細: " + e.message,
      ui.ButtonSet.OK
    );
  }
}
