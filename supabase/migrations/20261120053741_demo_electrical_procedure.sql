-- Add the missing demo procedure without competing with hotel-customized guidance.
INSERT INTO hotel.service_procedures(id,hotel,category,department,title,body)
SELECT 'demo-electrical','demo','Electrical','Maintenance','Lighting and electrical repair',
 'Confirm the affected light or fixture and room access permission. A qualified maintenance worker must inspect and repair the fault, test the lighting, and ask the guest to confirm. Escalate sparks, exposed wires, smoke, or electric shock for urgent safety review.'
WHERE NOT EXISTS (
 SELECT 1 FROM hotel.service_procedures WHERE hotel='demo' AND category='Electrical'
)
ON CONFLICT DO NOTHING;
