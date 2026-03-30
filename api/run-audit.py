"""
GEO-SEO Audit Orchestrator — Vercel Serverless Function
Coordinates data collection and all scoring functions to produce a complete audit.
Called by the Re-Analyze button in the report UI.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# Supabase config
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')

# GEO score weights
SCORE_WEIGHTS = {
    'ai_visibility': 0.25,
    'content_eeat': 0.20,
    'technical': 0.15,
    'schema': 0.10,
    'brand': 0.20,
    'platform': 0.10,
}


def supabase_request(method, path, data=None):
    """Make an authenticated request to Supabase REST API (marketing schema)."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    # Use Accept-Profile to target the marketing schema
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('apikey', SUPABASE_SERVICE_KEY)
    req.add_header('Authorization', f'Bearer {SUPABASE_SERVICE_KEY}')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Prefer', 'return=representation')
    req.add_header('Accept-Profile', 'marketing')
    req.add_header('Content-Profile', 'marketing')
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Supabase error: {e}")
        return None


def call_scoring_function(base_url, endpoint, payload):
    """Call an internal scoring function and return its result."""
    url = f"{base_url}/api/{endpoint}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    start = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read().decode())
        elapsed = round(time.time() - start, 2)
        ai_flag = result.get('ai_powered', 'n/a')
        print(f"[AUDIT] {endpoint} completed in {elapsed}s | score={result.get('score', '?')} | ai_powered={ai_flag}")
        if result.get('error'):
            print(f"[AUDIT] {endpoint} returned error: {result['error']}")
        result['_elapsed_s'] = elapsed
        return result
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        print(f"[AUDIT] {endpoint} FAILED after {elapsed}s: {e}")
        return {"score": 0, "error": str(e), "_elapsed_s": elapsed}


def extract_domain(url):
    """Extract domain from URL."""
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc or parsed.path.split('/')[0]


def extract_brand_name(domain, page_data):
    """Try to extract brand name from page data or domain."""
    if page_data and page_data.get('title'):
        title = page_data['title']
        # Take first part before common separators
        for sep in [' | ', ' - ', ' — ', ' – ', ' :: ']:
            if sep in title:
                return title.split(sep)[0].strip()
        return title.strip()
    # Fallback: clean domain name
    name = domain.replace('www.', '').split('.')[0]
    return name.capitalize()


def get_score_color(score):
    """Get color category for a score."""
    if score >= 80:
        return 'green'
    elif score >= 60:
        return 'yellow'
    elif score >= 40:
        return 'orange'
    return 'red'


def get_score_label(score):
    """Get label for a score."""
    if score >= 80:
        return 'Excellent'
    elif score >= 60:
        return 'Good'
    elif score >= 40:
        return 'Below Average'
    return 'Critical'


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_POST(self):
        try:
            audit_start = time.time()
            content_length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            url = body.get('url', '').strip()
            triggered_by = body.get('triggered_by')

            if not url:
                self.send_error_response(400, 'URL is required')
                return

            # Ensure URL has scheme
            if not url.startswith('http'):
                url = f'https://{url}'

            domain = extract_domain(url)
            base_url = f"https://{self.headers.get('Host', 'localhost')}"

            print(f"[AUDIT] ====== STARTING AUDIT for {domain} ======")
            print(f"[AUDIT] URL: {url} | triggered_by: {triggered_by}")
            print(f"[AUDIT] Base URL for internal calls: {base_url}")

            # Step 1: Create audit_reports row with status='running'
            report_id = None
            if SUPABASE_URL and SUPABASE_SERVICE_KEY:
                rows = supabase_request('POST', 'audit_reports', {
                    'domain': domain,
                    'url': url,
                    'status': 'running',
                    'triggered_by': triggered_by,
                    'scores': {},
                    'analysis_data': {},
                })
                if rows and len(rows) > 0:
                    report_id = rows[0]['id']

            # Step 2: Collect raw data
            print(f"[AUDIT] Step 2: Collecting raw data...")
            collect_result = call_scoring_function(base_url, 'collect-audit-data', {'url': url})
            if collect_result.get('error') and not collect_result.get('page_data'):
                error_msg = collect_result.get('error', 'Data collection failed')
                if report_id:
                    supabase_request('PATCH',
                        f'audit_reports?id=eq.{report_id}',
                        {'status': 'failed', 'error_message': error_msg}
                    )
                self.send_error_response(500, error_msg)
                return

            page_data = collect_result.get('page_data', {})
            robots_data = collect_result.get('robots_data', {})
            llms_data = collect_result.get('llms_data', {})
            content_blocks = collect_result.get('content_blocks', [])
            brand_name = extract_brand_name(domain, page_data)

            print(f"[AUDIT] Data collected: word_count={page_data.get('word_count', 0)}, "
                  f"content_blocks={len(content_blocks)}, "
                  f"robots_exists={robots_data.get('exists', False)}, "
                  f"brand_name={brand_name}")

            # Step 3: Run all scoring functions in parallel
            print(f"[AUDIT] Step 3: Launching 5 scoring functions in parallel...")
            scoring_payload = {
                'page_data': page_data,
                'robots_data': robots_data,
                'llms_data': llms_data,
                'content_blocks': content_blocks,
                'domain': domain,
                'brand_name': brand_name,
            }

            results = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(call_scoring_function, base_url, 'score-ai-visibility', scoring_payload): 'ai_visibility',
                    executor.submit(call_scoring_function, base_url, 'score-technical', scoring_payload): 'technical',
                    executor.submit(call_scoring_function, base_url, 'score-schema', scoring_payload): 'schema',
                    executor.submit(call_scoring_function, base_url, 'score-content-ai', scoring_payload): 'content_eeat',
                    executor.submit(call_scoring_function, base_url, 'score-brand-ai', scoring_payload): 'brand',
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        results[key] = future.result()
                    except Exception as e:
                        results[key] = {"score": 0, "error": str(e)}

            # Log scoring results summary
            print(f"[AUDIT] ---- Scoring Results Summary ----")
            for key, res in results.items():
                print(f"[AUDIT]   {key}: score={res.get('score', '?')} | "
                      f"ai_powered={res.get('ai_powered', 'n/a')} | "
                      f"elapsed={res.get('_elapsed_s', '?')}s | "
                      f"error={res.get('error', 'none')}")

            # Step 4: Calculate composite GEO score
            scores = {}
            for key, weight in SCORE_WEIGHTS.items():
                result = results.get(key, {})
                score = result.get('score', 0)
                scores[key] = round(float(score), 1)

            # For brand+platform, combine them
            # brand result includes platform scores
            brand_result = results.get('brand', {})
            platform_avg = brand_result.get('breakdown', {}).get('platform_average', scores.get('brand', 0))

            overall_score = round(
                scores.get('ai_visibility', 0) * SCORE_WEIGHTS['ai_visibility'] +
                scores.get('content_eeat', 0) * SCORE_WEIGHTS['content_eeat'] +
                scores.get('technical', 0) * SCORE_WEIGHTS['technical'] +
                scores.get('schema', 0) * SCORE_WEIGHTS['schema'] +
                scores.get('brand', 0) * SCORE_WEIGHTS['brand'] +
                float(platform_avg) * SCORE_WEIGHTS['platform'],
                1
            )

            print(f"[AUDIT] ---- Score Breakdown ----")
            print(f"[AUDIT]   ai_visibility: {scores.get('ai_visibility', 0)} * 0.25 = {scores.get('ai_visibility', 0) * 0.25}")
            print(f"[AUDIT]   content_eeat:  {scores.get('content_eeat', 0)} * 0.20 = {scores.get('content_eeat', 0) * 0.20}")
            print(f"[AUDIT]   technical:     {scores.get('technical', 0)} * 0.15 = {scores.get('technical', 0) * 0.15}")
            print(f"[AUDIT]   schema:        {scores.get('schema', 0)} * 0.10 = {scores.get('schema', 0) * 0.10}")
            print(f"[AUDIT]   brand:         {scores.get('brand', 0)} * 0.20 = {scores.get('brand', 0) * 0.20}")
            print(f"[AUDIT]   platform_avg:  {platform_avg} * 0.10 = {float(platform_avg) * 0.10}")
            print(f"[AUDIT]   OVERALL: {overall_score}")

            # Build the complete result
            audit_result = {
                'id': report_id,
                'domain': domain,
                'url': url,
                'overall_score': overall_score,
                'overall_label': get_score_label(overall_score),
                'overall_color': get_score_color(overall_score),
                'scores': {
                    'ai_visibility': scores.get('ai_visibility', 0),
                    'content_eeat': scores.get('content_eeat', 0),
                    'technical': scores.get('technical', 0),
                    'schema': scores.get('schema', 0),
                    'brand': scores.get('brand', 0),
                },
                'analysis_data': {
                    'ai_visibility': results.get('ai_visibility', {}),
                    'content_eeat': results.get('content_eeat', {}),
                    'technical': results.get('technical', {}),
                    'schema': results.get('schema', {}),
                    'brand': results.get('brand', {}),
                },
                'pages_analyzed': 1,  # Homepage analysis
                'brand_name': brand_name,
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'diagnostics': {
                    'total_elapsed_s': round(time.time() - audit_start, 2),
                    'google_api_key_detected': any(
                        res.get('api_key_detected') is True
                        for res in results.values()
                    ),
                    'scorers': {
                        key: {
                            'score': res.get('score', 0),
                            'ai_powered': res.get('ai_powered', 'n/a'),
                            'method': res.get('method', 'deterministic'),
                            'api_key_detected': res.get('api_key_detected', 'n/a'),
                            'elapsed_s': res.get('_elapsed_s', 0),
                            'error': res.get('error'),
                            'key_findings': (res.get('key_findings') or [])[:3],
                        }
                        for key, res in results.items()
                    },
                    'data_collection': {
                        'word_count': page_data.get('word_count', 0),
                        'content_blocks': len(content_blocks),
                        'robots_exists': robots_data.get('exists', False),
                        'collect_elapsed_s': collect_result.get('_elapsed_s', 0),
                    },
                },
            }

            total_elapsed = round(time.time() - audit_start, 2)
            print(f"[AUDIT] ====== AUDIT COMPLETE for {domain} in {total_elapsed}s | overall={overall_score} ======")

            # Step 5: Update audit_reports row
            if report_id:
                supabase_request('PATCH',
                    f'audit_reports?id=eq.{report_id}',
                    {
                        'overall_score': overall_score,
                        'scores': audit_result['scores'],
                        'analysis_data': audit_result['analysis_data'],
                        'pages_analyzed': 1,
                        'status': 'completed',
                        'completed_at': audit_result['created_at'],
                    }
                )

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(audit_result).encode())

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error_response(500, str(e))

    def send_error_response(self, status, message):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'error': message}).encode())
