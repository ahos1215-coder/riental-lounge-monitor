-- blog_drafts: LINE / 自動生成のブログ下書き（MDX）と insight メタ
-- Next.js API route (frontend/src/app/api/line) が service role で INSERT

create table if not exists public.blog_drafts (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),

  store_id text not null,
  store_slug text not null,
  target_date date not null,
  facts_id text not null,

  mdx_content text not null default '',
  insight_json jsonb not null default '{}'::jsonb,

  source text not null default 'line_webhook',
  line_user_id text,
  error_message text
);

create index if not exists blog_drafts_created_at_idx on public.blog_drafts (created_at desc);
create index if not exists blog_drafts_facts_id_idx on public.blog_drafts (facts_id);
create index if not exists blog_drafts_store_slug_idx on public.blog_drafts (store_slug);

comment on table public.blog_drafts is 'MEGRIBI blog MDX drafts generated via LINE webhook / automation';

-- RLS: 既定は anon から隠す。service_role はバイパス。
alter table public.blog_drafts enable row level security;

-- 必要なら anon の read ポリシーを後から追加（管理画面用）
