# `/api/current` の方針メモ
Last updated: 2026-08-21（外部レビュー F15 対応: `/api/range` に触れた1行を実装に合わせて訂正）

> **契約の正本は `CLAUDE.md` §3「絶対不変リスト」**。`plan/API_CONTRACT.md` と `plan/DECISIONS.md` はその詳細版。
> 本ファイルは **`/api/current` だけ**の位置づけ・将来案を短く固定する（`/api/range` の契約そのものは
> `plan/API_CONTRACT.md` を見ること。ここでは `/api/current` の文脈でしか触れない）。

---

## 現状（事実）

- **実装**: Flask（`oriental/routes/data.py` 等）。**ローカルキャッシュや直近1件のような「軽い最新値」**を返す経路であり、**Supabase `logs` の最新行を毎リクエストクエリしているわけではない**（`plan/STATUS.md` も参照）。
- **利用者**: 主にレガシー互換・ダッシュボード周辺。メインの時系列は **`/api/range?store=&limit=`** が正。

---

## 決定（当面）

1. **契約・パスは変えない**（Breaking を避ける）。フロントや外部が依存している可能性を無視しない。
2. **「最新の真実」を知りたい用途**は **`/api/range` の末尾行**や、将来の **専用メタ API** で扱う想定に寄せる（`/api/current` にクエリ増やさない方針と整合）。
3. **Supabase 直読みに Flask 内で切り替える**ことは **可能だが別タスク**。やるなら:
   - レスポンス形の互換
   - キャッシュ TTL / 負荷
   - `plan/API_CONTRACT.md` への1行追記  
   をセットにする。

---

## やらないこと

- `/api/current` にクエリを足す（`/api/range` の末尾行や将来の専用メタ API に寄せる方針）。
- `/api/range` に**時刻粒度**の引数を足してサーバ側で夜窓だけ返すこと（既存 DECISIONS どおり。
  2026-08-21 訂正: `/api/range` 自体は `from`/`to`〈日付粒度〉を既に正式サポートしている。
  ここで「やらない」としているのは時刻粒度の夜窓ロジックをFlaskに持たせることで、
  日付単位のクエリ追加ではない。詳細は `plan/API_CONTRACT.md`）。
- Next.js から Supabase 直参照（レイヤ方針どおり）。

---

## 参照

- `plan/DECISIONS.md` 13（`/api/current` の当面維持）
- `plan/STATUS.md`（既知の制限）
