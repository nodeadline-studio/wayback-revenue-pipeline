-- BizSpy Supabase schema migration
-- Applies forensic job persistence tables for project qylvmjncfblcsucfzdan.
-- Idempotent: safe to re-run.

-- -----------------------------------------------------------------------
-- users
-- -----------------------------------------------------------------------
create table if not exists public.users (
    id          text primary key,
    email       text unique not null,
    password    text not null default '',
    is_paid     boolean not null default false,
    tier        text not null default 'free'
);

alter table public.users enable row level security;

-- -----------------------------------------------------------------------
-- orders
-- -----------------------------------------------------------------------
create table if not exists public.orders (
    id                  text primary key,
    paypal_order_id     text unique not null,
    capture_id          text,
    email               text not null,
    package             text not null,
    amount              numeric not null,
    status              text not null default 'created',
    target_url          text,
    report_file         text,
    public_report_file  text,
    created_at          text not null,
    captured_at         text
);

alter table public.orders enable row level security;

-- -----------------------------------------------------------------------
-- forensic_jobs
-- -----------------------------------------------------------------------
create table if not exists public.forensic_jobs (
    id                  text primary key,
    email               text not null,
    target_url          text not null,
    status              text not null default 'processing',
    progress            integer not null default 0,
    stage_label         text,
    report_file         text,
    public_report_file  text,
    created_at          text not null,
    updated_at          text not null,
    referrer            text,
    utm_source          text,
    utm_medium          text,
    utm_campaign        text,
    user_agent          text,
    job_type            text not null default 'demo'
);

alter table public.forensic_jobs enable row level security;

create index if not exists forensic_jobs_email_idx on public.forensic_jobs (email);
create index if not exists forensic_jobs_created_idx on public.forensic_jobs (created_at desc);
create index if not exists forensic_jobs_status_idx on public.forensic_jobs (status);

-- -----------------------------------------------------------------------
-- Add acquisition columns if upgrading an existing schema
-- -----------------------------------------------------------------------
do $$ begin
    alter table public.forensic_jobs add column if not exists referrer text;
    alter table public.forensic_jobs add column if not exists utm_source text;
    alter table public.forensic_jobs add column if not exists utm_medium text;
    alter table public.forensic_jobs add column if not exists utm_campaign text;
    alter table public.forensic_jobs add column if not exists user_agent text;
    alter table public.forensic_jobs add column if not exists job_type text default 'demo';
exception when others then null;
end $$;
