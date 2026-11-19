CREATE TABLE IF NOT EXISTS profiles (
 id text PRIMARY KEY, hotel text NOT NULL, role text NOT NULL CHECK(role IN ('staff','manager','guest')),
 room text NOT NULL DEFAULT '', staying_until text NOT NULL DEFAULT '', consent integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tickets (
 id text PRIMARY KEY, hotel text NOT NULL, author text NOT NULL, request_key text NOT NULL,
 guest text REFERENCES profiles(id), room text NOT NULL, source text NOT NULL,
 complaint text NOT NULL, urgency text NOT NULL, department text NOT NULL, operator text NOT NULL,
 status text NOT NULL, analysis text NOT NULL, created text NOT NULL,
 UNIQUE(author, request_key)
);
CREATE TABLE IF NOT EXISTS events (
 id text PRIMARY KEY, ticket text NOT NULL REFERENCES tickets(id), action text NOT NULL,
 actor text NOT NULL, created text NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
 id text PRIMARY KEY, hotel text NOT NULL, guest text NOT NULL REFERENCES profiles(id),
 ticket text REFERENCES tickets(id), direction text NOT NULL, status text NOT NULL,
 operator text NOT NULL, created text NOT NULL, transcript text NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS calls_one_active_v2 ON calls(guest) WHERE status IN ('Ringing','Connecting','Connected');
CREATE INDEX IF NOT EXISTS tickets_queue ON tickets(hotel, status, created);
CREATE TABLE IF NOT EXISTS voice_messages (
 ticket text PRIMARY KEY REFERENCES tickets(id), audio bytea NOT NULL
);
CREATE TABLE IF NOT EXISTS guest_languages (
 guest text PRIMARY KEY REFERENCES profiles(id), language text NOT NULL
);
CREATE TABLE IF NOT EXISTS operators (
 hotel text NOT NULL, department text NOT NULL, name text NOT NULL, PRIMARY KEY(hotel,department)
);
CREATE TABLE IF NOT EXISTS policies (
 id text PRIMARY KEY, hotel text NOT NULL, title text NOT NULL, body text NOT NULL
);

