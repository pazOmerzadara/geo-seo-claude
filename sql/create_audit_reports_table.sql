-- Audit Reports table for storing GEO analysis history
-- Run this manually in Supabase SQL editor

CREATE TABLE IF NOT EXISTS marketing.audit_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain TEXT NOT NULL,
  url TEXT NOT NULL,
  overall_score NUMERIC(5,2),
  scores JSONB NOT NULL DEFAULT '{}',
  analysis_data JSONB NOT NULL DEFAULT '{}',
  pages_analyzed INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'completed', 'failed')),
  triggered_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_reports_domain
  ON marketing.audit_reports(domain, created_at DESC);

-- RLS policies
ALTER TABLE marketing.audit_reports ENABLE ROW LEVEL SECURITY;

-- All authenticated users can read audit reports
CREATE POLICY "authenticated_users_can_read_audits"
  ON marketing.audit_reports FOR SELECT
  USING (auth.role() = 'authenticated');

-- Authenticated users can insert their own reports
CREATE POLICY "authenticated_users_can_insert_audits"
  ON marketing.audit_reports FOR INSERT
  WITH CHECK (auth.role() = 'authenticated');

-- Users can update reports they triggered (or any authenticated user for API updates)
CREATE POLICY "authenticated_users_can_update_audits"
  ON marketing.audit_reports FOR UPDATE
  USING (auth.role() = 'authenticated');
