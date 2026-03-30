-- Seed the current hardcoded report scores as baseline for comparison
-- Run this in Supabase SQL editor after create_audit_reports_table.sql

INSERT INTO marketing.audit_reports (domain, url, overall_score, scores, analysis_data, pages_analyzed, status, completed_at)
VALUES (
  'www.zadara.com',
  'https://www.zadara.com',
  44,
  '{"ai_visibility": 76, "content_eeat": 52, "technical": 76, "schema": 60, "brand": 42}',
  '{"source": "initial_report", "note": "Baseline from original GEO-SEO audit"}',
  1,
  'completed',
  '2026-03-09T00:00:00Z'
);
