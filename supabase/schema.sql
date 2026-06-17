-- DiviConto — schema Supabase per la sincronizzazione (Fase 3).
--
-- Da eseguire UNA VOLTA nel SQL Editor di Supabase (Project → SQL Editor →
-- "New query" → incolla tutto → Run). È idempotente: si può rieseguire.
--
-- Cosa crea:
--   * tabelle "mirror" di quelle locali (trips, participants, expenses, splits)
--     con id uuid, updated_at (timestamptz, autoritativo del server) e deleted;
--   * trip_members: chi può accedere a quale viaggio;
--   * trigger per updated_at e per registrare il creatore del viaggio come owner;
--   * Row Level Security: ogni utente vede solo i viaggi di cui è membro;
--   * RPC join_trip(code): permette a un amico di unirsi con un codice.
--
-- Gli importi sono salvati come TEXT (come in locale) per fedeltà ai Decimal.

-- gen_random_uuid() è fornita da pgcrypto (già disponibile su Supabase).
create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------------
-- Tabelle
-- ---------------------------------------------------------------------------
create table if not exists public.trips (
    id            uuid primary key,
    name          text not null,
    description   text not null default '',
    base_currency text not null,
    owner_id      uuid not null references auth.users(id),
    share_code    text not null unique
                  default upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 8)),
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    deleted       boolean not null default false
);

create table if not exists public.participants (
    id         uuid primary key,
    trip_id    uuid not null references public.trips(id),
    name       text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted    boolean not null default false
);

create table if not exists public.expenses (
    id           uuid primary key,
    trip_id      uuid not null references public.trips(id),
    payer_id     uuid not null references public.participants(id),
    amount       text not null,
    currency     text not null,
    rate_to_base text not null,
    amount_base  text not null,
    description  text not null default '',
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    deleted      boolean not null default false
);

create table if not exists public.splits (
    id             uuid primary key,
    expense_id     uuid not null references public.expenses(id),
    participant_id uuid not null references public.participants(id),
    mode           text not null,
    share_base     text not null,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    deleted        boolean not null default false
);

create table if not exists public.trip_members (
    trip_id uuid not null references public.trips(id),
    user_id uuid not null references auth.users(id),
    role    text not null default 'member',
    email   text,
    primary key (trip_id, user_id)
);

-- email del membro (per mostrare nell'app con chi è condiviso un viaggio).
-- Su DB già creati la colonna va aggiunta; il backfill in fondo riempie le righe
-- preesistenti leggendo auth.users (non accessibile ai client, qui sì: lo script
-- gira come owner/service_role).
alter table public.trip_members add column if not exists email text;

create index if not exists idx_participants_trip on public.participants(trip_id);
create index if not exists idx_expenses_trip on public.expenses(trip_id);
create index if not exists idx_splits_expense on public.splits(expense_id);
create index if not exists idx_members_user on public.trip_members(user_id);

-- ---------------------------------------------------------------------------
-- Funzioni di supporto
-- ---------------------------------------------------------------------------

-- Verifica l'appartenenza dell'utente corrente a un viaggio. SECURITY DEFINER
-- per non innescare la RLS ricorsiva su trip_members.
create or replace function public.is_member(tid uuid)
returns boolean
language sql
security definer
stable
set search_path = public
as $$
    select exists (
        select 1 from public.trip_members m
        where m.trip_id = tid and m.user_id = auth.uid()
    );
$$;

-- Aggiorna updated_at a ogni insert/update (timestamp autoritativo del server).
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

-- Alla creazione di un viaggio, registra il creatore come owner.
create or replace function public.add_owner_membership()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.trip_members(trip_id, user_id, role, email)
    values (new.id, new.owner_id, 'owner',
            (select email from auth.users where id = new.owner_id))
    on conflict do nothing;
    return new;
end;
$$;

-- Un amico si unisce a un viaggio tramite il codice condiviso.
create or replace function public.join_trip(code text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    tid uuid;
begin
    select id into tid from public.trips where share_code = code and deleted = false;
    if tid is null then
        raise exception 'codice non valido';
    end if;
    insert into public.trip_members(trip_id, user_id, role, email)
    values (tid, auth.uid(), 'member',
            (select email from auth.users where id = auth.uid()))
    on conflict do nothing;
    return tid;
end;
$$;

-- ---------------------------------------------------------------------------
-- Trigger
-- ---------------------------------------------------------------------------
drop trigger if exists trg_set_updated_at on public.trips;
create trigger trg_set_updated_at before insert or update on public.trips
    for each row execute function public.set_updated_at();

drop trigger if exists trg_set_updated_at on public.participants;
create trigger trg_set_updated_at before insert or update on public.participants
    for each row execute function public.set_updated_at();

drop trigger if exists trg_set_updated_at on public.expenses;
create trigger trg_set_updated_at before insert or update on public.expenses
    for each row execute function public.set_updated_at();

drop trigger if exists trg_set_updated_at on public.splits;
create trigger trg_set_updated_at before insert or update on public.splits
    for each row execute function public.set_updated_at();

drop trigger if exists trg_trip_owner on public.trips;
create trigger trg_trip_owner after insert on public.trips
    for each row execute function public.add_owner_membership();

-- ---------------------------------------------------------------------------
-- Privilegi + Row Level Security
-- ---------------------------------------------------------------------------
grant usage on schema public to authenticated;
grant select, insert, update, delete on
    public.trips, public.participants, public.expenses,
    public.splits, public.trip_members to authenticated;
grant execute on function public.join_trip(text) to authenticated;

alter table public.trips         enable row level security;
alter table public.participants  enable row level security;
alter table public.expenses      enable row level security;
alter table public.splits        enable row level security;
alter table public.trip_members  enable row level security;

-- trips: accessibile ai membri; l'insert richiede di esserne l'owner.
-- include "owner_id = auth.uid()" anche qui: l'upsert rilegge la riga appena
-- creata (RETURNING) prima che il trigger renda visibile la membership owner.
drop policy if exists trips_select on public.trips;
create policy trips_select on public.trips
    for select using (public.is_member(id) or owner_id = auth.uid());
drop policy if exists trips_insert on public.trips;
create policy trips_insert on public.trips
    for insert with check (owner_id = auth.uid());
-- NB: include "owner_id = auth.uid()" perché il primo salvataggio del viaggio
-- avviene via UPSERT (INSERT ... ON CONFLICT DO UPDATE): Postgres verifica anche
-- la WITH CHECK di UPDATE, ma in quel momento la membership dell'owner non è
-- ancora stata creata dal trigger AFTER INSERT, quindi is_member(id) sarebbe false.
drop policy if exists trips_update on public.trips;
create policy trips_update on public.trips
    for update using (public.is_member(id) or owner_id = auth.uid())
    with check (public.is_member(id) or owner_id = auth.uid());

-- participants / expenses: legati al viaggio tramite trip_id.
drop policy if exists participants_all on public.participants;
create policy participants_all on public.participants
    for all using (public.is_member(trip_id)) with check (public.is_member(trip_id));

drop policy if exists expenses_all on public.expenses;
create policy expenses_all on public.expenses
    for all using (public.is_member(trip_id)) with check (public.is_member(trip_id));

-- splits: legati al viaggio passando per la spesa.
drop policy if exists splits_all on public.splits;
create policy splits_all on public.splits
    for all using (
        public.is_member((select e.trip_id from public.expenses e where e.id = expense_id))
    ) with check (
        public.is_member((select e.trip_id from public.expenses e where e.id = expense_id))
    );

-- trip_members: ognuno vede i membri dei propri viaggi (insert solo via RPC/trigger).
drop policy if exists members_select on public.trip_members;
create policy members_select on public.trip_members
    for select using (user_id = auth.uid() or public.is_member(trip_id));

-- ---------------------------------------------------------------------------
-- Backfill: popola email nelle membership preesistenti (idempotente)
-- ---------------------------------------------------------------------------
update public.trip_members m
set email = u.email
from auth.users u
where u.id = m.user_id and (m.email is null or m.email = '');
