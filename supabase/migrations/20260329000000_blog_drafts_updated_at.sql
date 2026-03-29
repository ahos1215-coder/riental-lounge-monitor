-- Add updated_at column to blog_drafts for upsert timestamp tracking.
-- created_at stays at original INSERT time; updated_at reflects the latest PATCH/UPDATE.

alter table public.blog_drafts
  add column if not exists updated_at timestamptz not null default now();

-- Backfill: set updated_at = created_at for all existing rows
update public.blog_drafts
set updated_at = created_at;

-- Auto-update trigger: set updated_at on every UPDATE
create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at := now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists blog_drafts_set_updated_at on public.blog_drafts;
create trigger blog_drafts_set_updated_at
  before update on public.blog_drafts
  for each row execute function public.set_updated_at();
