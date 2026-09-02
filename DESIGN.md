# 断熱材部品平面化ツール 設計書

## 1. 概要

SolidWorks から出力された STEP ファイルを読み込み、断熱材部品の最大面を XY 平面へ投影して DXF・PNG・JSON の 3 種類の成果物を生成する Web アプリケーション。
穴加工(内側輪郭)を含む実形状を保持したまま展開し、複数部品・複数数量(BOM)を対象に NFP(No-Fit-Polygon)ベースのネスティングを行い、歩留まり上位 3 件の分布案をブラウザ上で選択できる。
社内 LAN 限定・少人数利用・簡易ログイン必須の要件のもと、旧 PySide6 デスクトップ版から移行した(コアロジックである `src/` 配下は無改変のまま再利用し、精度を完全に維持している)。

---

## 2. アーキテクチャ

```
FlattenPipeline (src/pipeline.py)   ※ STEP 1 件あたりの平面化 (CLI/Web 共通)
  ├── StepReader      (src/cad/step_reader.py)
  ├── FaceExtractor   (src/flatten/face_extractor.py)
  ├── SurfaceUnfolder (src/flatten/surface_unfolder.py)   — min_strain / LSCM / ARAP + 穴抽出
  │     └── FaceProjector   (src/flatten/face_projector.py)
  │     └── CurvatureAnalyzer (src/flatten/curvature_analyzer.py)
  ├── DxfExporter     (src/export/dxf_exporter.py)   — 穴は HOLES レイヤーに出力
  ├── PngExporter     (src/export/png_exporter.py)   — 穴は白抜き表示
  ├── nesting_render.py (src/export/nesting_render.py) — ネスティング配置図 PNG レンダリング (GUI非依存)
  └── ResultWriter    (src/export/result_writer.py)  — holes/hole_count を含む result.json

Web アプリ (FastAPI, webapp/)        ※ 複数 STEP + 数量(BOM) をまとめてネスティング、ログイン必須
  templates/・static/ (Jinja2 + 素の JS) ── routers/{auth,jobs,config}.py
                    │
                    ├── JobManager (webapp/jobs.py) — ProcessPoolExecutor でジョブをプロセス分離実行
                    │     複数 STEP を順次 FlattenPipeline.run() で処理 (旧 PipelineWorker(QThread) の後継)
                    ├── NestingService (webapp/services/nesting_service.py)
                    │     └── NestingEngine (src/nesting/nfp_engine.py)  — NFPベース実形状ネスティング
                    ├── ExportService (webapp/services/export_service.py) — DXF/Excel 出力
                    ├── db.py — SQLite (users/jobs/user_config/uploads)、per-user 設定・ジョブ状態を管理
                    ├── security.py — bcrypt パスワードハッシュ・セッション署名・ログインレート制限
                    └── storage.py — ユーザー別アップロード/出力ディレクトリ管理・STEP ファイル検証
```

---

## 3. ディレクトリ構成

```
NetsingTool/
  src/
    __init__.py
    cad/
      __init__.py
      step_reader.py       # STEP 読み込み
    flatten/
      __init__.py
      face_extractor.py    # 最大面積面の抽出
      face_projector.py    # XY 投影・穴輪郭投影
      curvature_analyzer.py # 曲率解析・中立面推定
      surface_unfolder.py  # min_strain/LSCM/ARAP 展開・品質判定
      models.py            # UnfoldResult 等のデータモデル
    export/
      __init__.py
      dxf_exporter.py      # DXF 出力 (穴は HOLES レイヤー)
      png_exporter.py      # PNG 出力 (穴は白抜き)
      result_writer.py     # result.json 出力
    nesting/
      __init__.py
      models.py            # Part / PlacedInstance / NestingCandidate
      geometry_utils.py    # 回転・shapely変換・ネット面積計算
      nfp_engine.py        # NFPベース配置アルゴリズム (NestingEngine)
    pipeline.py            # パイプライン統合 (STEP 1 件分)
  webapp/
    main.py               # FastAPI アプリ起動・ルーティング登録
    db.py                 # SQLite (users/jobs/user_config/uploads)
    security.py           # bcrypt パスワードハッシュ・セッション署名・ログインレート制限
    storage.py             # アップロード/出力ファイルのユーザー別ストレージ管理・STEP 検証
    jobs.py                # ProcessPoolExecutor によるジョブ実行管理 (JobManager)
    deps.py                # 認証・CSRF 依存関係
    schemas.py             # pydantic リクエスト/レスポンススキーマ
    routers/
      auth.py, jobs.py, config.py
    services/
      nesting_service.py   # NestingEngine のラッパー (上位3候補を dict化)
      export_service.py    # DXF コピー・Excel(summary/内訳) 出力
      config_service.py    # config.json 読み書き・旧形式マイグレーション (CLI 向け、Web は DB 設定を使用)
    templates/, static/    # フロントエンド (Jinja2 + 素の JS)
    scripts/create_user.py # 初期ユーザー作成シードスクリプト
  tests/
    __init__.py
    conftest.py
    test_step_reader.py
    test_face_extractor.py
    test_face_projector.py
    test_surface_unfolder.py
    test_dxf_exporter.py
    test_png_exporter.py
    test_result_writer.py
    test_nfp_engine.py     # NestingEngine の重なり無し・穴内包・回転テスト
    test_integration.py    # ConfigService/ExportService 等の統合テスト
    test_pipeline.py
  main.py
  pyproject.toml
  conftest.py
  DESIGN.md
```

---

## 4. クラス設計

### 4.1 StepReader (`src/cad/step_reader.py`)

STEP ファイルの読み込みと cadquery ワークプレーンへの変換を担当。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `__init__` | `(path: str \| Path)` | ファイルパスを保持 |
| `load` | `() → StepReader` | STEP を読み込む（メソッドチェーン可） |
| `get_solids` | `() → list[cq.Shape]` | ソリッドリストを返す |

**エラー処理**
- `load()` 前に `get_solids()` を呼ぶ → `RuntimeError`
- ファイルが存在しない → `FileNotFoundError`

---

### 4.2 FaceExtractor (`src/flatten/face_extractor.py`)

ソリッドの全面を走査し最大面積の面を返す。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `extract_largest_face` | `(solid: cq.Shape) → cq.Face` | 面積最大の面を抽出 |
| `get_face_area` | `(face: cq.Face) → float` | 面積 (mm²) を返す |
| `get_face_normal` | `(face: cq.Face) → tuple[float, float, float]` | 面法線ベクトルを返す |

**エラー処理**
- 面が 0 枚 → `ValueError`

---

### 4.3 FaceProjector (`src/flatten/face_projector.py`)

面の外側輪郭ワイヤをサンプリングし、法線を Z 軸に揃える回転行列を適用して 2D 点列を生成する。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `__init__` | `(samples_per_edge: int = 50)` | エッジあたりのサンプリング数 |
| `project_to_xy` | `(face: cq.Face) → list[tuple[float, float]]` | 2D 投影点列を返す |
| `compute_rotation_matrix` | `(normal: tuple) → np.ndarray` | 法線→Z 軸の回転行列 |
| `get_polygon_area` | `(points: list[tuple]) → float` | 靴紐公式で 2D 面積を算出 |

**投影アルゴリズム**

1. `face.outerWire().Edges()` を走査
2. 各エッジを `samples_per_edge` 点でサンプリング (`edge.positionAt(t)`, t ∈ [0, 1))
3. 法線ベクトルを Z 軸に揃える回転行列 R を Rodrigues 公式で計算
4. 全 3D 点に R を適用し XY 成分を抽出

**回転行列（Rodrigues 公式）**

$$\mathbf{v} = \mathbf{n} \times \hat{z}, \quad c = \mathbf{n} \cdot \hat{z}, \quad s = \|\mathbf{v}\|$$

$$\mathbf{R} = \mathbf{I} + [\mathbf{v}]_{\times} + [\mathbf{v}]_{\times}^{2} \cdot \frac{1 - c}{s^{2}}$$

特殊ケース:
- $\mathbf{n} \approx +\hat{z}$: R = I
- $\mathbf{n} \approx -\hat{z}$: X 軸周り 180° 回転

**靴紐公式（Shoelace formula）**

$$A = \frac{1}{2} \left| \sum_{i=0}^{n-1} (x_i y_{i+1} - x_{i+1} y_i) \right|$$

---

### 4.4 DxfExporter (`src/export/dxf_exporter.py`)

2D 点列を ezdxf で LWPOLYLINE エンティティとして DXF R2010 形式で出力。穴は `HOLES` レイヤーへ分離出力する。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `export` | `(points: list[tuple], output_path: str \| Path, holes: list[list[tuple]] \| None = None) → None` | DXF を保存 (holes は HOLES レイヤーの LWPOLYLINE) |

---

### 4.5 PngExporter (`src/export/png_exporter.py`)

matplotlib (Agg バックエンド) でポリゴンを描画し PNG へ保存。穴は白抜き(赤破線)で表示する。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `export` | `(points: list[tuple], output_path: str \| Path, holes: list[list[tuple]] \| None = None) → None` | PNG を保存 (150 DPI) |

---

### 4.6 ResultWriter (`src/export/result_writer.py`)

面積情報を JSON ファイルへ書き出す。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `write` | `(part_area: float, flattened_area: float, output_path: str \| Path, holes: list[list[tuple]] \| None = None) → None` | result.json を保存 |

出力形式:
```json
{
  "part_area": 1234.5678,
  "flattened_area": 1230.1234,
  "area_diff_pct": 0.3567,
  "hole_count": 2,
  "holes": [[[2.0, 2.0], [4.0, 2.0], [4.0, 4.0], [2.0, 4.0]]]
}
```

`area_diff_pct = |part_area - flattened_area| / part_area × 100`

---

### 4.7 FlattenPipeline (`src/pipeline.py`)

全コンポーネントをオーケストレーションし、STEP ファイルから 3 種の成果物を一括生成する。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `__init__` | `(samples_per_edge: int = 50)` | 全コンポーネントを初期化 |
| `run` | `(step_path: str \| Path, output_dir: str \| Path) → dict` | パイプライン全体を実行 |

戻り値:
```python
{
    "part_area": float,        # 3D 面積 (face.Area()、穴控除済みネット値)
    "flattened_area": float,   # 展開後ネット面積 (穴控除済み。全手法で単位を統一)
    "area_diff_pct": float,
    "points": list[tuple[float, float]],
    "holes": list[list[tuple[float, float]]],
    "dxf_path": str,
    "png_path": str,
    "result_path": str,
    "best_method": str,        # "min_strain" | "lscm" | "arap"
    "error_rate": float,
    "quality": str,            # "A" | "B" | "C"
    "neutral_radius": float | None,
    "warning": str | None,
}
```

---

### 4.8 SurfaceUnfolder (`src/flatten/surface_unfolder.py`)

曲率解析→中立面推定→3手法(min_strain/LSCM/ARAP)展開→誤差最小の結果選択、を統括する。穴(内側ワイヤ)は
`FaceProjector.project_inner_wires_to_xy()` (min_strain) または `_ordered_boundaries()` のメッシュ内側ループ抽出
(LSCM/ARAP) により全手法で `UnfoldResult.holes` に保持される。

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `unfold` | `(face, solid=None) → UnfoldResult` | 3 手法を実行し誤差最小の結果を返す |
| `unfold_min_strain` | `(face, neutral_radius=None) → UnfoldResult` | 外周+穴を法線投影/円柱展開。`area_flat` は穴面積を控除したネット値 |
| `unfold_lscm` | `(face) → UnfoldResult` | Least Squares Conformal Mapping。メッシュが穴を含まないため元々ネット面積 |
| `unfold_arap` | `(face, max_iter=20) → UnfoldResult` | LSCM を初期値とした As-Rigid-As-Possible 展開 |

品質グレード: 誤差率 `< 1%` → A、`< 5%` → B、それ以外 → C (警告メッセージ付き)。

> **設計上の注意**: `area_3d` (`face.Area()`) は OCCT の実面積計算であり穴を控除したネット値。
> `area_flat` も必ずネット値で統一しないと誤差率比較・下流のネスティング歩留まり計算がずれる
> (2026-09 に `unfold_min_strain` の未控除バグを修正済み)。

---

### 4.9 NestingEngine (`src/nesting/nfp_engine.py`)

複数部品種別・数量(BOM)を対象に、穴を含む実形状のままシートへ配置する NFP(No-Fit-Polygon)ベースの
ネスティングエンジン。`webapp/services/nesting_service.py` からラップして呼び出される。

**アルゴリズム概要**

1. 各部品を 8 方向 (45°刻み) 回転させ、バウンディングボックス最小角を原点に正規化してキャッシュ (`_RotatedShape`)。
2. 既配置部品との衝突回避候補点は `pyclipper.MinkowskiSum` で NFP(A, B) = A ⊕ (−B) を計算し、その頂点集合と
   シート左下角・シート左右下辺への射影を候補として bottom-left-fill (y 最小 → x 最小) で採用。
3. 重なり最終判定は shapely の交差面積 (`Polygon(outer, holes)` 同士の `intersection().area`) で行うため、
   穴の内側リングを持つ部品同士なら他部品が穴の内部に収まる配置も自然に許容される。
4. 穴埋め二次パス (`_fill_holes`): 主配置パスで未配置の部品を、既配置部品の穴に対して
   `hole.buffer(-clearance/2).contains(candidate)` で重心合わせ判定する近似ヒューリスティック
   (厳密な内側 NFP 計算ではない)。
5. 面積降順・長辺降順・幅降順の 3 戦略で部品処理順を変えて実行し、歩留まり降順で重複を除いた上位
   `max_candidates` (既定 3) 件の `NestingCandidate` を返す。

| クラス/メソッド | シグネチャ | 説明 |
|---|---|---|
| `NestingEngine.__init__` | `(sheet_w, sheet_h, clearance)` | シート寸法・クリアランスを保持 |
| `NestingEngine.generate_candidates` | `(parts: list[Part], max_candidates=3) → list[NestingCandidate]` | 上位候補を返す |

性能特性: 衝突判定は AABB による事前フィルタ後に shapely 交差面積を計算する(フィルタ無しだと配置数の
増加に伴い O(n²) の重い幾何演算になる)。

---

### 4.10 Web アプリ層 (`webapp/`)

FastAPI + セッションCookie認証による構成。`webapp/routers/` のAPIエンドポイント → `webapp/jobs.py` の
`JobManager` → `webapp/services/` の各サービスがビジネスロジックを担う。

| コンポーネント | 役割 |
|---|---|
| `templates/index.html` + `static/app.js` | 複数 STEP アップロード+部品ごとの数量(BOM)入力、加工パラメータ入力 |
| `JobManager` (`webapp/jobs.py`) | `ProcessPoolExecutor` でジョブをプロセス分離実行し、各 STEP を順次 `FlattenPipeline.run()` で平面化後 `NestingService` で候補を計算 |
| `routers/jobs.py` | アップロード・ジョブ作成・進捗取得・候補一覧・ネスティング図PNGレンダリング・DXF/ZIPダウンロード |
| `static/app.js` の `renderCandidate()` | 選択中の分布案の画像(`/api/jobs/{id}/render`)と内訳テーブルを再描画 |
| `src/export/nesting_render.py` | 選択中の分布案を部品種別ごとに色分け・穴を透過表示して PNG にレンダリング (GUI非依存) |
| `webapp/services/config_service.py` | `config.json` の読み書き(CLI向け)。旧形式 (`step_path` 単体) から新形式 (`parts` リスト) への自動マイグレーション。Web版の実行時は使用せず、`webapp/db.py` の `user_config` テーブルでユーザー別に永続化する |
| `webapp/services/export_service.py` | DXF コピー、Excel (`Summary`/`Parts` シート) 出力、ユーザー別出力ディレクトリ下の `summary.xlsx` への追記 |
| `webapp/security.py` | bcrypt パスワードハッシュ、セッション署名(itsdangerous)、ログインレート制限 |
| `webapp/deps.py` | セッションCookie認証依存、CSRF検証(double-submit cookie方式) |

> 旧 GUI 版 (PySide6, `gui/`) は Web 版への完全移行に伴い廃止した(2026-09)。`src/` 配下のコアロジックは無改変で再利用しており、
> CLI版とWeb版で `result.json` の数値(`part_area`/`flattened_area`/`area_diff_pct`等)が完全一致することを確認済み。

---

## 5. データフロー

### 5.1 平面化 (STEP 1 件分、CLI/GUI 共通)

```
STEP File
    │
    ▼
StepReader.load() → get_solids()
    │  list[cq.Shape]  (先頭ソリッドを使用)
    ▼
FaceExtractor.extract_largest_face()
    │  cq.Face  +  part_area (mm², ネット)
    ▼
SurfaceUnfolder.unfold()  ── min_strain / LSCM / ARAP のうち誤差最小を選択
    │  points (外周) + holes (内側輪郭) + flattened_area (ネット)
    ├─────────────────────────────► DxfExporter.export()  → part_flat.dxf (holes は HOLES レイヤー)
    ├─────────────────────────────► PngExporter.export()  → part_preview.png (holes は白抜き)
    └─────────────────────────────► ResultWriter.write()  → result.json (holes/hole_count 含む)
```

### 5.2 Web ネスティング (複数 STEP + BOM)

```
STEP アップロード (POST /api/uploads)  ── 拡張子/マジックバイト/サイズ検証後、ユーザー別ディレクトリに保存
    │  list[(upload_id, quantity)]
    ▼
POST /api/jobs  ── job_id を発行し JobManager.submit() でプロセス分離実行
    │
    ▼
JobManager (ProcessPoolExecutor) ── 各 STEP を順次 FlattenPipeline.run()
    │  list[dict]  (part_area/flattened_area/points/holes/quantity を部品ごとに保持)
    ▼
NestingService.calculate_candidates()
    │  Part(id, outer, holes, quantity) を組み立て
    ▼
NestingEngine.generate_candidates()  ── 3 戦略 × NFP配置 → 歩留まり上位 3 件
    │  list[NestingCandidate] (DB: jobs.candidates_json に永続化)
    ├─────────────────────────────► GET /api/jobs/{id}/candidates  (分布案タブ・部品別内訳・穴面積合計)
    └─────────────────────────────► GET /api/jobs/{id}/render      (選択中の分布案を穴込みで PNG 描画)
```

---

## 6. テスト戦略

CadQuery 依存部分はモック化し、純 Python ロジックを単体テスト。

| テストファイル | テスト対象 |
|---|---|
| `test_step_reader.py` | ファイル未存在エラー・未ロードエラー・正常ロード |
| `test_face_extractor.py` | 最大面選択・空ソリッドエラー・面積/法線取得 |
| `test_face_projector.py` | 回転行列（Z 向き・逆向き・横向き）・靴紐面積・穴輪郭投影 |
| `test_surface_unfolder.py` | 品質グレード・誤差率・穴面積控除(ネット化)のリグレッション |
| `test_dxf_exporter.py` | ファイル生成・LWPOLYLINE エンティティ・HOLES レイヤー確認 |
| `test_png_exporter.py` | PNG ファイル生成・空点列の安全性・穴の白抜き描画 |
| `test_result_writer.py` | JSON 形式・面積差分計算・holes/hole_count 出力 |
| `test_pipeline.py` | E2E 正常系・ソリッド 0 件エラー |
| `test_nfp_engine.py` | 配置の重なり無し不変条件・穴内包配置・回転による配置可否・複数戦略の歩留まり降順 |
| `test_integration.py` | ConfigService (旧形式マイグレーション含む)・ExportService (Summary/Parts シート) の統合テスト (`webapp.services` を対象) |

---

## 7. 依存ライブラリ

| ライブラリ | バージョン要件 | 用途 |
|---|---|---|
| cadquery | 最新 | STEP 読み込み・形状操作 |
| OCP | cadquery 依存 | Open CASCADE Geometry Kernel |
| numpy | >=1.26 | 回転行列・幾何計算 |
| scipy | 最新 | LSCM/ARAP の疎行列ソルバ |
| ezdxf | >=1.3 | DXF 生成 |
| matplotlib | >=3.9 | PNG プレビュー・ネスティング配置図描画 |
| fastapi | >=0.110 | Web アプリケーションフレームワーク |
| uvicorn | >=0.29 | ASGI サーバー |
| bcrypt | >=4.0 | パスワードハッシュ |
| itsdangerous | >=2.1 | セッショントークンの署名 |
| jinja2 | >=3.1 | テンプレートレンダリング |
| python-multipart | >=0.0.9 | ファイルアップロード(multipart/form-data)解析 |
| openpyxl | >=3.1 | Excel (summary/内訳) 出力 |
| pyclipper | >=1.3 | NFP 計算 (Minkowski Sum) |
| shapely | >=2.0 | 穴判定・重なり検証・多角形バッファ |
| pytest | >=8.0 | テスト |
| pytest-cov | >=5.0 | カバレッジ計測 |

---

## 8. 設定の永続化

### 8.1 Web 版 (ユーザー別 DB 設定)

`webapp/db.py` の `user_config` テーブルに ユーザーごとの `parts`/`sheet_w`/`sheet_h`/`thickness`/`clearance` を JSON で保持する。
`GET/POST /api/config` で取得・保存する(フロントエンドはログイン中のユーザーの設定を自動復元する)。

### 8.2 CLI 向け config.json (後方互換)

```json
{
  "parts": [
    {"path": "D:/inetpub/授受/part1.step", "quantity": 2},
    {"path": "D:/inetpub/授受/part2.step", "quantity": 5}
  ],
  "sheet_w": 1000.0,
  "sheet_h": 2000.0,
  "thickness": 10.0,
  "clearance": 5.0
}
```

旧形式 (`"step_path": "..."` 単体キー) の `config.json` は `webapp/services/config_service.py` の `ConfigService.load()` 内の `_migrate()` で
自動的に `"parts": [{"path": step_path, "quantity": 1}]` へ変換される。保存時は常に新形式で書き出す。
