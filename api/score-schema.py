"""
Schema & Structured Data Scorer — Vercel Serverless Function.
Deterministic scoring based on JSON-LD analysis from geo-schema.md rubric.
"""
from http.server import BaseHTTPRequestHandler
import json


def get_type(schema):
    """Get the @type from a schema block, handling nested types."""
    t = schema.get("@type", "")
    if isinstance(t, list):
        return t[0] if t else ""
    return t


def find_schemas_by_type(schemas, target_type):
    """Find all schema blocks matching a type."""
    results = []
    for s in schemas:
        if isinstance(s, dict):
            t = get_type(s)
            if t.lower() == target_type.lower():
                results.append(s)
            # Check @graph
            if "@graph" in s:
                for item in s["@graph"]:
                    if isinstance(item, dict) and get_type(item).lower() == target_type.lower():
                        results.append(item)
    return results


def count_same_as(schema):
    """Count sameAs URLs in a schema."""
    same_as = schema.get("sameAs", [])
    if isinstance(same_as, str):
        return 1, [same_as]
    if isinstance(same_as, list):
        return len(same_as), same_as
    return 0, []


def has_wikipedia(urls):
    """Check if sameAs includes Wikipedia."""
    return any("wikipedia.org" in u for u in urls)


DEPRECATED_TYPES = {"HowTo", "SpecialAnnouncement"}


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
            schemas = page_data.get("structured_data", [])

            # Flatten @graph items
            all_items = []
            for s in schemas:
                if isinstance(s, dict):
                    if "@graph" in s:
                        all_items.extend(s["@graph"])
                    else:
                        all_items.append(s)

            types_found = list(set(get_type(item) for item in all_items if get_type(item)))

            # --- Scoring ---
            breakdown = {}

            # 1. Organization/LocalBusiness (20 pts)
            orgs = [i for i in all_items if get_type(i) in ("Organization", "LocalBusiness", "Corporation")]
            org_score = 0
            org_same_as_count = 0
            if orgs:
                org_score = 10
                count, urls = count_same_as(orgs[0])
                org_same_as_count = count
                if count >= 3:
                    org_score = 20
                elif count >= 1:
                    org_score = 15
            breakdown["organization"] = {"score": org_score, "found": bool(orgs), "sameAs_count": org_same_as_count}

            # 2. Article/content schema (15 pts)
            articles = [i for i in all_items if get_type(i) in ("Article", "BlogPosting", "NewsArticle", "WebPage")]
            art_score = 0
            has_author_person = False
            if articles:
                art_score = 8
                art = articles[0]
                author = art.get("author", {})
                if isinstance(author, dict) and get_type(author) == "Person":
                    has_author_person = True
                    art_score = 12
                if art.get("dateModified"):
                    art_score = 15
            breakdown["article"] = {"score": art_score, "found": bool(articles), "has_author_person": has_author_person}

            # 3. Person schema (15 pts)
            persons = [i for i in all_items if get_type(i) == "Person"]
            person_score = 0
            if persons:
                person_score = 8
                p = persons[0]
                p_count, _ = count_same_as(p)
                if p_count >= 1:
                    person_score = 12
                if p.get("jobTitle") or p.get("knowsAbout"):
                    person_score = 15
            breakdown["person"] = {"score": person_score, "found": bool(persons)}

            # 4. sameAs completeness (15 pts)
            all_same_as = set()
            for item in all_items:
                _, urls = count_same_as(item)
                all_same_as.update(urls)
            same_as_count = len(all_same_as)
            has_wiki = has_wikipedia(all_same_as)
            if same_as_count >= 5 and has_wiki:
                sa_score = 15
            elif same_as_count >= 3:
                sa_score = 10
            elif same_as_count >= 1:
                sa_score = 5
            else:
                sa_score = 0
            platforms = []
            for url in all_same_as:
                if "wikipedia" in url: platforms.append("Wikipedia")
                elif "wikidata" in url: platforms.append("Wikidata")
                elif "linkedin" in url: platforms.append("LinkedIn")
                elif "youtube" in url: platforms.append("YouTube")
                elif "twitter" in url or "x.com" in url: platforms.append("Twitter/X")
                elif "facebook" in url: platforms.append("Facebook")
                elif "github" in url: platforms.append("GitHub")
                elif "crunchbase" in url: platforms.append("Crunchbase")
            breakdown["sameAs"] = {"score": sa_score, "platforms_linked": same_as_count,
                                   "platforms": list(set(platforms)), "has_wikipedia": has_wiki}

            # 5. speakable (10 pts)
            speakable_found = any(item.get("speakable") for item in all_items)
            breakdown["speakable"] = {"score": 10 if speakable_found else 0, "found": speakable_found}

            # 6. BreadcrumbList (5 pts)
            bread = [i for i in all_items if get_type(i) == "BreadcrumbList"]
            breakdown["breadcrumb"] = {"score": 5 if bread else 0, "found": bool(bread)}

            # 7. WebSite + SearchAction (5 pts)
            websites = [i for i in all_items if get_type(i) == "WebSite"]
            has_search = any(w.get("potentialAction") for w in websites)
            ws_score = 5 if websites and has_search else (3 if websites else 0)
            breakdown["website_search"] = {"score": ws_score, "found": bool(websites), "has_search_action": has_search}

            # 8. No deprecated schemas (5 pts)
            deprecated_found = [t for t in types_found if t in DEPRECATED_TYPES]
            breakdown["no_deprecated"] = {"score": 0 if deprecated_found else 5, "deprecated_found": deprecated_found}

            # 9. JSON-LD format (5 pts) — all structured_data comes from JSON-LD parsing
            breakdown["json_ld_format"] = {"score": 5 if schemas else 0}

            # 10. Validation (5 pts)
            errors = []
            for item in all_items:
                if not item.get("@type"):
                    errors.append("Missing @type")
            breakdown["validation"] = {"score": 5 if not errors else 0, "errors": errors}

            total = sum(v["score"] for v in breakdown.values())
            print(f"[SCHEMA] score={total} | types_found={types_found} | total_blocks={len(schemas)}")

            result = {
                "score": total,
                "breakdown": breakdown,
                "types_found": types_found,
                "total_blocks": len(schemas),
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
