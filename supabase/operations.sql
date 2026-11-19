-- Private operational tables. Authenticated HTTP services own all mutations.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path TO hotel,public;
\ir ../hotel/operations.sql
CREATE OR REPLACE FUNCTION hotel.can_read_ticket(ref text) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT EXISTS(SELECT 1 FROM hotel.tickets t JOIN hotel.profiles p ON p.id=hotel.actor()
 WHERE t.id=ref AND t.hotel=p.hotel AND (p.role='manager' OR t.guest=p.id OR
 (p.role='staff' AND EXISTS(SELECT 1 FROM hotel.ticket_work w WHERE w.ticket=t.id AND w.owner=p.id))))
$$;
CREATE OR REPLACE FUNCTION hotel.manager() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT EXISTS(SELECT 1 FROM hotel.profiles WHERE id=hotel.actor() AND role='manager')
$$;
REVOKE ALL ON FUNCTION hotel.can_read_ticket(text),hotel.manager() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION hotel.can_read_ticket(text),hotel.manager() TO hotel_app;
DROP POLICY IF EXISTS ticket_read ON tickets;
CREATE POLICY ticket_read ON tickets FOR SELECT TO hotel_app USING(hotel.can_read_ticket(id));
DROP POLICY IF EXISTS ticket_change ON tickets;
CREATE POLICY ticket_change ON tickets FOR UPDATE TO hotel_app USING(hotel.can_read_ticket(id) AND hotel.staff()) WITH CHECK(hotel.can_read_ticket(id) AND hotel.staff());
DROP POLICY IF EXISTS hotel_calls ON calls;
CREATE POLICY hotel_calls ON calls TO hotel_app USING(hotel=hotel.my_hotel() AND (guest=hotel.actor() OR hotel.manager() OR hotel.can_read_ticket(ticket))) WITH CHECK(hotel=hotel.my_hotel() AND (guest=hotel.actor() OR hotel.manager() OR hotel.can_read_ticket(ticket)));
DROP POLICY IF EXISTS actor_notes ON call_notes;
CREATE POLICY actor_notes ON call_notes TO hotel_app
 USING (hotel=hotel.my_hotel() AND EXISTS(SELECT 1 FROM hotel.calls c WHERE c.id=call_notes.id))
 WITH CHECK (hotel=hotel.my_hotel() AND EXISTS(SELECT 1 FROM hotel.calls c WHERE c.id=call_notes.id AND c.guest=call_notes.guest));
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['service_lifecycle','task_assignments','agent_actions','guest_feedback'] LOOP
  EXECUTE format('ALTER TABLE hotel.%I ENABLE ROW LEVEL SECURITY',tab);
  EXECUTE format('GRANT SELECT ON hotel.%I TO hotel_app',tab);
  EXECUTE format('DROP POLICY IF EXISTS own_record ON hotel.%I',tab);
  EXECUTE format('CREATE POLICY own_record ON hotel.%I FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel() AND (hotel.manager() OR hotel.can_read_ticket(ticket)))',tab);
 END LOOP;
 FOREACH tab IN ARRAY ARRAY['reservations','staff_roster','service_policies','notifications','work_sessions','operation_jobs','work_turns','operation_migrations'] LOOP
  EXECUTE format('ALTER TABLE hotel.%I ENABLE ROW LEVEL SECURITY',tab);
 END LOOP;
END $$;
GRANT SELECT ON reservations,staff_roster,service_policies,notifications,work_sessions TO hotel_app;
DROP POLICY IF EXISTS reservation_read ON reservations;
CREATE POLICY reservation_read ON reservations FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel() AND (guest=hotel.actor() OR hotel.manager()));
DROP POLICY IF EXISTS roster_read ON staff_roster;
CREATE POLICY roster_read ON staff_roster FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel());
DROP POLICY IF EXISTS policy_read ON service_policies;
CREATE POLICY policy_read ON service_policies FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel() AND hotel.staff());
DROP POLICY IF EXISTS inbox_read ON notifications;
CREATE POLICY inbox_read ON notifications FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel() AND recipient=hotel.actor());
DROP POLICY IF EXISTS inbox_read_mark ON notifications;
CREATE POLICY inbox_read_mark ON notifications FOR UPDATE TO hotel_app USING(hotel=hotel.my_hotel() AND recipient=hotel.actor()) WITH CHECK(hotel=hotel.my_hotel() AND recipient=hotel.actor());
GRANT UPDATE(read_at) ON notifications TO hotel_app;
DROP POLICY IF EXISTS session_read ON work_sessions;
CREATE POLICY session_read ON work_sessions FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel() AND staff=hotel.actor());
-- Existing records are preserved; unresolved requests require supervisor review.
INSERT INTO service_lifecycle(ticket,hotel,state,reason,updated)
 SELECT t.id,t.hotel,CASE WHEN t.status IN ('Resolved','Closed') THEN 'resolved'
 WHEN w.owner<>'' AND t.status='In progress' THEN 'in_progress'
 WHEN w.owner<>'' AND t.status='Awaiting confirmation' THEN 'awaiting_confirmation'
 WHEN w.owner<>'' AND t.status='Assigned' THEN 'assigned' ELSE 'escalated' END,
 CASE WHEN w.owner<>'' THEN 'Legacy record preserved; original ownership and status retained' ELSE 'Migrated historical request; unresolved work requires supervisor review' END,t.created
 FROM tickets t LEFT JOIN ticket_work w ON w.ticket=t.id ON CONFLICT DO NOTHING;
INSERT INTO agent_actions(id,hotel,ticket,agent,action,result,actor,created,dedupe)
 SELECT 'legacy:'||t.id,t.hotel,t.id,'Migration','Legacy ownership preserved','No new assignment or deadline invented','Controller',t.created,'legacy:'||t.id
 FROM tickets t JOIN ticket_work w ON w.ticket=t.id JOIN service_lifecycle l ON l.ticket=t.id
 WHERE w.owner<>'' AND l.reason LIKE 'Legacy record preserved%' ON CONFLICT DO NOTHING;
UPDATE tickets SET status='Escalated' WHERE id IN (SELECT ticket FROM service_lifecycle WHERE state='escalated' AND reason LIKE 'Migrated historical%') AND status NOT IN ('Resolved','Closed');
INSERT INTO operation_migrations VALUES('autonomy-v1') ON CONFLICT DO NOTHING;
COMMIT;
-- Private per-user invalidation channels. Never broadcast complaint text.
DO $$ BEGIN
 IF to_regclass('realtime.messages') IS NOT NULL THEN
  EXECUTE 'DROP POLICY IF EXISTS wavo_inbox_broadcast ON realtime.messages';
  EXECUTE $policy$CREATE POLICY wavo_inbox_broadcast ON realtime.messages FOR SELECT TO authenticated
   USING(extension='broadcast' AND realtime.topic() = 'wavo:user:' || (SELECT auth.uid())::text)$policy$;
 END IF;
END $$;
