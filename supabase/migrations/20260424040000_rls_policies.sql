-- RLS policies for all tables.
-- service_role bypasses RLS natively in Supabase, but explicit policies
-- ensure anon/authenticated reads work for status polling.

-- -----------------------------------------------------------------------
-- forensic_jobs
-- -----------------------------------------------------------------------
drop policy if exists service_role_all_forensic_jobs on public.forensic_jobs;
create policy service_role_all_forensic_jobs on public.forensic_jobs
    for all to service_role using (true) with check (true);

-- Allow anonymous status polling by job id (no auth required for status page)
drop policy if exists anon_select_forensic_jobs on public.forensic_jobs;
create policy anon_select_forensic_jobs on public.forensic_jobs
    for select to anon using (true);

drop policy if exists authenticated_select_forensic_jobs on public.forensic_jobs;
create policy authenticated_select_forensic_jobs on public.forensic_jobs
    for select to authenticated using (true);

-- -----------------------------------------------------------------------
-- users
-- -----------------------------------------------------------------------
drop policy if exists service_role_all_users on public.users;
create policy service_role_all_users on public.users
    for all to service_role using (true) with check (true);

drop policy if exists anon_select_users on public.users;
create policy anon_select_users on public.users
    for select to anon using (true);

-- -----------------------------------------------------------------------
-- orders
-- -----------------------------------------------------------------------
drop policy if exists service_role_all_orders on public.orders;
create policy service_role_all_orders on public.orders
    for all to service_role using (true) with check (true);
