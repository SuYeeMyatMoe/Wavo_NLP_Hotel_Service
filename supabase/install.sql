-- Run with psql as the project database owner. The private schema is not exposed to PostgREST.
\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA IF NOT EXISTS hotel;
CREATE SCHEMA IF NOT EXISTS extensions;
SET LOCAL search_path TO hotel,public;
\ir ../hotel/schema.sql
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='hotel_app') THEN CREATE ROLE hotel_app NOLOGIN; END IF;
END $$;
GRANT hotel_app TO CURRENT_USER;
REVOKE ALL ON SCHEMA hotel FROM PUBLIC;
GRANT USAGE ON SCHEMA hotel,extensions TO hotel_app;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA hotel TO hotel_app;
CREATE OR REPLACE FUNCTION hotel.actor() RETURNS text LANGUAGE sql STABLE SET search_path=''
AS $$ SELECT nullif(current_setting('hotel.actor',true),'') $$;
CREATE OR REPLACE FUNCTION hotel.my_hotel() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=''
AS $$ SELECT hotel FROM hotel.profiles WHERE id=hotel.actor() $$;
CREATE OR REPLACE FUNCTION hotel.staff() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=''
AS $$ SELECT role IN ('staff','manager') FROM hotel.profiles WHERE id=hotel.actor() $$;
REVOKE ALL ON FUNCTION hotel.my_hotel(),hotel.staff() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION hotel.my_hotel(),hotel.staff() TO hotel_app;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY profile_read ON profiles FOR SELECT TO hotel_app USING(id=hotel.actor() OR (hotel=hotel.my_hotel() AND hotel.staff()));
CREATE POLICY profile_edit ON profiles FOR UPDATE TO hotel_app USING(id=hotel.actor()) WITH CHECK(id=hotel.actor());
REVOKE UPDATE ON profiles FROM hotel_app;
GRANT UPDATE(consent) ON profiles TO hotel_app;
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
CREATE POLICY ticket_read ON tickets FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel() AND (hotel.staff() OR guest=hotel.actor()));
CREATE POLICY ticket_create ON tickets FOR INSERT TO hotel_app WITH CHECK(hotel=hotel.my_hotel() AND author=hotel.actor() AND (hotel.staff() OR guest=hotel.actor()));
CREATE POLICY ticket_change ON tickets FOR UPDATE TO hotel_app USING(hotel=hotel.my_hotel() AND hotel.staff());
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
CREATE POLICY ticket_events ON events TO hotel_app USING(EXISTS(SELECT FROM hotel.tickets WHERE id=events.ticket)) WITH CHECK(EXISTS(SELECT FROM hotel.tickets WHERE id=events.ticket));
ALTER TABLE calls ENABLE ROW LEVEL SECURITY;
CREATE POLICY hotel_calls ON calls TO hotel_app USING(hotel=hotel.my_hotel() AND (hotel.staff() OR guest=hotel.actor())) WITH CHECK(hotel=hotel.my_hotel() AND (hotel.staff() OR guest=hotel.actor()));
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['operators','policies'] LOOP
 EXECUTE format('ALTER TABLE hotel.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY staff_tools ON hotel.%I TO hotel_app USING (hotel=hotel.my_hotel() AND hotel.staff()) WITH CHECK(hotel=hotel.my_hotel() AND hotel.staff())',t);
 END LOOP;
END $$;
-- Operators are safe for the guest intake controller to resolve within its hotel.
CREATE POLICY guest_routing ON operators FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel());
INSERT INTO storage.buckets(id,name,public) VALUES('hotel-private','hotel-private',false) ON CONFLICT(id) DO NOTHING;
COMMIT;
\ir guest_messages.sql
\ir concierge.sql
\ir work.sql

\ir intelligence.sql

\ir operations.sql
\ir call_start.sql
\ir completion.sql
\ir call_timing.sql
