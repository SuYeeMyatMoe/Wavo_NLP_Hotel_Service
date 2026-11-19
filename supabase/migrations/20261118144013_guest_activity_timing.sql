SET LOCAL search_path TO hotel, public;
CREATE TABLE IF NOT EXISTS call_timing (
 call_id text PRIMARY KEY REFERENCES calls(id),
 connected_at text, ended_at text, end_reason text
);
ALTER TABLE call_timing ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON call_timing FROM PUBLIC,anon,authenticated;
GRANT SELECT ON call_timing TO hotel_app;
CREATE POLICY own_call_timing ON call_timing FOR SELECT TO hotel_app
 USING(EXISTS(SELECT 1 FROM hotel.calls c WHERE c.id=call_id));

CREATE OR REPLACE FUNCTION hotel.capture_call_timing() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE stamp text := to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS') || '+00:00';
BEGIN
 IF TG_OP='INSERT' THEN
  INSERT INTO hotel.call_timing(call_id,connected_at)
  VALUES(NEW.id,CASE WHEN NEW.status='Connected' THEN stamp END);
 ELSE
  UPDATE hotel.call_timing SET
   connected_at=CASE WHEN NEW.status='Connected' AND ended_at IS NULL THEN COALESCE(connected_at,stamp) ELSE connected_at END,
   ended_at=CASE WHEN NEW.status IN ('Ended','Missed','Declined') THEN COALESCE(ended_at,stamp) ELSE ended_at END,
   end_reason=CASE WHEN NEW.status IN ('Ended','Missed','Declined') THEN COALESCE(end_reason,CASE WHEN NEW.status='Missed' THEN 'timeout' ELSE lower(NEW.status) END) ELSE end_reason END
  WHERE call_id=NEW.id;
 END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION hotel.capture_call_timing() FROM PUBLIC,anon,authenticated,hotel_app;
CREATE TRIGGER call_timing_insert AFTER INSERT ON calls FOR EACH ROW EXECUTE FUNCTION hotel.capture_call_timing();
CREATE TRIGGER call_timing_status AFTER UPDATE OF status ON calls FOR EACH ROW EXECUTE FUNCTION hotel.capture_call_timing();
-- No backfill: previous calls have no reliable connection or end timestamp.
