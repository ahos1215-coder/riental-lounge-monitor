-- Add missing indexes for common query patterns on blog_drafts.
--
-- 1. updated_at: ORDER BY updated_at DESC (レポートヘッダーの「最終更新」表示)
-- 2. (store_slug, created_at DESC): 店舗別の最新レポート取得
--    fetchLatestPublishedReportByStore() が content_type + is_published + store_slug + created_at.desc で
--    クエリするパターンをカバー。

CREATE INDEX IF NOT EXISTS blog_drafts_updated_at_idx
  ON public.blog_drafts (updated_at DESC);

CREATE INDEX IF NOT EXISTS blog_drafts_store_date_idx
  ON public.blog_drafts (store_slug, created_at DESC);
