-- Private, portable proof records. Verification evidence is a client report;
-- a retrieved record must be checked again in the consuming environment.
begin;
create table if not exists public.lean2llm_proofs (
  user_id uuid not null references auth.users(id) on delete cascade,
  content_id text not null check (content_id ~ '^[0-9a-f]{64}$'),
  record jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  search_document tsvector generated always as (
    to_tsvector('english'::regconfig,
      coalesce(record #>> '{content,title}', '') || ' ' ||
      coalesce(record #>> '{content,request,statement}', '') || ' ' ||
      coalesce(record #>> '{content,tags}', ''))
  ) stored,
  primary key (user_id, content_id),
  constraint lean2llm_record_schema check (
    coalesce(record ->> 'schema', '') = 'lean2llm.proof/v1' and
    coalesce(record ->> 'id', '') = content_id and
    coalesce(jsonb_typeof(record -> 'content'), '') = 'object'
  ),
  constraint lean2llm_record_size check (octet_length(record::text) <= 1048576)
);
alter table public.lean2llm_proofs enable row level security;
revoke all on public.lean2llm_proofs from anon;
grant select, insert, update, delete on public.lean2llm_proofs to authenticated;
create policy "lean2llm_select_own" on public.lean2llm_proofs
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "lean2llm_insert_own" on public.lean2llm_proofs
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "lean2llm_update_own" on public.lean2llm_proofs
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
create policy "lean2llm_delete_own" on public.lean2llm_proofs
  for delete to authenticated using ((select auth.uid()) = user_id);
create index lean2llm_proofs_search on public.lean2llm_proofs using gin(search_document);
create index lean2llm_proofs_recent on public.lean2llm_proofs(user_id, updated_at desc);
commit;
