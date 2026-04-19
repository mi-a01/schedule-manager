/**
 * Google Apps Script - 日程調整送信ボタンのトリガー
 *
 * ── セットアップ手順 ──────────────────────────────────────────────────
 * 1. スプレッドシートのメニュー「拡張機能」→「Apps Script」を開く
 * 2. このファイルの内容を全選択して貼り付けて保存（Ctrl+S）
 * 3. 「実行」→「sendScheduleAdjustment」を一度実行し、権限を付与する
 * 4. スプレッドシートに戻り「挿入」→「図形描画」でボタンを作成
 * 5. ボタンを右クリック →「スクリプトを割り当て」→「sendScheduleAdjustment」を入力
 * ─────────────────────────────────────────────────────────────────────
 */

// ▼ここを確認・編集してください▼
var SERVER_URL = "https://schedule-manager-50pu.onrender.com/trigger-schedule";
var WEBHOOK_SECRET = "mia-schedule-2024-xK9p";
// ▲ここまで▲

function sendScheduleAdjustment() {
  var ui = SpreadsheetApp.getUi();

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
      ui.alert("認証エラー", "WEBHOOK_SECRET が一致しません。GASとRenderの環境変数を確認してください。", ui.ButtonSet.OK);
    } else {
      ui.alert("エラー", "サーバーエラー (HTTP " + code + "):\n" + body, ui.ButtonSet.OK);
    }

  } catch (e) {
    ui.alert(
      "接続エラー",
      "Renderサーバーに接続できませんでした。\n\n" +
      "確認事項:\n" +
      "・RenderのサービスがLive状態か（render.com で確認）\n" +
      "・SERVER_URL が正しいか\n\n" +
      "エラー詳細: " + e.message,
      ui.ButtonSet.OK
    );
  }
}
