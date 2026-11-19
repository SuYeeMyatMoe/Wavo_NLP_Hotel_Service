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
