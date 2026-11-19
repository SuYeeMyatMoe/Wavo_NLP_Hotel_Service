-- New calls only: existing rows deliberately have no invented timing.
CREATE TABLE IF NOT EXISTS call_timing (
 call_id text PRIMARY KEY REFERENCES calls(id),
 connected_at text, ended_at text, end_reason text
);
CREATE TRIGGER IF NOT EXISTS call_timing_insert AFTER INSERT ON calls
BEGIN
 INSERT INTO call_timing(call_id,connected_at)
 VALUES(NEW.id,CASE WHEN NEW.status='Connected' THEN strftime('%Y-%m-%dT%H:%M:%f+00:00','now') END);
END;
CREATE TRIGGER IF NOT EXISTS call_timing_status AFTER UPDATE OF status ON calls
BEGIN
 UPDATE call_timing SET
 connected_at=CASE WHEN NEW.status='Connected' AND ended_at IS NULL THEN COALESCE(connected_at,strftime('%Y-%m-%dT%H:%M:%f+00:00','now')) ELSE connected_at END,
 ended_at=CASE WHEN NEW.status IN ('Ended','Missed','Declined') THEN COALESCE(ended_at,strftime('%Y-%m-%dT%H:%M:%f+00:00','now')) ELSE ended_at END,
 end_reason=CASE WHEN NEW.status IN ('Ended','Missed','Declined') THEN COALESCE(end_reason,CASE WHEN NEW.status='Missed' THEN 'timeout' ELSE lower(NEW.status) END) ELSE end_reason END
 WHERE call_id=NEW.id;
END;
