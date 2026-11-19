CREATE TABLE IF NOT EXISTS service_times (
 hotel text NOT NULL, department text NOT NULL, minutes integer NOT NULL CHECK(minutes BETWEEN 0 AND 1440),
 PRIMARY KEY(hotel,department)
);
CREATE TABLE IF NOT EXISTS room_inventory (
 hotel text NOT NULL,room text NOT NULL,category text NOT NULL,ready integer NOT NULL CHECK(ready IN (0,1)),
 PRIMARY KEY(hotel,room)
);
CREATE TABLE IF NOT EXISTS call_notes (
 id text PRIMARY KEY REFERENCES calls(id),hotel text NOT NULL,guest text NOT NULL,room text NOT NULL,
 language text NOT NULL,engine text NOT NULL,issue text NOT NULL DEFAULT '',options text NOT NULL DEFAULT '',
 outcome text NOT NULL DEFAULT 'Listening',analysis text NOT NULL DEFAULT '{}',
 reply text NOT NULL DEFAULT '',eta integer,updated text NOT NULL,version integer NOT NULL DEFAULT 0,
 staff_id text NOT NULL DEFAULT '',offer text NOT NULL DEFAULT '',answer text NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS concierge_turns (
 call_id text NOT NULL REFERENCES call_notes(id), turn_id text NOT NULL, PRIMARY KEY(call_id,turn_id)
);
CREATE TABLE IF NOT EXISTS move_requests (
 call_id text PRIMARY KEY REFERENCES call_notes(id),decision text NOT NULL,room text NOT NULL DEFAULT ''
);
