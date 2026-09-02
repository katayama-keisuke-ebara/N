# トラブルシューティング

---

## 起動時の問題

### `cadquery` の import に時間がかかる

`import cadquery` は OCP/OpenCascade ネイティブライブラリのロードのため約 10〜20 秒かかります。
`webapp/jobs.py` はジョブ実行ワーカープロセス内で遅延 import しているため、このコストは Web サーバー起動時ではなく
「ワーカープロセスが最初のジョブを処理するとき」に一度だけ発生します(既知の正常挙動)。

### ログインできない・セッションがすぐ切れる

- ユーザーが未作成の場合は `webapp/scripts/create_user.py` で作成してください。
- セッション有効期限は既定 8 時間です (`webapp/security.py` の `SESSION_MAX_AGE`)。
- 5 回連続でログインに失敗すると 15 分間ロックされます(`webapp/security.py` の `LoginRateLimiter`)。

### アップロードが `400 Bad Request` になる

- `.step` / `.stp` 拡張子以外、空ファイル、200MB を超えるファイル、STEP ヘッダー (`ISO-10303-21;`) を含まないファイルは拒否されます
  (`webapp/storage.py` の `validate_step_upload`)。

---

## STEP ファイルの読み込みに失敗する

**確認事項:**

1. ファイルパスに日本語・スペース・特殊文字が含まれないか確認する
2. SolidWorks から出力された `.STEP` または `.stp` 形式か確認する
3. `logs\` フォルダのログファイルでエラー詳細を確認する

---

## ログの確認

実行時エラーの詳細は `logs\` フォルダに記録されます。

```
logs\
  netsing_tool_YYYYMMDD.log
```

バグ報告の際はこのファイルを添付してください。

