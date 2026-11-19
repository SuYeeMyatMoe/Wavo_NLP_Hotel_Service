CREATE TABLE IF NOT EXISTS completion_estimates (
 assignment text PRIMARY KEY REFERENCES task_assignments(id),
 ticket text NOT NULL REFERENCES tickets(id), hotel text NOT NULL,
 expected_at text NOT NULL, source text NOT NULL, version integer NOT NULL DEFAULT 1,
 updated text NOT NULL, notified_version integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS completion_ticket ON completion_estimates(ticket);
