CREATE TABLE IF NOT EXISTS call_starts (
 actor text NOT NULL REFERENCES profiles(id), request_key text NOT NULL,
 call_id text REFERENCES calls(id), cancelled integer NOT NULL DEFAULT 0,
 consent integer NOT NULL DEFAULT 0, created text NOT NULL,
 PRIMARY KEY(actor,request_key)
);
