-- Extend blog_drafts for report/editorial split.
alter table public.blog_drafts
  add column if not exists content_type text,
  add column if not exists is_published boolean not null default false,
  add column if not exists edition text,
  add column if not exists public_slug text;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'blog_drafts_content_type_check'
  ) then
    alter table public.blog_drafts
      add constraint blog_drafts_content_type_check
      check (content_type in ('daily', 'weekly', 'editorial'));
  end if;
end $$;

create unique index if not exists blog_drafts_facts_id_uidx
  on public.blog_drafts (facts_id);

create unique index if not exists blog_drafts_public_slug_uidx
  on public.blog_drafts (public_slug)
  where public_slug is not null;

create index if not exists blog_drafts_content_type_published_idx
  on public.blog_drafts (content_type, is_published, store_slug, created_at desc);

-- Backfill existing rows.
update public.blog_drafts
set
  content_type = case
    when source in ('github_actions_cron', 'github_actions_retry', 'vercel_cron') then 'daily'
    else 'editorial'
  end,
  is_published = case
    when source in ('github_actions_cron', 'github_actions_retry', 'vercel_cron') then true
    else false
  end
where content_type is null;
