-- Demo fixtures only. First create the four demo identities through Supabase Auth.
-- psql "$DATABASE_URL" -v guest_id=UUID -v maintenance_id=UUID -v backup_id=UUID -v manager_id=UUID -f supabase/seed.sql
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path TO hotel,public;
INSERT INTO profiles(id,hotel,role,room,staying_until) VALUES
 (:'guest_id','demo','guest','305','2099-01-01'),
 (:'maintenance_id','demo','staff','',''),
 (:'backup_id','demo','staff','',''),
 (:'manager_id','demo','manager','','') ON CONFLICT DO NOTHING;
INSERT INTO reservations VALUES(:'guest_id','demo','305','2020-01-01','2099-01-01',1) ON CONFLICT DO NOTHING;
INSERT INTO staff_roster(staff,hotel,name,department,skills,shift_start,shift_end,available,capacity) VALUES
 (:'maintenance_id','demo','Aung · Maintenance','Maintenance','["Air conditioning","Plumbing","Electrical"]','2020-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00',1,3),
 (:'backup_id','demo','Maya · Maintenance','Maintenance','["Air conditioning","Plumbing","Electrical"]','2020-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00',1,3) ON CONFLICT DO NOTHING;
INSERT INTO service_policies VALUES ('demo','Urgent',2,15,1),('demo','Moderate',5,30,1),('demo','Low',10,60,1) ON CONFLICT DO NOTHING;
INSERT INTO service_procedures(id,hotel,category,department,title,body,approval,completion_minutes) VALUES
 ('demo-ac','demo','Air conditioning','Maintenance','Quiet AC repair','Confirm access and quiet-service preferences. Inspect the AC, repair the fault, test cooling and request guest confirmation.','Room moves require front-desk approval.',15),
 ('demo-plumbing','demo','Plumbing','Maintenance','Plumbing repair','Confirm the fixture and access. Inspect, repair and test for leaks.','',NULL),
 ('demo-wifi','demo','Wi-Fi','Front Desk','Guest Wi-Fi connection','Select Hotel-Guest in Wi-Fi settings. Open a browser and choose Guest access on the welcome page.','',NULL),
 ('demo-housekeeping','demo','Housekeeping','Housekeeping','Housekeeping service','Confirm items and access permission. Deliver items and ask the guest to confirm.','',NULL) ON CONFLICT DO NOTHING;
INSERT INTO service_times VALUES('demo','Maintenance',15) ON CONFLICT DO NOTHING;
\ir migrations/20261120053741_demo_electrical_procedure.sql
INSERT INTO room_inventory VALUES('demo','305','Standard',0),('demo','308','Standard',1) ON CONFLICT DO NOTHING;
COMMIT;
