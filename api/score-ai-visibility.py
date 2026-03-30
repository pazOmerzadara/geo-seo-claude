"""
AI Visibility & Citability Scorer — Vercel Serverless Function.
Deterministic scoring: citability, crawler access, llms.txt, brand mentions.
"""
from http.server import BaseHTTPRequestHandler
import json
import re
import urllib.request
from urllib.parse import quote_plus


def score_passage(text, heading=None):
    """Score a single passage for AI citability (0-100)."""
    words = text.split()
    word_count = len(words)
    scores = {"answer_block_quality": 0, "self_containment": 0,
              "structural_readability": 0, "statistical_density": 0, "uniqueness_signals": 0}

    # 1. Answer Block Quality (30%)
    abq = 0
    for p in [r"\b\w+\s+is\s+(?:a|an|the)\s", r"\b\w+\s+refers?\s+to\s",
              r"\b\w+\s+means?\s", r"\b\w+\s+(?:can be |are )?defined\s+as\s"]:
        if re.search(p, text, re.IGNORECASE):
            abq += 15; break
    first_60 = " ".join(words[:60])
    if any(re.search(p, first_60, re.IGNORECASE) for p in [r"\b(?:is|are|was|were|means?|refers?)\b", r"\d+%", r"\$[\d,]+", r"\d+\s+(?:million|billion|thousand)"]):
        abq += 15
    if heading and heading.endswith("?"):
        abq += 10
    sentences = re.split(r"[.!?]+", text)
    if sentences:
        short_clear = sum(1 for s in sentences if 5 <= len(s.split()) <= 25)
        abq += int((short_clear / len(sentences)) * 10)
    if re.search(r"(?:according to|research shows|studies? (?:show|indicate|suggest|found))", text, re.IGNORECASE):
        abq += 10
    scores["answer_block_quality"] = min(abq, 30)

    # 2. Self-Containment (25%)
    sc = 0
    if 134 <= word_count <= 167: sc += 10
    elif 100 <= word_count <= 200: sc += 7
    elif 80 <= word_count <= 250: sc += 4
    elif 30 <= word_count <= 400: sc += 2
    pronoun_count = len(re.findall(r"\b(?:it|they|them|their|this|that|these|those|he|she|his|her)\b", text, re.IGNORECASE))
    if word_count > 0:
        ratio = pronoun_count / word_count
        if ratio < 0.02: sc += 8
        elif ratio < 0.04: sc += 5
        elif ratio < 0.06: sc += 3
    proper_nouns = len(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text))
    if proper_nouns >= 3: sc += 7
    elif proper_nouns >= 1: sc += 4
    scores["self_containment"] = min(sc, 25)

    # 3. Structural Readability (20%)
    sr = 0
    if sentences:
        avg_len = word_count / len(sentences)
        if 10 <= avg_len <= 20: sr += 8
        elif 8 <= avg_len <= 25: sr += 5
        else: sr += 2
    if re.search(r"(?:first|second|third|finally|additionally|moreover)", text, re.IGNORECASE): sr += 4
    if re.search(r"(?:\d+[\.\)]\s|\b(?:step|tip|point)\s+\d+)", text, re.IGNORECASE): sr += 4
    if "\n" in text: sr += 4
    scores["structural_readability"] = min(sr, 20)

    # 4. Statistical Density (15%)
    sd = 0
    sd += min(len(re.findall(r"\d+(?:\.\d+)?%", text)) * 3, 6)
    sd += min(len(re.findall(r"\$[\d,]+(?:\.\d+)?", text)) * 3, 5)
    sd += min(len(re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s+(?:users|customers|pages|sites|companies|people|percent|times)", text, re.IGNORECASE)) * 2, 4)
    if re.findall(r"\b20(?:2[3-6]|1\d)\b", text): sd += 2
    for p in [r"(?:according to|per|from|by)\s+[A-Z]", r"(?:Gartner|Forrester|McKinsey|Google|Microsoft|OpenAI|Anthropic)"]:
        if re.search(p, text): sd += 2
    scores["statistical_density"] = min(sd, 15)

    # 5. Uniqueness Signals (10%)
    us = 0
    if re.search(r"(?:our (?:research|study|data|analysis)|we (?:found|discovered|analyzed))", text, re.IGNORECASE): us += 5
    if re.search(r"(?:case study|for example|for instance|real-world)", text, re.IGNORECASE): us += 3
    if re.search(r"(?:using|with|via)\s+[A-Z][a-z]+", text): us += 2
    scores["uniqueness_signals"] = min(us, 10)

    total = sum(scores.values())
    return {"total_score": total, "breakdown": scores, "word_count": word_count,
            "heading": heading, "preview": " ".join(words[:25]) + ("..." if word_count > 25 else "")}


def score_citability(content_blocks):
    """Score all content blocks and return page-level citability."""
    if not content_blocks:
        return {"score": 0, "blocks_analyzed": 0, "avg_score": 0, "top_blocks": []}
    scored = [score_passage(b.get("content", ""), b.get("heading")) for b in content_blocks]
    scored.sort(key=lambda x: x["total_score"], reverse=True)
    top5 = scored[:5]
    avg = sum(b["total_score"] for b in top5) / len(top5) if top5 else 0
    return {"score": round(avg, 1), "blocks_analyzed": len(scored), "avg_score": round(avg, 1),
            "top_blocks": [{"heading": b["heading"], "score": b["total_score"], "preview": b["preview"]} for b in top5]}


def score_crawler_access(robots_data):
    """Score crawler access from robots.txt data."""
    if not robots_data or not robots_data.get("exists"):
        return {"score": 50, "details": "No robots.txt found"}
    status = robots_data.get("ai_crawler_status", {})
    score = 100
    critical = ["GPTBot", "ClaudeBot", "PerplexityBot", "OAI-SearchBot"]
    secondary = ["CCBot", "Google-Extended", "Bytespider", "cohere-ai"]
    blocked = []
    allowed = []
    for crawler in critical:
        s = status.get(crawler, "NOT_MENTIONED")
        if s == "BLOCKED":
            score -= 15; blocked.append(crawler)
        elif s == "BLOCKED_BY_WILDCARD":
            score -= 10; blocked.append(crawler + " (wildcard)")
        else:
            allowed.append(crawler)
    for crawler in secondary:
        s = status.get(crawler, "NOT_MENTIONED")
        if s == "BLOCKED":
            score -= 5; blocked.append(crawler)
        elif s == "BLOCKED_BY_WILDCARD":
            score -= 3; blocked.append(crawler + " (wildcard)")
        else:
            allowed.append(crawler)
    if not robots_data.get("sitemaps"):
        score -= 10
    return {"score": max(score, 0), "blocked": blocked, "allowed": allowed}


def score_llms_txt(llms_data):
    """Score llms.txt presence and quality."""
    if not llms_data:
        return {"score": 0, "exists": False, "full_exists": False}
    llms = llms_data.get("llms_txt", {})
    full = llms_data.get("llms_full_txt", {})
    if not llms.get("exists"):
        return {"score": 0, "exists": False, "full_exists": full.get("exists", False)}
    content = llms.get("content", "")
    content_len = len(content)
    if content_len < 100: score = 30
    elif content_len < 500: score = 50
    elif content_len < 2000: score = 70
    else: score = 90
    if full.get("exists"):
        score = min(score + 10, 100)
    return {"score": score, "exists": True, "full_exists": full.get("exists", False), "content_length": content_len}


def score_brand_mentions(domain):
    """Check Wikipedia and Wikidata for brand presence."""
    brand = domain.replace("www.", "").split(".")[0]
    result = {"score": 0, "wikipedia": False, "wikidata": False, "brand_name": brand}
    try:
        api_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(brand)}&format=json"
        req = urllib.request.Request(api_url, headers={"User-Agent": "GEO-SEO-Audit/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        search_results = data.get("query", {}).get("search", [])
        if search_results:
            top_title = search_results[0].get("title", "").lower()
            if brand.lower() in top_title:
                result["wikipedia"] = True
    except Exception:
        pass
    try:
        wd_url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={quote_plus(brand)}&language=en&format=json"
        req = urllib.request.Request(wd_url, headers={"User-Agent": "GEO-SEO-Audit/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        if data.get("search"):
            result["wikidata"] = True
    except Exception:
        pass
    if result["wikipedia"] and result["wikidata"]: result["score"] = 100
    elif result["wikipedia"]: result["score"] = 80
    elif result["wikidata"]: result["score"] = 30
    return result


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

            content_blocks = body.get("content_blocks", [])
            robots_data = body.get("robots_data", {})
            llms_data = body.get("llms_data", {})
            domain = body.get("domain", "")

            citability = score_citability(content_blocks)
            crawler = score_crawler_access(robots_data)
            llms = score_llms_txt(llms_data)
            brand = score_brand_mentions(domain)

            print(f"[AI-VIS] citability={citability['score']}, crawler={crawler['score']}, "
                  f"llms={llms['score']}, brand={brand['score']}")

            # Combined: (Citability * 0.35) + (Brand * 0.30) + (Crawlers * 0.25) + (LLMS_TXT * 0.10)
            combined = round(
                citability["score"] * 0.35 +
                brand["score"] * 0.30 +
                crawler["score"] * 0.25 +
                llms["score"] * 0.10, 1
            )
            print(f"[AI-VIS] combined score={combined}")

            result = {
                "score": combined,
                "breakdown": {
                    "citability": citability,
                    "crawler_access": crawler,
                    "llms_txt": llms,
                    "brand_mentions": brand,
                }
            }

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
