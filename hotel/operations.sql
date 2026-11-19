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
