-- Additive upgrade. Existing policy and vector records are preserved but are no longer searched.
SET search_path TO hotel,public;
CREATE TABLE IF NOT EXISTS service_procedures (
 id text PRIMARY KEY, hotel text NOT NULL, category text NOT NULL, department text NOT NULL,
 title text NOT NULL, body text NOT NULL, constraints text NOT NULL DEFAULT '[]',
 questions text NOT NULL DEFAULT '[]', approval text NOT NULL DEFAULT '', enabled integer NOT NULL DEFAULT 1,
 version integer NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS call_privacy (
 call_id text PRIMARY KEY REFERENCES calls(id), consent integer NOT NULL DEFAULT 0,
 updated text NOT NULL, notice_version text NOT NULL DEFAULT 'transcript-v1'
);
CREATE TABLE IF NOT EXISTS call_transcripts (
 id text PRIMARY KEY, call_id text NOT NULL REFERENCES calls(id), turn_id text NOT NULL,
 speaker text NOT NULL, original text NOT NULL, english text NOT NULL, language text NOT NULL,
 created text NOT NULL, UNIQUE(call_id,turn_id,speaker)
);
CREATE TABLE IF NOT EXISTS nlp_analysis (
 id text PRIMARY KEY, hotel text NOT NULL, call_id text REFERENCES calls(id), ticket text REFERENCES tickets(id),
 turn_id text NOT NULL DEFAULT '', payload text NOT NULL, created text NOT NULL
);
CREATE TABLE IF NOT EXISTS note_revisions (
 id text PRIMARY KEY, call_id text NOT NULL REFERENCES calls(id), version integer NOT NULL,
 author text NOT NULL, payload text NOT NULL, created text NOT NULL, UNIQUE(call_id,version)
);
CREATE INDEX IF NOT EXISTS analysis_call ON nlp_analysis(call_id,created);
CREATE INDEX IF NOT EXISTS transcript_call ON call_transcripts(call_id,created);

GRANT SELECT ON service_procedures,call_privacy,call_transcripts,nlp_analysis,note_revisions TO hotel_app;
GRANT INSERT,UPDATE ON service_procedures TO hotel_app;
GRANT INSERT ON call_privacy,call_transcripts,nlp_analysis,note_revisions TO hotel_app;
ALTER TABLE service_procedures ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS procedure_read ON service_procedures;
CREATE POLICY procedure_read ON service_procedures FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel());
DROP POLICY IF EXISTS procedure_manage ON service_procedures;
CREATE POLICY procedure_manage ON service_procedures TO hotel_app
USING(hotel=hotel.my_hotel() AND EXISTS(SELECT FROM profiles WHERE id=hotel.actor() AND role='manager'))
WITH CHECK(hotel=hotel.my_hotel() AND EXISTS(SELECT FROM profiles WHERE id=hotel.actor() AND role='manager'));
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['call_privacy','call_transcripts','note_revisions'] LOOP
 EXECUTE format('ALTER TABLE hotel.%I ENABLE ROW LEVEL SECURITY',tab);
 EXECUTE format('DROP POLICY IF EXISTS call_evidence_read ON hotel.%I',tab);
 EXECUTE format('CREATE POLICY call_evidence_read ON hotel.%I FOR SELECT TO hotel_app USING(EXISTS(SELECT FROM hotel.calls c WHERE c.id=call_id AND c.hotel=hotel.my_hotel() AND (hotel.staff() OR c.guest=hotel.actor())))',tab);
 END LOOP;
END $$;
DROP POLICY IF EXISTS privacy_create ON call_privacy;
CREATE POLICY privacy_create ON call_privacy FOR INSERT TO hotel_app WITH CHECK(consent=0 AND EXISTS(SELECT FROM calls c WHERE c.id=call_id AND c.guest=hotel.actor()));
DROP POLICY IF EXISTS transcript_create ON call_transcripts;
CREATE POLICY transcript_create ON call_transcripts FOR INSERT TO hotel_app WITH CHECK(EXISTS(SELECT FROM calls c JOIN call_privacy p ON p.call_id=c.id WHERE c.id=call_transcripts.call_id AND c.guest=hotel.actor() AND p.consent=1));
DROP POLICY IF EXISTS note_review ON note_revisions;
CREATE POLICY note_review ON note_revisions FOR INSERT TO hotel_app WITH CHECK(hotel.staff() AND author=hotel.actor() AND EXISTS(SELECT FROM calls c WHERE c.id=call_id AND c.hotel=hotel.my_hotel()));
ALTER TABLE nlp_analysis ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS analysis_read ON nlp_analysis;
CREATE POLICY analysis_read ON nlp_analysis FOR SELECT TO hotel_app USING(hotel=hotel.my_hotel() AND (hotel.staff() OR EXISTS(SELECT FROM calls c WHERE c.id=call_id AND c.guest=hotel.actor()) OR EXISTS(SELECT FROM tickets t WHERE t.id=ticket AND t.guest=hotel.actor())));
DROP POLICY IF EXISTS analysis_create ON nlp_analysis;
CREATE POLICY analysis_create ON nlp_analysis FOR INSERT TO hotel_app WITH CHECK(hotel=hotel.my_hotel() AND ((call_id IS NOT NULL AND EXISTS(SELECT FROM calls c WHERE c.id=call_id AND c.hotel=hotel.my_hotel() AND c.guest=hotel.actor())) OR (ticket IS NOT NULL AND EXISTS(SELECT FROM tickets t WHERE t.id=ticket AND t.hotel=hotel.my_hotel()))));
