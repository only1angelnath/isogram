-- Enable RLS on every table and restrict anon/authenticated to read-only.
-- Confirmed exploitable before this migration: POST to
-- /rest/v1/projects with only the public anon key inserted a real row
-- into production with no auth at all (PostgREST's auto-exposed REST
-- layer, separate from and invisible to api/'s own route-level checks).
--
-- service_role (used only by ingestion/ and scoring/, server-side,
-- never shipped to a client) bypasses RLS by default in Postgres/Supabase,
-- so this does not touch those write paths.
--
-- No INSERT/UPDATE/DELETE policy is added for anon/authenticated on
-- purpose: with RLS enabled and no permissive policy for a given
-- command, that command is denied. This is default-deny, not
-- default-allow with holes.

ALTER TABLE "public"."projects" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."gas_events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."token_flows" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."project_scores" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."network_stats" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sync_state" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_read_only" ON "public"."projects"
    FOR SELECT TO "anon", "authenticated" USING (true);

CREATE POLICY "public_read_only" ON "public"."gas_events"
    FOR SELECT TO "anon", "authenticated" USING (true);

CREATE POLICY "public_read_only" ON "public"."token_flows"
    FOR SELECT TO "anon", "authenticated" USING (true);

CREATE POLICY "public_read_only" ON "public"."project_scores"
    FOR SELECT TO "anon", "authenticated" USING (true);

CREATE POLICY "public_read_only" ON "public"."network_stats"
    FOR SELECT TO "anon", "authenticated" USING (true);

-- sync_state is an internal ingestion checkpoint, not public-facing data
-- (never read by api/, bot/, or dashboard/) — no read policy for
-- anon/authenticated at all, so it's fully inaccessible to the public
-- REST layer now, matching what it already was to every legitimate
-- consumer in this codebase.
