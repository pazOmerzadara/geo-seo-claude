"""
Brand Authority & Platform Readiness Scorer — Vercel Serverless Function.
Uses Gemini API for AI-powered platform analysis with deterministic fallback.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.request
import urllib.error
from urllib.parse import quote_plus


def check_wikipedia(brand_name):
    """Check Wikipedia and Wikidata presence."""
    result = {"wikipedia": False, "wikidata": False}
    try:
        api_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(brand_name)}&format=json"
        req = urllib.request.Request(api_url, headers={"User-Agent": "GEO-SEO-Audit/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        search_results = data.get("query", {}).get("search", [])
        if search_results:
            top = search_results[0].get("title", "").lower()
            if brand_name.lower() in top:
                result["wikipedia"] = True
    except Exception:
        pass
    try:
        wd_url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={quote_plus(brand_name)}&language=en&format=json"
        req = urllib.request.Request(wd_url, headers={"User-Agent": "GEO-SEO-Audit/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        if data.get("search"):
            result["wikidata"] = True
    except Exception:
        pass
    return result


def deterministic_brand_score(page_data, robots_data, domain, brand_name, wiki_data):
    """Fallback deterministic scoring."""
    score = 0

    # Wikipedia/Wikidata (0-40)
    if wiki_data["wikipedia"] and wiki_data["wikidata"]:
        score += 40
    elif wiki_data["wikipedia"]:
        score += 30
    elif wiki_data["wikidata"]:
        score += 15

    # Crawler access for AI bots (0-25)
    statuses = robots_data.get("ai_crawler_status", {})
    allowed = sum(1 for v in statuses.values() if v in ("ALLOWED", "ALLOWED_BY_DEFAULT", "NOT_MENTIONED", "NO_ROBOTS_TXT"))
    total = max(len(statuses), 1)
    score += round(25 * (allowed / total))

    # Schema sameAs (0-20)
    schemas = page_data.get("structured_data", [])
    same_as_count = 0
    for s in schemas:
        if isinstance(s, dict):
            sa = s.get("sameAs", [])
            if isinstance(sa, list): same_as_count += len(sa)
            elif isinstance(sa, str): same_as_count += 1
            if "@graph" in s:
                for item in s["@graph"]:
                    sa = item.get("sameAs", []) if isinstance(item, dict) else []
                    if isinstance(sa, list): same_as_count += len(sa)
                    elif isinstance(sa, str): same_as_count += 1
    if same_as_count >= 5: score += 20
    elif same_as_count >= 3: score += 15
    elif same_as_count >= 1: score += 8

    # Content structure (0-15)
    headings = page_data.get("heading_structure", [])
    word_count = page_data.get("word_count", 0)
    if word_count > 1500 and len(headings) > 5: score += 15
    elif word_count > 800: score += 10
    elif word_count > 300: score += 5

    return {
        "score": min(score, 100),
        "breakdown": {
            "platforms": {
                "google_aio": {"score": score, "rationale": "Deterministic estimate"},
                "chatgpt": {"score": score, "rationale": "Deterministic estimate"},
                "perplexity": {"score": max(score - 10, 0), "rationale": "Deterministic estimate"},
                "gemini": {"score": score, "rationale": "Deterministic estimate"},
                "bing_copilot": {"score": score, "rationale": "Deterministic estimate"},
            },
            "platform_average": score,
            "brand_authority": {"score": score, "wikipedia": wiki_data["wikipedia"], "wikidata": wiki_data["wikidata"]},
            "key_findings": ["AI scoring unavailable — using deterministic fallback"],
        },
        "ai_powered": False,
    }


def call_gemini_api(api_key, page_data, robots_data, domain, brand_name, wiki_data):
    """Call Gemini API for platform readiness analysis."""
    schemas = page_data.get("structured_data", [])
    same_as = []
    for s in schemas:
        if isinstance(s, dict):
            sa = s.get("sameAs", [])
            if isinstance(sa, list): same_as.extend(sa)
            elif isinstance(sa, str): same_as.append(sa)

    statuses = robots_data.get("ai_crawler_status", {})
    crawler_summary = ", ".join(f"{k}: {v}" for k, v in list(statuses.items())[:8])

    headings = [h.get("text", "") for h in page_data.get("heading_structure", [])[:10]]
    word_count = page_data.get("word_count", 0)

    prompt = f"""Analyze this website's readiness for AI search platforms.

Domain: {domain}
Brand: {brand_name}
Wikipedia presence: {wiki_data['wikipedia']}
Wikidata presence: {wiki_data['wikidata']}
Word count: {word_count}
Schema sameAs links: {json.dumps(same_as[:10])}
Crawler access: {crawler_summary}
Headings: {json.dumps(headings)}

Score readiness (0-100) for each platform and explain briefly:
1. Google AI Overviews - favors ranked pages, question-answer structure, tables/lists
2. ChatGPT Web Search - favors Wikipedia entity recognition, factual concise content
3. Perplexity AI - favors community validation (Reddit), primary sources, freshness
4. Google Gemini - favors Google ecosystem presence (YouTube, Knowledge Graph)
5. Bing Copilot - favors Bing index signals, LinkedIn presence, enterprise content

Also give an overall brand_authority_score (0-100).

Return ONLY valid JSON (no markdown):
{{"google_aio": {{"score": 0, "rationale": "..."}}, "chatgpt": {{"score": 0, "rationale": "..."}}, "perplexity": {{"score": 0, "rationale": "..."}}, "gemini": {{"score": 0, "rationale": "..."}}, "bing_copilot": {{"score": 0, "rationale": "..."}}, "brand_authority_score": 0, "key_findings": ["...", "..."]}}"""

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
            robots_data = body.get("robots_data", {})
            domain = body.get("domain", "")
            brand_name = body.get("brand_name", domain.replace("www.", "").split(".")[0])

            # Always do deterministic Wikipedia/Wikidata check
            wiki_data = check_wikipedia(brand_name)

            api_key = os.environ.get("GOOGLE_API_KEY", "")

            if not api_key:
                result = deterministic_brand_score(page_data, robots_data, domain, brand_name, wiki_data)
            else:
                try:
                    ai_result = call_gemini_api(api_key, page_data, robots_data, domain, brand_name, wiki_data)

                    platforms = {}
                    for p in ["google_aio", "chatgpt", "perplexity", "gemini", "bing_copilot"]:
                        pdata = ai_result.get(p, {})
                        platforms[p] = {
                            "score": min(max(pdata.get("score", 50), 0), 100),
                            "rationale": pdata.get("rationale", "")
                        }

                    platform_avg = round(sum(p["score"] for p in platforms.values()) / 5)
                    brand_auth = min(max(ai_result.get("brand_authority_score", 50), 0), 100)

                    # Combined: 60% platform readiness, 40% brand authority
                    combined = round(platform_avg * 0.6 + brand_auth * 0.4)

                    result = {
                        "score": combined,
                        "breakdown": {
                            "platforms": platforms,
                            "platform_average": platform_avg,
                            "brand_authority": {
                                "score": brand_auth,
                                "wikipedia": wiki_data["wikipedia"],
                                "wikidata": wiki_data["wikidata"]
                            },
                            "key_findings": ai_result.get("key_findings", []),
                        },
                        "ai_powered": True,
                    }
                except Exception as ai_err:
                    print(f"AI scoring failed: {ai_err}")
                    result = deterministic_brand_score(page_data, robots_data, domain, brand_name, wiki_data)
                    result["breakdown"]["key_findings"].append(f"AI scoring failed: {str(ai_err)}")

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
