SET LOCAL search_path TO hotel, public;
ALTER TABLE service_procedures ADD COLUMN IF NOT EXISTS completion_minutes integer CHECK(completion_minutes BETWEEN 1 AND 1440);
CREATE TABLE IF NOT EXISTS completion_estimates (
 assignment text PRIMARY KEY REFERENCES task_assignments(id),
 ticket text NOT NULL REFERENCES tickets(id), hotel text NOT NULL,
 expected_at text NOT NULL, source text NOT NULL, version integer NOT NULL DEFAULT 1,
 updated text NOT NULL, notified_version integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS completion_ticket ON completion_estimates(ticket);

ALTER TABLE completion_estimates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON completion_estimates FROM PUBLIC, anon, authenticated;
GRANT SELECT ON completion_estimates TO hotel_app;
CREATE POLICY own_completion ON completion_estimates FOR SELECT TO hotel_app
 USING(hotel=hotel.my_hotel() AND (hotel.manager() OR hotel.can_read_ticket(ticket)));
-- Only future demo AC assignments receive this estimate; no history is backfilled.
UPDATE service_procedures SET completion_minutes=15,version=version+1
 WHERE id='demo-ac' AND hotel='demo' AND completion_minutes IS NULL;
INSERT INTO operation_migrations VALUES('completion-demo-default-v1') ON CONFLICT DO NOTHING;
