\set ON_ERROR_STOP on
BEGIN;
\ir migrations/20261118144013_guest_activity_timing.sql
COMMIT;
