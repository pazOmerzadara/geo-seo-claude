"""
Content Quality & E-E-A-T Scorer — Vercel Serverless Function.
Uses Gemini API for AI-powered content analysis with deterministic fallback.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import time
import urllib.request
import urllib.error


def deterministic_content_score(page_data, content_blocks):
    """Fallback deterministic scoring when AI is unavailable."""
    word_count = page_data.get("word_count", 0)
    headings = page_data.get("heading_structure", [])
    ext_links = page_data.get("external_links", [])
    images = page_data.get("images", [])
    meta = page_data.get("meta_tags", {})

    # Word count score
    if word_count < 300: wc_score = 20
    elif word_count < 800: wc_score = 50
    elif word_count < 1500: wc_score = 70
    elif word_count < 3000: wc_score = 90
    else: wc_score = 80

    # Heading density
    h_count = len(headings)
    ideal_headings = word_count / 250
    if ideal_headings > 0:
        h_ratio = h_count / ideal_headings
        if 0.5 <= h_ratio <= 2: heading_score = 80
        else: heading_score = 50
    else:
        heading_score = 40

    # External citations
    cite_score = min(len(ext_links) * 10, 80)

    # Images with alt text
    imgs_with_alt = sum(1 for img in images if img.get("alt"))
    img_score = min(imgs_with_alt * 15, 80) if images else 30

    # Content metrics composite
    content_metrics = round((wc_score * 0.4 + heading_score * 0.3 + cite_score * 0.2 + img_score * 0.1))

    # Basic E-E-A-T estimates
    experience = 10  # Can't assess without AI
    expertise = 10
    authoritativeness = 10
    trustworthiness = 12 if page_data.get("url", "").startswith("https") else 5

    # Boost if author info detected
    text = page_data.get("text_content", "").lower()
    if any(kw in text for kw in ["author", "written by", "by "]):
        expertise += 5
    if any(kw in text for kw in ["case study", "our research", "we found"]):
        experience += 5

    eeat_total = experience + expertise + authoritativeness + trustworthiness

    # Combined score using weights from geo-content.md
    score = round(
        (experience / 25 * 15) +
        (expertise / 25 * 15) +
        (authoritativeness / 25 * 15) +
        (trustworthiness / 25 * 15) +
        (content_metrics / 100 * 15) +
        (70 / 100 * 10) +  # AI content default
        (50 / 100 * 10) +  # Topical authority default
        (60 / 100 * 5)     # Freshness default
    )

    return {
        "score": score,
        "breakdown": {
            "experience": {"score": experience, "max": 25, "evidence": "Limited assessment without AI"},
            "expertise": {"score": expertise, "max": 25, "evidence": "Limited assessment without AI"},
            "authoritativeness": {"score": authoritativeness, "max": 25, "evidence": "Limited assessment without AI"},
            "trustworthiness": {"score": trustworthiness, "max": 25, "evidence": "HTTPS present" if trustworthiness > 10 else "No HTTPS"},
            "eeat_total": eeat_total,
            "content_metrics": {"score": content_metrics, "word_count": word_count, "readability": "standard"},
            "ai_content": {"assessment": "unknown", "score": 70},
            "topical_authority": {"assessment": "unknown", "score": 50},
            "freshness": {"assessment": "unknown", "score": 60},
        },
        "key_findings": ["AI scoring unavailable — using deterministic fallback"],
        "ai_powered": False,
    }


def call_gemini_api(api_key, page_data, content_blocks):
    """Call Gemini API for E-E-A-T analysis."""
    title = page_data.get("title", "Unknown")
    url = page_data.get("url", "")
    word_count = page_data.get("word_count", 0)
    text = page_data.get("text_content", "")[:8000]
    headings = [h.get("text", "") for h in page_data.get("heading_structure", [])[:20]]
    ext_count = len(page_data.get("external_links", []))
    img_count = len(page_data.get("images", []))

    prompt = f"""Analyze this webpage content and score it for E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness).

URL: {url}
Title: {title}
Word Count: {word_count}
External links: {ext_count}
Images: {img_count}
Headings: {json.dumps(headings[:15])}

Content (first 8000 chars):
{text}

Score each dimension 0-25 and provide brief evidence. Also assess:
- AI content likelihood: human, likely_human_edited, likely_ai_light_edit, likely_unedited_ai
- Topical authority: strong, moderate, weak, minimal
- Content freshness: current, aging, stale, unknown

Return ONLY valid JSON (no markdown, no explanation):
{{"experience": {{"score": 0, "evidence": "..."}}, "expertise": {{"score": 0, "evidence": "..."}}, "authoritativeness": {{"score": 0, "evidence": "..."}}, "trustworthiness": {{"score": 0, "evidence": "..."}}, "ai_content_assessment": "human", "topical_authority": "moderate", "content_freshness": "current", "key_findings": ["...", "..."]}}"""

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
    }).encode()

    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    req = urllib.request.Request(
        api_url,
        data=body,
        headers={'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read().decode())

    response_text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")

    # Try to parse JSON from response (Gemini sometimes wraps in markdown)
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        return json.loads(json_match.group())
    return json.loads(response_text)


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
            content_blocks = body.get("content_blocks", [])

            api_key = os.environ.get("GOOGLE_API_KEY", "")

            print(f"[CONTENT-AI] GOOGLE_API_KEY present: {bool(api_key)} (length={len(api_key)})")
            print(f"[CONTENT-AI] page_data word_count={page_data.get('word_count', 0)}, "
                  f"content_blocks={len(content_blocks)}")

            api_key_detected = bool(api_key)

            if not api_key:
                print(f"[CONTENT-AI] NO API KEY — using deterministic fallback")
                result = deterministic_content_score(page_data, content_blocks)
                result["api_key_detected"] = False
                result["method"] = "deterministic"
                result["key_findings"] = ["GOOGLE_API_KEY not configured in Vercel — using rule-based scoring"]
            else:
                try:
                    print(f"[CONTENT-AI] Calling Gemini API...")
                    gemini_start = time.time()
                    ai_result = call_gemini_api(api_key, page_data, content_blocks)

                    gemini_elapsed = round(time.time() - gemini_start, 2)
                    print(f"[CONTENT-AI] Gemini API responded in {gemini_elapsed}s")
                    print(f"[CONTENT-AI] Gemini result keys: {list(ai_result.keys())}")

                    # Calculate deterministic content metrics
                    word_count = page_data.get("word_count", 0)
                    if word_count < 300: wc_score = 20
                    elif word_count < 800: wc_score = 50
                    elif word_count < 1500: wc_score = 70
                    elif word_count < 3000: wc_score = 90
                    else: wc_score = 80

                    exp = ai_result.get("experience", {}).get("score", 10)
                    expt = ai_result.get("expertise", {}).get("score", 10)
                    auth = ai_result.get("authoritativeness", {}).get("score", 10)
                    trust = ai_result.get("trustworthiness", {}).get("score", 12)

                    ai_assess = ai_result.get("ai_content_assessment", "unknown")
                    ai_scores = {"human": 90, "likely_human_edited": 70, "likely_ai_light_edit": 40, "likely_unedited_ai": 15}
                    ai_score = ai_scores.get(ai_assess, 50)

                    ta = ai_result.get("topical_authority", "moderate")
                    ta_scores = {"strong": 90, "moderate": 60, "weak": 30, "minimal": 10}
                    ta_score = ta_scores.get(ta, 50)

                    fresh = ai_result.get("content_freshness", "unknown")
                    fresh_scores = {"current": 90, "aging": 60, "stale": 30, "unknown": 50}
                    fresh_score = fresh_scores.get(fresh, 50)

                    score = round(
                        (exp / 25 * 15) + (expt / 25 * 15) +
                        (auth / 25 * 15) + (trust / 25 * 15) +
                        (wc_score / 100 * 15) + (ai_score / 100 * 10) +
                        (ta_score / 100 * 10) + (fresh_score / 100 * 5)
                    )

                    # Build evidence strings from Gemini
                    evidence_findings = ai_result.get("key_findings", [])
                    # Add E-E-A-T evidence as findings for UI display
                    for dim in ["experience", "expertise", "authoritativeness", "trustworthiness"]:
                        ev = ai_result.get(dim, {}).get("evidence", "")
                        if ev:
                            evidence_findings.append(f"{dim.title()}: {ev}")

                    result = {
                        "score": score,
                        "breakdown": {
                            "experience": {"score": exp, "max": 25, "evidence": ai_result.get("experience", {}).get("evidence", "")},
                            "expertise": {"score": expt, "max": 25, "evidence": ai_result.get("expertise", {}).get("evidence", "")},
                            "authoritativeness": {"score": auth, "max": 25, "evidence": ai_result.get("authoritativeness", {}).get("evidence", "")},
                            "trustworthiness": {"score": trust, "max": 25, "evidence": ai_result.get("trustworthiness", {}).get("evidence", "")},
                            "eeat_total": exp + expt + auth + trust,
                            "content_metrics": {"score": wc_score, "word_count": word_count, "readability": "standard"},
                            "ai_content": {"assessment": ai_assess, "score": ai_score},
                            "topical_authority": {"assessment": ta, "score": ta_score},
                            "freshness": {"assessment": fresh, "score": fresh_score},
                        },
                        "key_findings": evidence_findings,
                        "ai_powered": True,
                        "api_key_detected": True,
                        "method": "gemini-2.0-flash",
                        "gemini_elapsed_s": gemini_elapsed,
                    }
                    print(f"[CONTENT-AI] AI scoring complete: score={score}, method=gemini-2.0-flash, elapsed={gemini_elapsed}s")

                except Exception as ai_err:
                    print(f"[CONTENT-AI] Gemini API FAILED: {ai_err}")
                    print(f"[CONTENT-AI] Falling back to deterministic scoring")
                    result = deterministic_content_score(page_data, content_blocks)
                    result["api_key_detected"] = True
                    result["method"] = "deterministic"
                    result["key_findings"] = [f"Gemini API call FAILED: {str(ai_err)} — fell back to rule-based scoring"]

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
