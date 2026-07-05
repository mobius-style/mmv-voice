# mmv-voice — Whisper large-v3-turbo + MMV 音声整形パイプライン

> Governance-mediated voice pipeline: Whisper transcription + MMV-governed
> formatting, chunk-level fidelity verification, speaker attribution, minutes,
> and secretary digest output. A sibling of
> [mobius-style/mmv](https://github.com/mobius-style/mmv) — every LLM call goes
> through the frozen MMV governance stack, never a raw API.

音声ファイルをローカル完結で「検証済みの構造化テキスト」に変換するパイプライン。

1. **文字起こし**: Whisper `large-v3-turbo`(GPU、日本語)。生ログを左ペインにリアルタイム表示。
2. **話者分離**: pyannote が使える環境なら音声ベース、なければ MMV 経由の
   テキスト帰属に自動フォールバック。「話者1: / 話者2:」形式のターンに構造化。
3. **整形**: **MOBIUS MMV Medium ハーネス経由**の `gemma4:12b`(Ollama)。
   route_transformer + post_validator + force_reanchor_v2 の凍結ガバナンス
   スタック(MMV-M-RC3.3)を通して、フィラー除去・句読点/段落整形を行う。
4. **忠実性検証**: 整形文が原文の意味内容を保存しているか(脱落・追加・
   過度な要約・意味変化)をチャンク毎に MMV 経由で検査し、疑わしい
   チャンクに ⚠️ マーカーを付け、検証レポートを出力する。
5. **議事メモ生成**: 概要/主な論点/決定事項/TODO の Markdown 議事メモを生成。
6. **秘書digest出力**: ボタン一つで MOBIUS 秘書システムの
   `addons/secretary/state/digests/voice_note_<ts>.md` に保存し、
   音声を秘書エコシステムの入力チャネルにする。

話者分離・忠実性検証・議事メモはGUIのチェックボックスで個別にON/OFF可能。

## MMVエンジン切替（ローカル ⇔ クラウド120B）

処理エンジン(話者帰属・整形・検証・議事メモの全MMV段)をGUIのラジオボタンで
切り替えられる:

| エンジン | モデル | 実行場所 | 用途 |
|---|---|---|---|
| **MMV-M**(既定) | gemma4:12b | ローカル(Ollama) | プライバシー重視・通常運用 |
| **MMV-L**(任意) | gpt-oss-120b | **Groqクラウド** | 話者帰属・整形の精度重視 |

- どちらも `releases/<medium|large>/current.yaml` のリリースポインタから
  束縛を読み、凍結ガバナンススタック(route_transformer + post_validator +
  force_reanchor_v2)を通る。「MMVの状態」はどちらでも維持される。
- MMV-L 選択時は**文字起こしテキストがGroqへ送信される**ため、選択の瞬間に
  確認ダイアログが出る(既定は常にローカルM)。
- `GROQ_API_KEY` は環境変数 → `MOBIUS_MMV/.env` の順で自動解決。
  どちらにも無い場合は MMV-L のボタンが無効化される。
- digest には使用エンジンが `formatter:` 行に記録される。

## フォルダ構成

```
Wisper/
├── whisper_gui.py        # メインプログラム
├── launch.sh             # 起動ファイル(Ollama自動起動 → GUI起動)
├── whisper_tool.desktop  # Linux デスクトップアイコン用(launch.sh を呼ぶ)
├── requirements.txt      # Python パッケージ一覧
├── LICENSE               # AGPL-3.0
└── README.md             # このファイル
```

ローカル作業フォルダには上記に加えて `backup/`(旧構成の退避)、
`launch.bat`(旧Windows用)、テスト音声(*.m4a)があるが、これらは
git 管理外(.gitignore)。**音声ファイルは絶対にコミットしないこと。**

## 動作環境(検証済み構成)

| 項目 | 内容 |
|---|---|
| GPU | NVIDIA RTX 5070 Ti (16GB) |
| Python | pyenv 3.10.14 (`~/.pyenv/versions/3.10.14/bin/python3`) |
| PyTorch | 2.10.0+cu128(Blackwell対応) |
| Whisper | openai-whisper 20250625 |
| LLM | Ollama + `gemma4:12b`(7.6GB) |
| MMVハーネス | `~/デスクトップ/mobius_ai/MOBIUS_MMV/operate-fr-bench` |

実測(音声60秒あたり): 文字起こし 約2.3秒、話者帰属 約6秒、整形 約5秒、
忠実性検証 約1秒/チャンク、議事メモ 約3秒。

## 忠実性検証・議事メモ・digest出力

- **忠実性検証**: 整形チャンク毎に「原文 vs 整形文」を MMV 経由で比較判定。
  NG判定のチャンクは整形済みタブで `⚠️【要確認 チャンクN: 理由】` と
  マークされ、「検証レポート」タブに全チャンクの判定一覧が出る。
  LLM整形の弱点である「黙った改変」をローカルで検出する層。
- **議事メモ**: 「議事メモ」タブに Markdown で出力。該当がない節は
  「(なし)」となる(本文にない事柄は追加しない指示付き)。
- **秘書digest**: 処理完了後に「📤 秘書digestへ保存」ボタンが有効になる。
  保存先は `MOBIUS_MMV/addons/secretary/state/digests/voice_note_<ts>.md`。
  メタデータ(音源・モデル・話者バックエンド・検証サマリ)+議事メモ+
  整形本文+検証レポートを1ファイルに収める。

## 話者分離のバックエンド

| バックエンド | 条件 | 品質 |
|---|---|---|
| pyannote.audio(音声ベース) | `pip install pyannote.audio` + HFで `pyannote/speaker-diarization-3.1` と `segmentation-3.0` のゲート承認 | 高(声質で判定) |
| MMVテキスト帰属(既定) | 追加設定不要 | 中(発話内容から推定) |

pyannote は起動時ではなく処理時に自動検出され、失敗すれば黙って
テキスト帰属にフォールバックする(現環境はゲート未承認のためテキスト帰属)。

## MMV連携の仕組み

- モデル束縛はハードコードせず、起動時にMMVのリリースポインタ
  `operate-fr-bench/releases/medium/current.yaml` から読む
  (現行: MMV-M-RC3.3 / gemma4:12b、2026-06-06 モデル束縛更新)。
  MMV側で束縛が更新されれば本ツールも自動追従する。
- 整形は `harness.adapters.call_adapter` を直接呼ぶ。凍結プロファイル
  (`gemma4_12b_route_transformer_plus_validator_v3_1`)には一切手を加えない。
- プロファイルは `max_tokens=1024` で凍結されているため、長い文字起こしは
  文末境界で約1000字ずつに分割して整形する(`FORMAT_CHUNK_CHARS`)。
  チャンクの整形に失敗した場合は未整形の原文をそのまま残す。
- MMVハーネスが読み込めない場合、整形は無効化されエラー表示になる
  (素のGemmaへの無言フォールバックはしない)。

## VRAM運用(16GB 1枚での共存)

Whisper と LLM は同時には載せず、順次スワップする:

1. Whisper実行前に Ollama へ `keep_alive: 0` を送り gemma4:12b をアンロード
2. 空きVRAMが 7GB(`MIN_FREE_VRAM_GB`)を超えるまで待機(最大30秒)、
   確保できなければCPUフォールバック
3. 文字起こし完了後、Whisperモデルを解放してからMMV整形を開始

## 起動方法

```bash
bash launch.sh        # Ollama serve の自動起動込み
```

またはデスクトップアイコン(`音声整形ツール`)をダブルクリック。

## セットアップ(新規マシンの場合)

1. Ollama をインストールし `ollama pull gemma4:12b`
2. `sudo apt install ffmpeg`
3. Blackwell世代GPUの場合は CUDA 12.8 対応 PyTorch を入れる:
   `pip install torch --index-url https://download.pytorch.org/whl/cu128`
4. `pip install -r requirements.txt`(openai-whisper / requests / pyyaml)
5. [MOBIUS_MMV リポジトリ](https://github.com/mobius-style/mmv)を配置し、
   場所が既定(`~/デスクトップ/mobius_ai/MOBIUS_MMV`)と異なる場合は
   環境変数 `MMV_REPO` でパスを指定する

## 設定の切り替え

`whisper_gui.py` 冒頭の定数で変更する:

| 定数 | 既定値 | 用途 |
|---|---|---|
| `WHISPER_MODEL_SIZE` | `large-v3-turbo` | 精度優先なら `large-v3`(約4.7倍遅い・要VRAM 11GB) |
| `MIN_FREE_VRAM_GB` | `7.0` | `large-v3` にするなら `11.0` に上げる |
| `FORMAT_CHUNK_CHARS` | `1000` | MMV整形1回あたりの最大入力文字数 |

## よくあるエラー

| エラー | 原因 | 対処 |
|---|---|---|
| `Ollama未起動` | ollama serve 未起動 | launch.sh が自動起動する |
| `モデル [gemma4:12b] が見つかりません` | モデル未取得 | `ollama pull gemma4:12b` |
| `MMVハーネスを読み込めません` | MMV_REPO パス不正 / MMVリポジトリ移動 | `whisper_gui.py` の `MMV_REPO` を修正 |
| `No module named 'whisper'` | パッケージ未インストール | `pip install -r requirements.txt` |
| `ffmpeg not found` | ffmpeg 未インストール | `sudo apt install ffmpeg` |
| `CUDA out of memory` | VRAM不足 | 他のGPUアプリを閉じてから起動 |

## 旧構成に戻す場合

```bash
cp backup/whisper_gui.py.bak_qwen_20260704 whisper_gui.py
```

(Whisper medium + Qwen3.5:9b 直叩き構成。2×RTX 3070 時代のもの)

## License

AGPL-3.0 — Copyright (C) 2025-2026 MOBIUS LLC (Author: Taiko Toeda)。
[mobius-style/mmv](https://github.com/mobius-style/mmv) の兄弟プロジェクト。
MMVハーネス本体・凍結プロファイル・リリースポインタは mmv リポジトリ側の
成果物であり、本リポジトリはそれを呼び出すアプリケーション層のみを含む。
