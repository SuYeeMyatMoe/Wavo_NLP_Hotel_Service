-- Apply once to an existing connected deployment, or via the initial installer.
BEGIN;
SET LOCAL search_path TO hotel, public;
CREATE TABLE IF NOT EXISTS voice_messages(ticket text PRIMARY KEY REFERENCES tickets(id), audio bytea NOT NULL);
CREATE TABLE IF NOT EXISTS guest_languages(guest text PRIMARY KEY REFERENCES profiles(id), language text NOT NULL);
REVOKE UPDATE ON voice_messages FROM hotel_app;
GRANT SELECT,INSERT ON voice_messages TO hotel_app;
GRANT SELECT,INSERT,UPDATE ON guest_languages TO hotel_app;
ALTER TABLE voice_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE guest_languages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_recording ON voice_messages;
CREATE POLICY own_recording ON voice_messages TO hotel_app
 USING(EXISTS(SELECT FROM hotel.tickets t WHERE t.id=voice_messages.ticket))
 WITH CHECK(EXISTS(SELECT FROM hotel.tickets t WHERE t.id=voice_messages.ticket AND t.guest=hotel.actor()));
DROP POLICY IF EXISTS own_language ON guest_languages;
CREATE POLICY own_language ON guest_languages TO hotel_app USING(guest=hotel.actor()) WITH CHECK(guest=hotel.actor());
COMMIT;
