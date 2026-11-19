-- Fix the helper's namespace; current_setting is resolved from pg_catalog.
ALTER FUNCTION hotel.actor() SET search_path = '';
