BEGIN;
SET LOCAL search_path=hotel,public;
CREATE TABLE IF NOT EXISTS call_starts (
 actor text NOT NULL REFERENCES profiles(id), request_key text NOT NULL,
 call_id text REFERENCES calls(id), cancelled integer NOT NULL DEFAULT 0,
 consent integer NOT NULL DEFAULT 0, created text NOT NULL,
 PRIMARY KEY(actor,request_key)
);
CREATE INDEX IF NOT EXISTS call_starts_call ON call_starts(call_id);
ALTER TABLE call_starts ENABLE ROW LEVEL SECURITY;
-- Only the authenticated, ownership-checked backend startup service writes here.
REVOKE ALL ON call_starts FROM PUBLIC,anon,authenticated,hotel_app;
COMMIT;
