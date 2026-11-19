\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path TO hotel,public;
\ir ../hotel/concierge.sql
GRANT SELECT,INSERT,UPDATE ON service_times,room_inventory,call_notes TO hotel_app;
GRANT SELECT,INSERT ON concierge_turns TO hotel_app;
ALTER TABLE service_times ENABLE ROW LEVEL SECURITY;
ALTER TABLE room_inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE concierge_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE move_requests ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON move_requests TO hotel_app;
DROP POLICY IF EXISTS read_moves ON move_requests;
CREATE POLICY read_moves ON move_requests FOR SELECT TO hotel_app USING(EXISTS(SELECT FROM hotel.call_notes n WHERE n.id=call_id));
DROP POLICY IF EXISTS request_move ON move_requests;
CREATE POLICY request_move ON move_requests FOR INSERT TO hotel_app WITH CHECK(decision='Pending' AND EXISTS(SELECT FROM hotel.call_notes n WHERE n.id=call_id));
DROP POLICY IF EXISTS decide_move ON move_requests;
CREATE POLICY decide_move ON move_requests FOR UPDATE TO hotel_app USING(hotel.staff() AND EXISTS(SELECT FROM hotel.call_notes n WHERE n.id=call_id));
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['service_times','room_inventory'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS hotel_read ON hotel.%I',tab);
 EXECUTE format('CREATE POLICY hotel_read ON hotel.%I FOR SELECT TO hotel_app USING (hotel=hotel.my_hotel())',tab);
 EXECUTE format('DROP POLICY IF EXISTS staff_write ON hotel.%I',tab);
 EXECUTE format('CREATE POLICY staff_write ON hotel.%I TO hotel_app USING (hotel=hotel.my_hotel() AND hotel.staff()) WITH CHECK (hotel=hotel.my_hotel() AND hotel.staff())',tab);
 END LOOP;
END $$;
DROP POLICY IF EXISTS actor_notes ON call_notes;
CREATE POLICY actor_notes ON call_notes TO hotel_app
 USING (hotel=hotel.my_hotel() AND (guest=hotel.actor() OR hotel.staff()))
 WITH CHECK (hotel=hotel.my_hotel() AND EXISTS(SELECT FROM hotel.calls c WHERE c.id=call_notes.id AND c.hotel=call_notes.hotel AND c.guest=call_notes.guest));
DROP POLICY IF EXISTS actor_turns ON concierge_turns;
CREATE POLICY actor_turns ON concierge_turns TO hotel_app USING(EXISTS(SELECT FROM hotel.call_notes n WHERE n.id=call_id));
COMMIT;
