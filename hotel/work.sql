CREATE TABLE IF NOT EXISTS ticket_work (
 ticket text PRIMARY KEY REFERENCES tickets(id),owner text NOT NULL DEFAULT '',
 version integer NOT NULL DEFAULT 0,outcome text NOT NULL DEFAULT '',action text NOT NULL DEFAULT '',
 note text NOT NULL DEFAULT '',updated text NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS service_outcomes (
 id text PRIMARY KEY,ticket text NOT NULL REFERENCES tickets(id),staff text NOT NULL,
 outcome text NOT NULL,action text NOT NULL,note text NOT NULL,created text NOT NULL
);
