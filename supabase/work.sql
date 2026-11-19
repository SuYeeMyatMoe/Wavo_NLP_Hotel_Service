\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path TO hotel,public;
\ir ../hotel/work.sql
GRANT SELECT,INSERT,UPDATE ON ticket_work TO hotel_app;
GRANT SELECT,INSERT ON service_outcomes TO hotel_app;
REVOKE UPDATE ON service_outcomes FROM hotel_app;
ALTER TABLE ticket_work ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_outcomes ENABLE ROW LEVEL SECURITY;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['ticket_work','service_outcomes'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS work_read ON hotel.%I',tab);
 EXECUTE format('CREATE POLICY work_read ON hotel.%I FOR SELECT TO hotel_app USING(EXISTS(SELECT FROM hotel.tickets t WHERE t.id=ticket))',tab);
 EXECUTE format('DROP POLICY IF EXISTS staff_work ON hotel.%I',tab);
 EXECUTE format('CREATE POLICY staff_work ON hotel.%I TO hotel_app USING(hotel.staff() AND EXISTS(SELECT FROM hotel.tickets t WHERE t.id=ticket)) WITH CHECK(hotel.staff() AND EXISTS(SELECT FROM hotel.tickets t WHERE t.id=ticket))',tab);
 END LOOP;
END $$;
COMMIT;
