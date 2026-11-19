-- Private operational tables. Authenticated HTTP services own all mutations.
BEGIN;
SET LOCAL search_path TO hotel,public;
CREATE TABLE IF NOT EXISTS reservations (
 guest text PRIMARY KEY REFERENCES profiles(id), hotel text NOT NULL, room text NOT NULL,
 starts text NOT NULL, ends text NOT NULL, version integer NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS staff_roster (
 staff text PRIMARY KEY REFERENCES profiles(id), hotel text NOT NULL, name text NOT NULL,
 department text NOT NULL, skills text NOT NULL DEFAULT '[]', shift_start text NOT NULL,
 shift_end text NOT NULL, available integer NOT NULL DEFAULT 0, capacity integer NOT NULL DEFAULT 3,
 last_assigned text NOT NULL DEFAULT '', version integer NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS service_policies (
 hotel text NOT NULL, priority text NOT NULL, ack_minutes integer NOT NULL,
 service_minutes integer NOT NULL, version integer NOT NULL DEFAULT 1,
 PRIMARY KEY(hotel,priority)
);
CREATE TABLE IF NOT EXISTS service_lifecycle (
 ticket text PRIMARY KEY REFERENCES tickets(id), hotel text NOT NULL,
 state text NOT NULL CHECK(state IN ('new','needs_clarification','pending_assignment','assigned','in_progress','awaiting_confirmation','resolved','reopened','escalated')),
 version integer NOT NULL DEFAULT 1, reason text NOT NULL DEFAULT '', updated text NOT NULL
);
CREATE TABLE IF NOT EXISTS task_assignments (
 id text PRIMARY KEY, ticket text NOT NULL REFERENCES tickets(id), staff text NOT NULL REFERENCES profiles(id),
 hotel text NOT NULL, attempt integer NOT NULL, active integer NOT NULL DEFAULT 1,
 assigned text NOT NULL, acknowledged text NOT NULL DEFAULT '', ack_due text NOT NULL,
 service_due text NOT NULL, reminded text NOT NULL DEFAULT '', ended text NOT NULL DEFAULT '',
 reason text NOT NULL, UNIQUE(ticket,attempt)
);
CREATE UNIQUE INDEX IF NOT EXISTS assignment_one_active ON task_assignments(ticket) WHERE active=1;
CREATE INDEX IF NOT EXISTS assignment_worker ON task_assignments(staff,active);
CREATE TABLE IF NOT EXISTS notifications (
 id text PRIMARY KEY, hotel text NOT NULL, recipient text NOT NULL REFERENCES profiles(id),
 ticket text REFERENCES tickets(id), kind text NOT NULL, message text NOT NULL,
 created text NOT NULL, published text NOT NULL DEFAULT '', read_at text NOT NULL DEFAULT '',
 delivery text NOT NULL DEFAULT 'queued', dedupe text NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS operation_jobs (
 id text PRIMARY KEY REFERENCES notifications(id), due text NOT NULL, attempts integer NOT NULL DEFAULT 0,
 lease_until text NOT NULL DEFAULT '', lease_token text NOT NULL DEFAULT '', error text NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS agent_actions (
 id text PRIMARY KEY, hotel text NOT NULL, ticket text REFERENCES tickets(id), agent text NOT NULL,
 action text NOT NULL, result text NOT NULL, actor text NOT NULL, created text NOT NULL, dedupe text NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS work_turns (
 actor text NOT NULL, turn_id text NOT NULL, digest text NOT NULL, response text NOT NULL,
 created text NOT NULL, PRIMARY KEY(actor,turn_id)
);
CREATE TABLE IF NOT EXISTS guest_feedback (
 id text PRIMARY KEY, hotel text NOT NULL, ticket text NOT NULL REFERENCES tickets(id),
 guest text NOT NULL, resolved integer NOT NULL, version integer NOT NULL, created text NOT NULL,
 UNIQUE(ticket,version)
);
CREATE TABLE IF NOT EXISTS operation_migrations (id text PRIMARY KEY);
CREATE TABLE IF NOT EXISTS work_sessions (
 id text PRIMARY KEY, hotel text NOT NULL, staff text NOT NULL REFERENCES profiles(id),
 status text NOT NULL, created text NOT NULL
);
CREATE INDEX IF NOT EXISTS notification_inbox ON notifications(recipient,created);
CREATE INDEX IF NOT EXISTS jobs_due ON operation_jobs(due,lease_until);
CREATE INDEX IF NOT EXISTS activity_ticket ON agent_actions(hotel,ticket,created);

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
