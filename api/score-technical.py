"""
Technical SEO Scorer — Vercel Serverless Function.
Deterministic scoring: SSR, meta tags, security, crawlability, CWV, mobile, URL structure.
"""
from http.server import BaseHTTPRequestHandler
import json
import re
from urllib.parse import urlparse

# Category weights from geo-technical.md
WEIGHTS = {
    "ssr": 0.25, "meta_tags": 0.15, "crawlability": 0.15,
    "security": 0.10, "cwv_risk": 0.10, "mobile": 0.10,
    "url_structure": 0.05, "response": 0.05, "additional": 0.05,
}


def score_ssr(page_data):
    """Score server-side rendering / JS dependency (0-100)."""
    has_ssr = page_data.get("has_ssr_content", True)
    text_content = page_data.get("text_content", "")
    word_count = page_data.get("word_count", 0)
    errors = page_data.get("errors", [])

    # Check for framework indicators
    headers = page_data.get("headers", {})
    server = headers.get("server", headers.get("Server", "")).lower()
    has_next = "__NEXT_DATA__" in text_content or "next" in server
    has_nuxt = "__NUXT__" in text_content

    if not has_ssr:
        status = "CRITICAL"
        score = 20
    elif has_next or has_nuxt:
        status = "LOW_RISK"
        score = 95
    elif word_count > 500:
        status = "LOW_RISK"
        score = 90
    elif word_count > 100:
        status = "MEDIUM"
        score = 70
    else:
        status = "HIGH"
        score = 40

    framework = "Next.js" if has_next else "Nuxt.js" if has_nuxt else "Unknown"
    return {"score": score, "status": status, "framework": framework, "word_count": word_count}


def score_meta_tags(page_data):
    """Score meta tags completeness (0-100)."""
    score = 0
    meta = page_data.get("meta_tags", {})
    title = page_data.get("title", "")
    desc = page_data.get("description", "")
    canonical = page_data.get("canonical")
    missing = []

    # Title (25 pts)
    if title:
        tlen = len(title)
        if 50 <= tlen <= 60: score += 25
        elif 30 <= tlen <= 70: score += 20
        else: score += 10
    else:
        missing.append("title")

    # Description (25 pts)
    if desc:
        dlen = len(desc)
        if 150 <= dlen <= 160: score += 25
        elif 100 <= dlen <= 200: score += 20
        else: score += 10
    else:
        missing.append("description")

    # Canonical (15 pts)
    if canonical: score += 15
    else: missing.append("canonical")

    # Viewport (10 pts)
    if meta.get("viewport"): score += 10
    else: missing.append("viewport")

    # Lang (10 pts)
    # Can't check directly from meta_tags, give benefit of doubt
    score += 10

    # OG tags (10 pts)
    og_tags = [k for k in meta if k.startswith("og:")]
    if len(og_tags) >= 3: score += 10
    elif len(og_tags) >= 1: score += 5
    else: missing.append("og:tags")

    # Twitter (5 pts)
    tw_tags = [k for k in meta if k.startswith("twitter:")]
    if tw_tags: score += 5
    else: missing.append("twitter:card")

    return {"score": min(score, 100), "missing": missing}


def score_security(page_data):
    """Score security headers (0-100)."""
    score = 100
    sec = page_data.get("security_headers", {})
    url = page_data.get("url", "")
    missing = []

    if not url.startswith("https"):
        score -= 30; missing.append("HTTPS")
    if not sec.get("Strict-Transport-Security"):
        score -= 10; missing.append("HSTS")
    if not sec.get("Content-Security-Policy"):
        score -= 10; missing.append("CSP")
    if not sec.get("X-Frame-Options"):
        score -= 5; missing.append("X-Frame-Options")
    if not sec.get("X-Content-Type-Options"):
        score -= 5; missing.append("X-Content-Type-Options")
    if not sec.get("Referrer-Policy"):
        score -= 5; missing.append("Referrer-Policy")
    if not sec.get("Permissions-Policy"):
        score -= 3; missing.append("Permissions-Policy")

    return {"score": max(score, 0), "missing": missing}


def score_crawlability(robots_data):
    """Score crawlability from robots.txt and sitemap (0-100)."""
    score = 0
    if robots_data.get("exists"):
        score += 40
    if robots_data.get("sitemaps"):
        score += 30
    # Check no critical blocks
    statuses = robots_data.get("ai_crawler_status", {})
    blocked = [k for k, v in statuses.items() if v in ("BLOCKED", "BLOCKED_BY_WILDCARD")]
    if not blocked:
        score += 30
    elif len(blocked) <= 2:
        score += 15
    return {"score": min(score, 100), "has_robots": robots_data.get("exists", False),
            "has_sitemap": bool(robots_data.get("sitemaps")), "blocked_crawlers": blocked}


def score_cwv_risk(page_data):
    """Estimate Core Web Vitals risk from HTML analysis (0-100)."""
    score = 80  # Default moderate
    images = page_data.get("images", [])
    risk_level = "LOW"

    # LCP: images without dimensions
    imgs_no_dims = sum(1 for img in images if not img.get("width") or not img.get("height"))
    if imgs_no_dims > 3:
        score -= 15; risk_level = "MEDIUM"
    elif imgs_no_dims > 0:
        score -= 5

    # CLS: images without dimensions also affect CLS
    if imgs_no_dims > 5:
        score -= 10; risk_level = "HIGH"

    return {"score": max(score, 0), "risk_level": risk_level}


def score_mobile(page_data):
    """Score mobile optimization (0-100)."""
    meta = page_data.get("meta_tags", {})
    score = 0
    if meta.get("viewport"):
        score += 50
        if "width=device-width" in meta.get("viewport", ""):
            score += 30
    # Responsive indicators are hard to detect from meta alone
    score += 20  # Benefit of doubt for modern sites
    return {"score": min(score, 100)}


def score_url_structure(url):
    """Score URL structure (0-100)."""
    parsed = urlparse(url)
    path = parsed.path
    score = 80

    # Check for query params
    if parsed.query:
        score -= 15
    # Check for session-like IDs
    if re.search(r"[a-f0-9]{32}", path):
        score -= 20
    # Check for clean slugs
    if path and re.match(r"^(/[a-z0-9-]+)+/?$", path):
        score += 10
    # Check depth
    depth = len([p for p in path.split("/") if p])
    if depth > 4:
        score -= 10
    # Mixed case
    if path != path.lower():
        score -= 5

    return {"score": max(min(score, 100), 0), "path": path, "depth": depth}


def score_response(page_data):
    """Score response headers and status (0-100)."""
    status = page_data.get("status_code", 200)
    redirects = page_data.get("redirect_chain", [])
    score = 100
    if status != 200:
        score -= 30
    if len(redirects) > 1:
        score -= 10 * (len(redirects) - 1)
    return {"score": max(score, 0), "status_code": status, "redirect_count": len(redirects)}


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            page_data = body.get("page_data", {})
            robots_data = body.get("robots_data", {})

            ssr = score_ssr(page_data)
            meta = score_meta_tags(page_data)
            security = score_security(page_data)
            crawl = score_crawlability(robots_data)
            cwv = score_cwv_risk(page_data)
            mobile = score_mobile(page_data)
            url_struct = score_url_structure(page_data.get("url", ""))
            response = score_response(page_data)
            additional = {"score": 80}  # Default for additional checks

            # Calculate weighted total
            breakdown = {
                "ssr": {**ssr, "weighted": round(ssr["score"] * WEIGHTS["ssr"], 1)},
                "meta_tags": {**meta, "weighted": round(meta["score"] * WEIGHTS["meta_tags"], 1)},
                "crawlability": {**crawl, "weighted": round(crawl["score"] * WEIGHTS["crawlability"], 1)},
                "security": {**security, "weighted": round(security["score"] * WEIGHTS["security"], 1)},
                "cwv_risk": {**cwv, "weighted": round(cwv["score"] * WEIGHTS["cwv_risk"], 1)},
                "mobile": {**mobile, "weighted": round(mobile["score"] * WEIGHTS["mobile"], 1)},
                "url_structure": {**url_struct, "weighted": round(url_struct["score"] * WEIGHTS["url_structure"], 1)},
                "response": {**response, "weighted": round(response["score"] * WEIGHTS["response"], 1)},
                "additional": {**additional, "weighted": round(additional["score"] * WEIGHTS["additional"], 1)},
            }

            total = sum(v["weighted"] for v in breakdown.values())

            result = {"score": round(total, 1), "breakdown": breakdown}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e), "score": 0}).encode())
