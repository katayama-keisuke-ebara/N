# 断熱材部品平面化ツール (NetsingTool)

SolidWorks から出力された STEP ファイルを読み込み、断熱材部品の最大面を XY 平面へ投影して **DXF・PNG・JSON** の 3 種類の成果物を生成する Web アプリケーションです。
複数 STEP ファイル+数量(BOM)を指定すると、穴加工(内側輪郭)を考慮した NFP(No-Fit-Polygon)ベースのネスティング計算を行い、
歩留まり上位 3 件までの分布案をブラウザ上で確認・ダウンロードできます。

## 動作環境

| 項目 | 要件 |
|------|------|
| OS | Windows Server / Windows 11 64bit (社内 LAN 配置) |
| Python | 3.12 以上 |
| 主要ライブラリ | FastAPI, CadQuery, NumPy ≥ 1.26, ezdxf ≥ 1.3, matplotlib ≥ 3.9, pyclipper ≥ 1.3, shapely ≥ 2.0 |

---

## インストール (開発環境)

```cmd
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## 初期ユーザーの作成

自己登録 UI は提供していないため、管理者が事前にユーザーを作成します(対話式でパスワードを入力)。

```cmd
.venv\Scripts\python.exe -m webapp.scripts.create_user <username>
```

## 起動

```cmd
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 0.0.0.0 --port 8000
```

ブラウザで `http://<サーバー名>:8000/` にアクセスし、作成したユーザーでログインします。

**使い方:**

1. STEP ファイル(複数選択可)をアップロードし、部品ごとの数量(BOM)・定尺サイズ・材料厚み・クリアランスを入力する。
2. 「実行」で穴加工を考慮した NFP ベースのネスティング計算を実行する(ジョブとしてバックグラウンド処理され、完了までポーリングで進捗表示)。
3. 完了後、異なる配置戦略による歩留まり上位 3 件までの分布案が「案1/案2/案3」タブとして表示される。タブを切り替えると
   ネスティング配置図・部品別内訳(穴面積合計を含む)がその案に合わせて再描画される。
4. DXF / 全成果物 ZIP をダウンロードできる。

穴に他の部品が収まる場合は自動的に穴埋め配置を試みますが、これは近似ヒューリスティックであり必ず最適解になるとは限りません。

**品質レベル (展開誤差率):**

| 記号 | 面積差分率 | 説明 |
|------|-----------|------|
| A | < 1% | 高精度 |
| B | < 5% | 実用品質 |
| C | ≥ 5% | 警告あり |

## CLI (単体テスト・バッチ処理向け)

複数部品ネスティングを伴わない単一 STEP ファイルの平面化のみ、コマンドラインからも実行できます。

```cmd
.venv\Scripts\python.exe main.py path\to\part.step --output-dir output --samples 50
```

---

## 本番デプロイ手順 (社内 Windows Server への常駐配置)

社内 LAN 限定・少人数利用を前提に、Windows Server 上で `uvicorn` を Windows サービスとして常駐させる手順です。
Docker・Linux への移行は行わず、開発時に動作確認済みの Windows 環境をそのまま利用します。

### 1. 前提条件

| 項目 | 要件 |
|------|------|
| OS | Windows Server 2019/2022 (または Windows 11) |
| Python | 3.12 以上をインストール済み (`python --version` で確認) |
| ネットワーク | 社内 LAN からサーバーの IP/ポートへ到達可能であること |
| 権限 | サービス登録・ファイアウォール設定には管理者権限が必要 |

### 2. アプリの配置

```powershell
# 配置先ディレクトリへリポジトリを取得 (git 経由、または ZIP を展開)
cd D:\
git clone <リポジトリURL> NetsingTool
cd NetsingTool

# venv 作成と依存インストール
python -m venv .venv
.venv\Scripts\pip.exe install --upgrade pip
.venv\Scripts\pip.exe install -r requirements.txt
```

### 3. 初期ユーザーの作成

```powershell
.venv\Scripts\python.exe -m webapp.scripts.create_user <username>
```

利用者の人数分、上記コマンドを繰り返して事前にアカウントを作成しておきます(自己登録 UI はありません)。

### 4. シークレットキー・データベースの永続化について

初回起動時に `webapp_data\secret.key` (セッション署名鍵) と `webapp_data\app.db` (SQLite: ユーザー/ジョブ/設定) が自動生成されます。
`secret.key` を再生成するとログイン中のセッションが全て無効化されるため、**バックアップを取り、サービス再構築時も使い回してください**。

```powershell
# 定期バックアップの例 (タスクスケジューラ等で日次実行を推奨)
Copy-Item D:\NetsingTool\webapp_data\app.db "D:\Backup\app_$(Get-Date -Format yyyyMMdd).db"
```

### 5. 動作確認 (フォアグラウンド起動)

サービス化する前に、一度手動起動して動作することを確認します。

```powershell
cd D:\NetsingTool
.venv\Scripts\python.exe -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000
```

別ターミナルから `Invoke-WebRequest http://127.0.0.1:8000/login` が 200 を返すことを確認したら `Ctrl+C` で停止します。

### 6. Windows サービスとして常駐化 (NSSM を使用)

[NSSM (Non-Sucking Service Manager)](https://nssm.cc/) を使うと、任意のコマンドを Windows サービスとして登録できます。

```powershell
# NSSM のダウンロード・展開 (公式サイトから nssm.exe を取得し、PATH の通ったフォルダへ配置)
# 例: C:\tools\nssm\nssm.exe

# サービスの登録
C:\tools\nssm\nssm.exe install NetsingToolWeb "D:\NetsingTool\.venv\Scripts\python.exe" `
  "-m uvicorn webapp.main:app --host 0.0.0.0 --port 8000"

# 作業ディレクトリ (相対パス解決・webapp_data 配置先の基準) を指定
C:\tools\nssm\nssm.exe set NetsingToolWeb AppDirectory "D:\NetsingTool"

# IIS の /nesting/ サブパス配下で公開する場合(手順8参照)は、外部プレフィックスを環境変数で渡す
C:\tools\nssm\nssm.exe set NetsingToolWeb AppEnvironmentExtra "NESTING_ROOT_PATH=/nesting"

# 標準出力・エラー出力をログファイルへ
C:\tools\nssm\nssm.exe set NetsingToolWeb AppStdout "D:\NetsingTool\logs\service_stdout.log"
C:\tools\nssm\nssm.exe set NetsingToolWeb AppStderr "D:\NetsingTool\logs\service_stderr.log"

# 標準出力・エラーを10MBまたは1日ごとにローテーション
C:\tools\nssm\nssm.exe set NetsingToolWeb AppRotateFiles 1
C:\tools\nssm\nssm.exe set NetsingToolWeb AppRotateOnline 1
C:\tools\nssm\nssm.exe set NetsingToolWeb AppRotateBytes 10485760
C:\tools\nssm\nssm.exe set NetsingToolWeb AppRotateSeconds 86400

# サーバー起動時に自動開始
C:\tools\nssm\nssm.exe set NetsingToolWeb Start SERVICE_AUTO_START

# サービス開始
C:\tools\nssm\nssm.exe start NetsingToolWeb

# 状態確認
Get-Service NetsingToolWeb
```

**サービスの停止・再起動・削除:**

```powershell
nssm stop NetsingToolWeb
nssm restart NetsingToolWeb
nssm remove NetsingToolWeb confirm   # サービス削除 (アプリのファイル自体は残る)
```

> NSSM を導入できない環境では、代わりに「タスクスケジューラ」で `ログオン時` または `システム起動時` トリガーの
> タスクを作成し、操作を `.venv\Scripts\python.exe`、引数を `-m uvicorn webapp.main:app --host 0.0.0.0 --port 8000` として
> 「ユーザーがログオンしているかどうかにかかわらず実行する」を選択する方法でも常駐化できます。

### 7. ファイアウォール設定

社内 LAN の利用者からのみアクセスできるよう、送信元を絞ってポートを開放します。

```powershell
New-NetFirewallRule -DisplayName "NetsingTool Web" -Direction Inbound -Protocol TCP -LocalPort 8000 `
  -RemoteAddress 192.168.0.0/24 -Action Allow
```

`-RemoteAddress` は実際の社内 LAN のサブネットに置き換えてください。

### 8. IIS リバースプロキシ + HTTPS化 (任意・推奨)

`uvicorn` は既定でポート 8000 を直接待ち受けますが、社内標準の 443(HTTPS)でアクセスさせたい場合は
IIS を前段に置きリバースプロキシします。

1. サーバーマネージャーで IIS の役割を追加し、「URL Rewrite」モジュールと「Application Request Routing (ARR)」を
   Microsoft 公式サイトからダウンロードしてインストールする。
2. IIS マネージャーで ARR の「プロキシ」設定を有効化する。
3. サイト用の証明書 (社内 CA 発行、または自己署名証明書) をサーバー証明書ストアにインポートし、
   バインドで `https` ポート `443` に割り当てる。
4. サイトの `web.config` に以下のリライトルールを追加し、`https://<サーバー名>/` へのアクセスを
   `http://127.0.0.1:8000/` へ転送する。

```xml
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToUvicorn" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8000/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

この構成の場合、手順 6 の NSSM 登録時は `--host 127.0.0.1`(外部非公開)にし、IIS 側の 443 のみを
手順 7 のファイアウォールで開放してください。

> **`/nesting/` のようなサブパス配下で公開する場合**: 上記の `web.config` の `match url` を
> `^nesting/(.*)` 、`action` の `url` を `http://127.0.0.1:8000/{R:1}` のように書き換えてパスの
> プレフィックスを剥がして転送する。あわせて `webapp` 側にも外部から見えるプレフィックスを
> 教える必要があるため、環境変数 `NESTING_ROOT_PATH=/nesting` を設定してからサーバーを起動する
> (`start_server.bat` は未設定時に自動で `/nesting` を既定値にする。NSSM の場合は上記手順6の
> `AppEnvironmentExtra` で設定し、`nssm restart NetsingToolWeb` で反映する)。この設定が漏れると
> HTML 本体は表示されるが `style.css`/`app.js` などの静的ファイルが 404 になる。

### 9. アップデート手順

```powershell
nssm stop NetsingToolWeb
cd D:\NetsingTool
git pull
.venv\Scripts\pip.exe install -r requirements.txt
nssm start NetsingToolWeb
```

更新後は `pytest -q` が全件成功することを確認してから配布してください(コアロジックの精度に影響がないことの確認)。

### 10. 運用メモ

- ログ: アプリログは `logs\`、サービスの標準出力/エラーは手順 6 で設定した `logs\service_std*.log` を確認する。
- ジョブ実行の並列数: `webapp/jobs.py` の `MAX_WORKERS`(既定 2)。サーバースペックに応じて調整可能。
- データ保持: 完了・失敗ジョブはユーザーごとに直近20件かつ30日以内を保持し、起動時と1時間ごとに
  古い成果物とDBレコードを削除する。使用済みSTEPはジョブ完了時、未使用STEPは24時間後に削除する。
- 保持設定: `NESTING_RETENTION_KEEP_JOBS`、`NESTING_RETENTION_MAX_AGE_DAYS`、
  `NESTING_RETENTION_UPLOAD_MAX_AGE_HOURS`、`NESTING_RETENTION_INTERVAL_SECONDS` で既定値を変更できる。
- ログ保持: `server_*.log` とNSSMのローテーション済みログは、直近20件かつ30日以内を保持する。
  `NESTING_RETENTION_KEEP_LOG_FILES` と `NESTING_RETENTION_LOG_MAX_AGE_DAYS` で既定値を変更できる。
  NSSMのローテーション容量・間隔はサーバー負荷に応じて `AppRotateBytes` と
  `AppRotateSeconds` を調整する。
- 障害時: `nssm restart NetsingToolWeb` でプロセスプールごと再起動すれば、cadquery/OCP のネイティブクラッシュ
  (詳細は [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) を参照)からも復旧できる。

---

## ファイル構成

```
NetsingTool/
  main.py                    # CLI エントリポイント (単一 STEP の平面化)
  src/                       # コアロジック (GUI/Web いずれにも依存しない)
    cad/                     # STEP 読み込み (CadQuery)
    flatten/                 # 面展開アルゴリズム (穴輪郭抽出を含む)
    export/                  # DXF / PNG / JSON エクスポート・ネスティング配置図レンダリング
    nesting/                 # NFPベース複数部品ネスティングエンジン
  webapp/                    # Web アプリケーション (FastAPI)
    main.py                  # アプリ起動・ルーティング登録
    db.py                    # SQLite (users/jobs/user_config/uploads)
    security.py              # パスワードハッシュ・セッション署名・ログインレート制限
    storage.py                # アップロード/出力ファイルのユーザー別ストレージ管理
    jobs.py                  # ProcessPoolExecutor によるジョブ実行管理
    deps.py                  # 認証・CSRF 依存関係
    routers/                 # auth / jobs / config の API エンドポイント
    services/                # ConfigService / ExportService / NestingService
    templates/, static/      # フロントエンド (Jinja2 + 素の JS)
    scripts/create_user.py   # 初期ユーザー作成シードスクリプト
  docs/
    TROUBLESHOOTING.md       # トラブルシューティング
  tests/                     # pytest テストスイート
```

---

## テスト

```cmd
pytest
pytest --cov=src --cov=webapp  # カバレッジ付き
```

cadquery/OCP は正常終了時にもネイティブ側の後始末でクラッシュする既知の不具合があり、
全テスト成功後でも exit code が異常値になることがあります(詳細は
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) を参照)。CI 等で exit code を判定に使う場合は、
同じ引数を渡せる `run_tests.py` 経由で実行してください(exit code が正しく 0/1 になります)。

```cmd
python run_tests.py -q
python run_tests.py -q --cov=src --cov=webapp
```

---

## トラブルシューティング

[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) を参照してください。
