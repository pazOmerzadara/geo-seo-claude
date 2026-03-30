"""
Collect raw audit data for a URL — Vercel Serverless Function.
Fetches homepage, robots.txt, llms.txt, and extracts content blocks.
"""
from http.server import BaseHTTPRequestHandler
import json
import re
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

PARSER = "html.parser"  # lxml may not be available on Vercel

AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot",
    "anthropic-ai", "PerplexityBot", "CCBot", "Bytespider",
    "cohere-ai", "Google-Extended", "GoogleOther", "Applebot-Extended",
    "FacebookBot", "Amazonbot",
]


def fetch_page(url, timeout=30):
    result = {
        "url": url, "status_code": None, "redirect_chain": [],
        "headers": {}, "meta_tags": {}, "title": None, "description": None,
        "canonical": None, "h1_tags": [], "heading_structure": [],
        "word_count": 0, "text_content": "", "internal_links": [],
        "external_links": [], "images": [], "structured_data": [],
        "has_ssr_content": True, "security_headers": {}, "errors": [],
    }
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
        if response.history:
            result["redirect_chain"] = [{"url": r.url, "status": r.status_code} for r in response.history]
        result["status_code"] = response.status_code
        result["headers"] = {k: v for k, v in response.headers.items()}

        for header in ["Strict-Transport-Security", "Content-Security-Policy", "X-Frame-Options",
                        "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy"]:
            result["security_headers"][header] = response.headers.get(header)

        soup = BeautifulSoup(response.text, PARSER)
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else None

        for meta in soup.find_all("meta"):
            name = meta.get("name", meta.get("property", ""))
            content = meta.get("content", "")
            if name and content:
                result["meta_tags"][name.lower()] = content
                if name.lower() == "description":
                    result["description"] = content

        canonical = soup.find("link", rel="canonical")
        result["canonical"] = canonical.get("href") if canonical else None

        for level in range(1, 7):
            for heading in soup.find_all(f"h{level}"):
                text = heading.get_text(strip=True)
                result["heading_structure"].append({"level": level, "text": text})
                if level == 1:
                    result["h1_tags"].append(text)

        # Text content (remove non-content elements)
        content_soup = BeautifulSoup(response.text, PARSER)
        for el in content_soup.find_all(["script", "style", "nav", "footer", "header"]):
            el.decompose()
        text = content_soup.get_text(separator=" ", strip=True)
        result["text_content"] = text[:15000]  # Limit for API payload size
        result["word_count"] = len(text.split())

        parsed_url = urlparse(url)
        base_domain = parsed_url.netloc
        for link in soup.find_all("a", href=True):
            href = urljoin(url, link["href"])
            link_text = link.get_text(strip=True)
            parsed_href = urlparse(href)
            if parsed_href.netloc == base_domain:
                result["internal_links"].append({"url": href, "text": link_text[:100]})
            elif parsed_href.scheme in ("http", "https"):
                result["external_links"].append({"url": href, "text": link_text[:100]})
        # Limit link lists
        result["internal_links"] = result["internal_links"][:50]
        result["external_links"] = result["external_links"][:30]

        for img in soup.find_all("img"):
            result["images"].append({
                "src": img.get("src", ""), "alt": img.get("alt", ""),
                "width": img.get("width"), "height": img.get("height"),
                "loading": img.get("loading"),
            })
        result["images"] = result["images"][:30]

        for script in BeautifulSoup(response.text, PARSER).find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                result["structured_data"].append(data)
            except (json.JSONDecodeError, TypeError):
                result["errors"].append("Invalid JSON-LD detected")

        # SSR check
        js_app_roots = soup.find_all(id=re.compile(r"(app|root|__next|__nuxt)", re.I))
        if js_app_roots:
            for root in js_app_roots:
                inner_text = root.get_text(strip=True)
                if len(inner_text) < 50:
                    result["has_ssr_content"] = False

    except requests.exceptions.Timeout:
        result["errors"].append(f"Timeout after {timeout} seconds")
    except requests.exceptions.ConnectionError as e:
        result["errors"].append(f"Connection error: {str(e)}")
    except Exception as e:
        result["errors"].append(f"Unexpected error: {str(e)}")
    return result


def fetch_robots_txt(url, timeout=15):
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    result = {"url": robots_url, "exists": False, "content": "", "ai_crawler_status": {}, "sitemaps": [], "errors": []}
    try:
        response = requests.get(robots_url, headers=DEFAULT_HEADERS, timeout=timeout)
        if response.status_code == 200:
            result["exists"] = True
            result["content"] = response.text[:5000]
            lines = response.text.split("\n")
            current_agent = None
            agent_rules = {}
            for line in lines:
                line = line.strip()
                if line.lower().startswith("user-agent:"):
                    current_agent = line.split(":", 1)[1].strip()
                    if current_agent not in agent_rules:
                        agent_rules[current_agent] = []
                elif line.lower().startswith("disallow:") and current_agent:
                    path = line.split(":", 1)[1].strip()
                    agent_rules[current_agent].append({"directive": "Disallow", "path": path})
                elif line.lower().startswith("allow:") and current_agent:
                    path = line.split(":", 1)[1].strip()
                    agent_rules[current_agent].append({"directive": "Allow", "path": path})
                elif line.lower().startswith("sitemap:"):
                    sitemap_url = line.split(":", 1)[1].strip()
                    if not sitemap_url.startswith("http"):
                        sitemap_url = "http" + sitemap_url
                    result["sitemaps"].append(sitemap_url)

            for crawler in AI_CRAWLERS:
                if crawler in agent_rules:
                    rules = agent_rules[crawler]
                    if any(r["directive"] == "Disallow" and r["path"] == "/" for r in rules):
                        result["ai_crawler_status"][crawler] = "BLOCKED"
                    elif any(r["directive"] == "Disallow" and r["path"] for r in rules):
                        result["ai_crawler_status"][crawler] = "PARTIALLY_BLOCKED"
                    else:
                        result["ai_crawler_status"][crawler] = "ALLOWED"
                elif "*" in agent_rules:
                    wildcard = agent_rules["*"]
                    if any(r["directive"] == "Disallow" and r["path"] == "/" for r in wildcard):
                        result["ai_crawler_status"][crawler] = "BLOCKED_BY_WILDCARD"
                    else:
                        result["ai_crawler_status"][crawler] = "ALLOWED_BY_DEFAULT"
                else:
                    result["ai_crawler_status"][crawler] = "NOT_MENTIONED"
        elif response.status_code == 404:
            result["errors"].append("No robots.txt found (404)")
            for crawler in AI_CRAWLERS:
                result["ai_crawler_status"][crawler] = "NO_ROBOTS_TXT"
    except Exception as e:
        result["errors"].append(f"Error fetching robots.txt: {str(e)}")
    return result


def fetch_llms_txt(url, timeout=15):
    parsed = urlparse(url)
    llms_url = f"{parsed.scheme}://{parsed.netloc}/llms.txt"
    llms_full_url = f"{parsed.scheme}://{parsed.netloc}/llms-full.txt"
    result = {
        "llms_txt": {"url": llms_url, "exists": False, "content": ""},
        "llms_full_txt": {"url": llms_full_url, "exists": False, "content": ""},
        "errors": [],
    }
    for key, check_url in [("llms_txt", llms_url), ("llms_full_txt", llms_full_url)]:
        try:
            response = requests.get(check_url, headers=DEFAULT_HEADERS, timeout=timeout)
            if response.status_code == 200:
                result[key]["exists"] = True
                result[key]["content"] = response.text[:5000]
        except Exception as e:
            result["errors"].append(f"Error checking {check_url}: {str(e)}")
    return result


def extract_content_blocks(html):
    soup = BeautifulSoup(html, PARSER)
    for el in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
        el.decompose()
    blocks = []
    current_heading = "Introduction"
    current_content = []
    for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol", "table", "blockquote"]):
        if element.name.startswith("h"):
            if current_content:
                combined = " ".join(current_content)
                if len(combined.split()) >= 20:
                    blocks.append({"heading": current_heading, "content": combined, "word_count": len(combined.split())})
            current_heading = element.get_text(strip=True)
            current_content = []
        else:
            text = element.get_text(strip=True)
            if text and len(text.split()) >= 5:
                current_content.append(text)
    if current_content:
        combined = " ".join(current_content)
        if len(combined.split()) >= 20:
            blocks.append({"heading": current_heading, "content": combined, "word_count": len(combined.split())})
    return blocks[:50]  # Limit blocks


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
            url = body.get('url', '').strip()
            if not url:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "URL is required"}).encode())
                return

            if not url.startswith('http'):
                url = f'https://{url}'

            domain = urlparse(url).netloc
            print(f"[COLLECT] Fetching data for {domain} ({url})")

            # Fetch all data
            page_data = fetch_page(url)
            print(f"[COLLECT] Page fetched: status={page_data.get('status_code')}, "
                  f"word_count={page_data.get('word_count', 0)}, "
                  f"errors={page_data.get('errors', [])}")

            robots_data = fetch_robots_txt(url)
            print(f"[COLLECT] robots.txt: exists={robots_data.get('exists', False)}, "
                  f"sitemaps={len(robots_data.get('sitemaps', []))}")

            llms_data = fetch_llms_txt(url)
            print(f"[COLLECT] llms.txt: exists={llms_data.get('llms_txt', {}).get('exists', False)}, "
                  f"llms-full.txt: exists={llms_data.get('llms_full_txt', {}).get('exists', False)}")

            # Extract content blocks from raw HTML
            try:
                resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
                content_blocks = extract_content_blocks(resp.text) if resp.status_code == 200 else []
            except Exception:
                content_blocks = []
            print(f"[COLLECT] Content blocks extracted: {len(content_blocks)}")

            result = {
                "url": url,
                "domain": domain,
                "page_data": page_data,
                "robots_data": robots_data,
                "llms_data": llms_data,
                "content_blocks": content_blocks,
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result, default=str).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
