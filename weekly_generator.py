#!/usr/bin/env python3
"""
weekly_generator.py — Automated weekly blog post generator
for bernardjanitorial.com

Generates 3 unique, SEO-targeted posts per run and publishes them via
publish_post.publish() (no subprocesses — imported directly).

Usage:
    python3 weekly_generator.py --niche "commercial cleaning midlands sc"
    python3 weekly_generator.py --niche "office cleaning tips columbia sc" --dry-run
    python3 weekly_generator.py --niche "janitorial services sc" --approve

Environment variables:
    ANTHROPIC_API_KEY   Required when LLM_ENDPOINT is not set (default backend)
    LLM_ENDPOINT        Optional. Set to an OpenAI-compatible base URL to swap backends.
    LLM_MODEL           Optional. Model name for custom LLM_ENDPOINT backends.
    BLOG_NICHE          Default niche for Railway cron. Overridden by --niche.
    GITHUB_TOKEN        Required for publishing (forwarded to publish_post.py)
    GITHUB_REPO         Optional. Defaults to PalmettoAI/Bernard-Commercial-Cleaning
    GSC_CREDENTIALS     Optional. Service account JSON (or base64) for GSC keyword targeting.
    GSC_SITE_URL        Optional. Defaults to sc-domain:bernardjanitorial.com

──────────────────────────────────────────────────────────────────────────────
Railway cron service setup (create a SEPARATE service from the web service):
──────────────────────────────────────────────────────────────────────────────
  1. Railway dashboard → New Service → link same GitHub repo
  2. Service Settings → Build: Dockerfile path: Dockerfile.cron
  3. Service Settings → Deploy:
       Start Command: python3 weekly_generator.py --niche "$BLOG_NICHE"
       Cron Schedule: 0 8 * * 5   (every Friday 8:00 AM UTC)
  4. Service Settings → Variables:
       BLOG_NICHE          commercial cleaning services janitorial midlands south carolina
       ANTHROPIC_API_KEY   <your key>
       GITHUB_TOKEN        <your token>
       GITHUB_REPO         PalmettoAI/Bernard-Commercial-Cleaning
       SITE_URL            https://bernardjanitorial.com
       GSC_CREDENTIALS     <base64-encoded service account JSON>
       GSC_SITE_URL        sc-domain:bernardjanitorial.com
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from gsc import get_opportunities as _gsc_get_opportunities
    _GSC_AVAILABLE = True
except ImportError:
    _GSC_AVAILABLE = False

# ── Config ────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).parent
PUBLISH_LOG = REPO_ROOT / "publish_log.json"
BLOG_DIR    = REPO_ROOT / "blog"
SITEMAP     = REPO_ROOT / "sitemap.xml"
SITE_URL    = os.environ.get("SITE_URL", "https://bernardjanitorial.com")


# ── Git repo bootstrap ────────────────────────────────────────────────────────

def ensure_git_repo():
    """
    If the script is not running inside a git repository (e.g. Railway cron
    container where .git is stripped from the build context), clone the repo
    fresh into a temp directory and re-exec the script from there.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        cwd=str(REPO_ROOT),
    )
    if result.returncode == 0:
        # Already inside a git repo — clean up tmp dir from a prior re-exec
        tmpdir = os.environ.get("_BLOG_CRON_TMPDIR", "")
        if tmpdir and os.path.isdir(tmpdir) and str(REPO_ROOT).startswith(tmpdir):
            import atexit
            atexit.register(shutil.rmtree, tmpdir, True)
        return

    github_token = os.environ.get("GITHUB_TOKEN", "")
    github_repo  = os.environ.get("GITHUB_REPO", "PalmettoAI/Bernard-Commercial-Cleaning")
    if not github_token:
        sys.exit("Error: GITHUB_TOKEN must be set to clone the repo in cron mode.")

    tmpdir = tempfile.mkdtemp(prefix="blog-cron-")
    clone_url = f"https://x-access-token:{github_token}@github.com/{github_repo}.git"
    print(f"  Not in a git repo — cloning {github_repo} into {tmpdir} ...")
    subprocess.run(["git", "clone", clone_url, tmpdir], check=True)
    print("  Clone complete. Re-executing from cloned directory.")

    script = os.path.join(tmpdir, "weekly_generator.py")
    env = os.environ.copy()
    env["_BLOG_CRON_TMPDIR"] = tmpdir
    # Use subprocess.run instead of os.execve so Railway keeps logging the output
    result = subprocess.run(
        [sys.executable, script] + sys.argv[1:],
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    shutil.rmtree(tmpdir, ignore_errors=True)
    sys.exit(result.returncode)


LLM_ENDPOINT        = os.environ.get("LLM_ENDPOINT", "")
LLM_MODEL_ANTHROPIC = "claude-sonnet-4-6"
LLM_MODEL_CUSTOM    = os.environ.get("LLM_MODEL", "llama3.2")
NUM_POSTS           = 3

# Service pages to link back to from blog posts.
SERVICE_PAGES = [
    {"url": "/#contact",  "description": "Free quote and cleaning consultation for Midlands SC businesses"},
    {"url": "/#services", "description": "Commercial cleaning and janitorial services overview"},
    {"url": "/#about",    "description": "About Bernard Commercial Cleaning LLC"},
]

# Words to skip when computing keyword overlap for internal link injection
STOP_WORDS = {
    "this", "that", "with", "from", "have", "what", "when", "where", "which",
    "will", "your", "their", "they", "them", "been", "more", "than", "into",
    "some", "each", "most", "about", "after", "also", "like", "just", "make",
    "time", "year", "over", "such", "even", "take", "only", "then", "well",
    "work", "back", "used", "many", "need", "help", "does", "here", "very",
    "both", "much", "down", "come", "good", "know", "long", "made", "part",
    "these", "those", "every", "first", "being", "other", "same", "three",
    "while", "place", "right", "still", "small", "found", "never", "under",
    "might", "since", "again", "could", "gives", "build", "built", "using",
    "business", "businesses", "service", "services", "company", "companies",
    "cleaning", "clean", "commercial", "janitorial",
}


# ── LLM backend ───────────────────────────────────────────────────────────────

def call_llm(system: str, user: str) -> str:
    if not LLM_ENDPOINT:
        return _call_anthropic(system, user)
    return _call_openai_compatible(system, user)


def _call_anthropic(system: str, user: str) -> str:
    import urllib.request

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY is not set.")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=LLM_MODEL_ANTHROPIC,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text
    except ImportError:
        payload = json.dumps({
            "model": LLM_MODEL_ANTHROPIC,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            result = json.loads(r.read().decode("utf-8"))
        return result["content"][0]["text"]


def _call_openai_compatible(system: str, user: str) -> str:
    import urllib.request

    url = LLM_ENDPOINT.rstrip("/") + "/v1/chat/completions"
    payload = json.dumps({
        "model": LLM_MODEL_CUSTOM,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": 4096,
        "temperature": 0.7,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        result = json.loads(r.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"]


# ── JSON extraction ───────────────────────────────────────────────────────────

def extract_json(text: str):
    """Parse JSON from LLM output — handles raw, fenced, and embedded JSON."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    stripped = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        end   = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(
        f"Could not extract valid JSON from LLM response.\n"
        f"First 500 chars:\n{text[:500]}"
    )


# ── Publish log ───────────────────────────────────────────────────────────────

def load_published() -> list:
    if not PUBLISH_LOG.exists():
        return []
    try:
        return json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def extract_history(published: list) -> tuple:
    """Return (titles, slugs) from the publish log."""
    titles = [p["title"] for p in published]
    slugs  = [p["url"].rstrip("/").split("/")[-1].replace(".html", "")
              for p in published]
    return titles, slugs


def extract_published_context(published: list) -> str:
    if not published:
        return "None yet."
    lines = []
    for p in published:
        slug  = p["url"].rstrip("/").split("/")[-1].replace(".html", "")
        topic = p.get("topic", "")
        line  = f'- Title: "{p["title"]}" | Slug: {slug}.html'
        if topic:
            line += f' | Topic: {topic}'
        lines.append(line)
    return "\n".join(lines)


# ── Internal link injector ────────────────────────────────────────────────────

def inject_internal_links(new_posts: list, all_published: list) -> list:
    """
    Scan existing blog HTML files and inject links to newly published posts
    where keyword overlap (>= 2 meaningful words) suggests topical relevance.
    """
    if not new_posts or not all_published:
        return []

    new_slugs = {p["slug"] for p in new_posts}

    new_post_data = []
    for p in new_posts:
        text = " ".join([
            p.get("title", ""),
            p.get("angle", ""),
            p.get("target_keyword", ""),
        ])
        words = {
            w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', text)
            if w.lower() not in STOP_WORDS
        }
        new_post_data.append({"slug": p["slug"], "title": p["title"], "keywords": words})

    modified = []
    for pub in all_published:
        slug = pub["url"].rstrip("/").split("/")[-1].replace(".html", "")
        if slug in new_slugs:
            continue

        post_file = BLOG_DIR / f"{slug}.html"
        if not post_file.exists():
            continue

        content = post_file.read_text(encoding="utf-8")

        old_text  = f"{pub.get('title', '')} {pub.get('topic', '')}"
        old_words = {
            w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', old_text)
            if w.lower() not in STOP_WORDS
        }

        links_to_add = []
        for np in new_post_data:
            if np["slug"] + ".html" in content:
                continue
            if len(np["keywords"] & old_words) >= 2:
                links_to_add.append(np)

        if not links_to_add:
            continue

        link_items = "".join(
            f'<li><a href="{lp["slug"]}.html">{lp["title"]}</a></li>'
            for lp in links_to_add
        )
        related_html = (
            f'\n        <div class="callout">\n'
            f'          <p><strong>Related reading:</strong></p>\n'
            f'          <ul>{link_items}</ul>\n'
            f'        </div>'
        )

        # Insert before the post-cta block
        cta_marker = '<div class="post-cta">'
        if cta_marker in content:
            new_content = content.replace(
                cta_marker,
                related_html + "\n\n        " + cta_marker,
                1,
            )
            post_file.write_text(new_content, encoding="utf-8")
            modified.append(post_file)
            injected = ", ".join(f'"{lp["title"][:45]}"' for lp in links_to_add)
            print(f"  Injected link(s) into {slug}.html → {injected}")

    return modified


# ── Git config ────────────────────────────────────────────────────────────────

def ensure_git_user():
    """Set git user.name/email if missing — required in CI/cron environments."""
    cwd = str(REPO_ROOT)

    def git_get(key):
        r = subprocess.run(
            ["git", "config", "--global", key],
            cwd=cwd, capture_output=True, text=True,
        )
        return r.stdout.strip()

    def git_set(key, value):
        subprocess.run(
            ["git", "config", "--global", key, value],
            cwd=cwd, capture_output=True,
        )

    if not git_get("user.email"):
        git_set("user.email", "bot@bernardjanitorial.com")
    if not git_get("user.name"):
        git_set("user.name", "Bernard Publishing Bot")


# ── LLM prompts ───────────────────────────────────────────────────────────────

SYSTEM_STRATEGIST = (
    "You are an SEO content strategist for Bernard Commercial Cleaning LLC, a "
    "licensed and bonded commercial cleaning and janitorial services company based "
    "in the Midlands of South Carolina, serving Columbia, Lexington, Irmo, and "
    "surrounding areas. You generate blog post ideas that target commercial-intent "
    "keywords with genuine buyer interest from facility managers, property managers, "
    "office administrators, medical office managers, school administrators, church "
    "administrators, and business owners who need reliable professional cleaning. "
    "Ideas must be locally relevant to the Midlands SC region where natural, address "
    "a real operational pain point (cleanliness standards, liability, staff time, "
    "floor care, post-construction cleanup, move-in/move-out cleans, medical "
    "facility compliance), and be entirely distinct from any already-published "
    "content in both topic AND angle — do not reuse the same editorial structure "
    "or framing even if the surface topic differs. Return ONLY valid JSON with no "
    "surrounding text."
)

SYSTEM_WRITER = (
    "You are writing a blog post for bernardjanitorial.com, which serves commercial "
    "property owners, facility managers, office administrators, medical offices, "
    "schools, churches, and businesses across the Midlands of South Carolina "
    "evaluating professional janitorial and commercial cleaning services.\n\n"
    "Tone: Professional, direct, practical. Trusted cleaning expert — not salesperson.\n"
    "Length: 800-1200 words of body content.\n"
    "HTML format: Use <p>, <h2>, <h3>, <ul>/<li>, and <div class=\"callout\"> only.\n"
    "Do NOT include <html>, <head>, <body>, <article>, <h1>, or <div class=\"post-cta\"> "
    "— these are added by the template automatically.\n\n"
    "Quality standards — strictly enforce:\n"
    "- No filler openings. Never start with 'In today's fast-paced world', "
    "'As a business owner', 'In the digital age', or any generic scene-setter.\n"
    "- Every paragraph must contain specific, useful information. No vague padding.\n"
    "- Use concrete examples, real scenarios from commercial cleaning contexts, "
    "or specific numbers where possible.\n"
    "- Heading hierarchy: logical H2s for major sections, H3s for sub-points where "
    "appropriate. No bloated single-sentence sections.\n"
    "- Reference Midlands SC cities, business types, or local context where natural "
    "(Columbia, Lexington, Irmo, West Columbia, Cayce, Blythewood).\n"
    "Return ONLY the raw HTML. No JSON, no markdown, no fences."
)


def generate_ideas(niche: str, published: list, gsc_opportunities: list | None = None) -> list:
    existing_block = extract_published_context(published)

    gsc_block = ""
    if gsc_opportunities:
        lines = []
        for o in gsc_opportunities[:12]:
            lines.append(
                f"  - \"{o['query']}\" "
                f"({o['impressions']} impressions, pos {o['position']}, CTR {o['ctr']}%)"
            )
        gsc_block = (
            "\n\nReal keyword gaps from Google Search Console (high impressions, low clicks):\n"
            "These are queries people are already searching that land on this site but rarely click.\n"
            "PRIORITIZE topics from this list — they have proven demand:\n"
            + "\n".join(lines)
            + "\n\nFor each post, prefer picking a target_keyword directly from the GSC list above.\n"
        )

    prompt = f"""Generate exactly {NUM_POSTS} blog post ideas for this niche: "{niche}"

Already published — do NOT repeat these topics, angles, OR editorial structures:
{existing_block}
{gsc_block}
Each idea must:
- Target one specific keyword phrase a facility manager or business owner in Midlands SC would actually search
- Have a unique angle AND structure not used in any existing post
- Be relevant to commercial cleaning, janitorial services, or building maintenance in South Carolina
- Be specific and practical — no generic "why clean offices matter" overviews
- Include the target keyword naturally in the proposed title and slug

Return a JSON array of exactly {NUM_POSTS} objects with these keys:
- "title": compelling, keyword-rich title under 70 characters — keyword near the front
- "slug": URL slug, lowercase with hyphens only, max 60 characters, keyword-first where possible
- "tag": one category label (e.g. Office Cleaning, Floor Care, Medical Facilities, Post-Construction, Building Maintenance, Janitorial Services)
- "angle": 2-3 sentences describing the unique editorial angle and what makes it distinct from existing posts
- "target_keyword": the single primary keyword phrase this post targets

Return only the JSON array. Example shape:
[
  {{
    "title": "...",
    "slug": "...",
    "tag": "...",
    "angle": "...",
    "target_keyword": "..."
  }}
]"""

    print("  Calling LLM to generate post ideas...")
    raw   = call_llm(SYSTEM_STRATEGIST, prompt)
    ideas = extract_json(raw)

    if not isinstance(ideas, list) or len(ideas) == 0:
        raise ValueError("LLM returned an empty or non-list ideas response.")

    return ideas[:NUM_POSTS]


def generate_post_content(idea: dict, published: list) -> dict:
    print(f"  Writing: {idea['title'][:65]}...")

    published_context = extract_published_context(published)

    blog_links_block = ""
    if published:
        lines = []
        for p in published:
            slug  = p["url"].rstrip("/").split("/")[-1].replace(".html", "")
            topic = p.get("topic", p["title"])
            lines.append(f'- File: {slug}.html | Title: "{p["title"]}" | Topic: {topic}')
        blog_links_block = "\n".join(lines)
    else:
        blog_links_block = "None yet."

    service_links_block = "\n".join(
        f'- URL: {sp["url"]} | Description: {sp["description"]}'
        for sp in SERVICE_PAGES
    )

    # Step 1: excerpt
    excerpt_prompt = f"""Write a meta description / excerpt for this blog post.
Requirements:
- 1-2 sentences, under 160 characters total
- Must include the target keyword naturally
- Must be specific — describe what the reader will learn, not just the topic
- Reference Midlands SC or a specific local context where it fits naturally
- No generic openers like "Learn how" or "Discover why"

Title:          {idea["title"]}
Target keyword: {idea["target_keyword"]}
Angle:          {idea["angle"]}

Return ONLY the excerpt text. No quotes, no labels."""
    excerpt = call_llm(SYSTEM_WRITER, excerpt_prompt).strip().strip('"')

    # Step 2: HTML body
    body_prompt = f"""Write a complete blog post body for bernardjanitorial.com.

PRIMARY KEYWORD: {idea["target_keyword"]}
TITLE: {idea["title"]}
EDITORIAL ANGLE: {idea["angle"]}

KEYWORD PLACEMENT — required:
- Use the primary keyword naturally in the opening paragraph
- Use the primary keyword (or a close variant) in at least one <h2> subheading
- Use it naturally 3-5 more times throughout — never forced or repeated awkwardly

HEADING STRUCTURE — required:
- Use <h2> for major sections (at least 4)
- Use <h3> for sub-points within sections where it aids clarity
- No single-sentence throwaway sections — every heading must have substance

CONTENT QUALITY — strictly enforced:
- Open with a direct, specific hook — a real scenario, a specific problem, or a stat
- Never open with "In today's fast-paced world", "As a business owner", or any generic scene-setter
- Every paragraph must contain specific, useful information — no vague padding
- Use concrete examples, realistic scenarios from commercial cleaning contexts, or specific numbers
- At least one <div class="callout"> with a genuinely useful insight (not a rephrasing of the heading)
- At least one <ul>/<li> list with specific, actionable points
- Reference Midlands SC cities, business types, or local context where it fits naturally
  (Columbia, Lexington, Irmo, West Columbia, Cayce, Blythewood)

INTERNAL LINKS — required (2-4 total):
Available blog posts to link to (ONLY link when topically relevant — do not force):
{blog_links_block}

Available service/conversion pages:
{service_links_block}

Linking rules:
- Include 1-2 links to the blog posts above, but ONLY where the topic genuinely relates
- Include 1-2 links to the service pages above, placed where they add value to the reader
- Use descriptive, varied anchor text that reflects the destination — NEVER use "click here",
  "read more", "this article", or repeat the same anchor text twice
- Anchor text should be a natural phrase within the sentence, not bolted on
- For blog post links, use relative paths (e.g. href="other-slug.html")
- For service pages, use absolute paths as given (e.g. href="/#contact")

DUPLICATE AVOIDANCE:
Previously published posts (do NOT reuse their phrasing, structure, or angles):
{published_context}

CLOSING:
- End with a short, specific forward-looking paragraph (not a generic closer)
- The final paragraph should naturally lead the reader toward requesting a quote

Return ONLY the raw HTML body. Start directly with <p> or <h2>. No JSON, no markdown, no fences."""

    body_html = call_llm(SYSTEM_WRITER, body_prompt).strip()
    if body_html.startswith("```"):
        body_html = re.sub(r"^```[a-z]*\n?", "", body_html)
        body_html = re.sub(r"\n?```$", "", body_html).strip()

    # Step 3: FAQs for FAQPage schema (non-fatal)
    faq_prompt = f"""Generate 3 FAQ questions and answers for a blog post.
Title: {idea["title"]}
Target keyword: {idea["target_keyword"]}
Angle: {idea["angle"]}

Requirements:
- Each question must be something a facility manager or business owner would actually search
- Each answer must be 1-3 sentences — specific, useful, and jargon-free
- Cover different aspects: cost, process, timeline, or common concerns about commercial cleaning

Return ONLY a JSON array with no surrounding text:
[{{"question": "...", "answer": "..."}}]"""

    faqs = []
    try:
        faq_raw = call_llm(SYSTEM_WRITER, faq_prompt)
        parsed  = extract_json(faq_raw)
        if isinstance(parsed, list):
            faqs = parsed
    except Exception as e:
        print(f"  FAQ generation skipped (non-fatal): {e}")

    return {
        "title":          idea["title"],
        "slug":           idea["slug"],
        "tag":            idea["tag"],
        "excerpt":        excerpt,
        "body_html":      body_html,
        "faqs":           faqs,
        "angle":          idea.get("angle", ""),
        "target_keyword": idea.get("target_keyword", ""),
    }


# ── Preview ───────────────────────────────────────────────────────────────────

def print_preview(post: dict, index: int, total: int):
    bar = "─" * 62
    print(f"\n{bar}")
    print(f"  Post {index + 1} of {total}")
    print(bar)
    print(f"  Title:   {post['title']}")
    print(f"  Slug:    {post['slug']}")
    print(f"  Tag:     {post['tag']}")
    print(f"  Excerpt: {post['excerpt']}")
    print(f"  Body:    {len(post['body_html']):,} characters")
    snippet = re.sub(r"<[^>]+>", " ", post["body_html"])
    snippet = re.sub(r"\s+", " ", snippet).strip()[:220]
    print(f"  Body preview: {snippet}...")
    print(bar)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ensure_git_repo()

    parser = argparse.ArgumentParser(
        description="Generate and publish 3 weekly blog posts for bernardjanitorial.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 weekly_generator.py --niche "commercial cleaning midlands sc"
  python3 weekly_generator.py --niche "office cleaning columbia sc" --dry-run
  python3 weekly_generator.py --niche "janitorial services sc" --approve

railway cron env vars:
  BLOG_NICHE          topic/niche passed to --niche on each Friday run
  ANTHROPIC_API_KEY   LLM credentials
  GITHUB_TOKEN        git push credentials
  GITHUB_REPO         PalmettoAI/Bernard-Commercial-Cleaning
        """,
    )
    parser.add_argument(
        "--niche",
        default=os.environ.get("BLOG_NICHE", ""),
        help="Target niche or keyword theme. Falls back to BLOG_NICHE env var.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and preview all posts without committing or pushing.",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Prompt for manual confirmation before publishing each post.",
    )
    args = parser.parse_args()

    if not args.niche:
        parser.error(
            "--niche is required, or set the BLOG_NICHE environment variable.\n"
            "Example: python3 weekly_generator.py --niche \"commercial cleaning midlands sc\""
        )

    date_str = datetime.today().strftime("%Y-%m-%d")
    mode     = "dry-run" if args.dry_run else ("approve" if args.approve else "auto-publish")
    backend  = LLM_ENDPOINT or "Anthropic (default)"

    print(f"\n{'═' * 62}")
    print("  Bernard Commercial Cleaning — Weekly Blog Generator")
    print(f"{'═' * 62}")
    print(f"  Niche:   {args.niche}")
    print(f"  Date:    {date_str}")
    print(f"  Mode:    {mode}")
    print(f"  Backend: {backend}")
    print(f"{'═' * 62}\n")

    # ── 1. Load published history ──────────────────────────────────────────────
    published = load_published()
    existing_titles, existing_slugs = extract_history(published)
    print(f"[1/3] {len(published)} previously published post(s) loaded — will avoid overlap.\n")

    # ── 1b. Fetch GSC keyword opportunities ───────────────────────────────────
    gsc_opportunities = []
    if _GSC_AVAILABLE:
        gsc_site = os.environ.get("GSC_SITE_URL", "sc-domain:bernardjanitorial.com")
        print(f"[GSC] Fetching keyword opportunities for {gsc_site}...")
        gsc_opportunities = _gsc_get_opportunities(site_url=gsc_site)
        if gsc_opportunities:
            print(f"[GSC] {len(gsc_opportunities)} opportunities found — injecting into topic prompt.")
        else:
            print("[GSC] No opportunities returned — using LLM topic selection only.")
    else:
        print("[GSC] gsc module not available — skipping GSC topic targeting.")

    # ── 2. Generate ideas ──────────────────────────────────────────────────────
    print(f"\n[2/3] Generating {NUM_POSTS} post ideas for: \"{args.niche}\"")
    ideas = generate_ideas(args.niche, published, gsc_opportunities)

    print(f"\n  Ideas:")
    for i, idea in enumerate(ideas, 1):
        print(f"    {i}. [{idea['tag']}] {idea['title']}")
    print()

    # ── 3. Write and publish each post ────────────────────────────────────────
    print(f"[3/3] Writing and publishing {len(ideas)} posts...\n")

    if not args.dry_run:
        ensure_git_user()
        from publish_post import publish, git_push  # noqa: E402

    results         = []
    published_posts = []

    for i, idea in enumerate(ideas):
        print(f"── Post {i + 1}/{len(ideas)}")

        post = generate_post_content(idea, published)
        print_preview(post, i, len(ideas))

        if args.dry_run:
            results.append({
                "title":     post["title"],
                "url":       "(dry-run — not published)",
                "published": date_str,
            })
            print("  [dry-run] Skipped.\n")
            continue

        if args.approve:
            try:
                answer = input("\n  Publish this post? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer != "y":
                results.append({
                    "title":     post["title"],
                    "url":       "(skipped by user)",
                    "published": date_str,
                })
                print("  Skipped.\n")
                continue

        try:
            url = publish(
                title     = post["title"],
                slug      = post["slug"].removesuffix(".html"),
                date_str  = date_str,
                excerpt   = post["excerpt"],
                tag       = post["tag"],
                body_html = post["body_html"],
                faqs      = post.get("faqs", []),
            )
            # Enrich log entry with topic/angle for future duplicate-avoidance
            try:
                log = json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
                for entry in log:
                    if entry.get("url", "").endswith(f"{post['slug']}.html"):
                        entry["topic"] = idea.get("angle", "")
                        break
                PUBLISH_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")
            except Exception:
                pass  # non-fatal

            results.append({
                "title":     post["title"],
                "url":       url,
                "published": date_str,
            })
            published_posts.append({
                "slug":           post["slug"],
                "title":          post["title"],
                "angle":          post.get("angle", idea.get("angle", "")),
                "target_keyword": post.get("target_keyword", idea.get("target_keyword", "")),
            })
        except FileExistsError as e:
            print(f"  WARNING: {e}\n  Skipping this post.\n")
            results.append({
                "title":     post["title"],
                "url":       "(skipped — slug already exists)",
                "published": date_str,
            })
        except Exception as e:
            print(f"  ERROR publishing post: {e}\n")
            results.append({
                "title":     post["title"],
                "url":       f"(error: {e})",
                "published": date_str,
            })

    # ── Internal link injection ───────────────────────────────────────────────
    if not args.dry_run and published_posts:
        print("\n── Internal link injection")
        all_published_now = load_published()
        modified_files    = inject_internal_links(published_posts, all_published_now)
        if modified_files:
            try:
                git_push(
                    files=modified_files,
                    commit_msg=f"seo: inject internal links into {len(modified_files)} post(s)",
                )
                print(f"  Pushed link injections for {len(modified_files)} file(s).")
            except Exception as e:
                print(f"  Link injection push failed (non-fatal): {e}")
        else:
            print("  No existing posts needed link injection.")

    # ── Summary ───────────────────────────────────────────────────────────────
    bar = "═" * 62
    print(f"\n{bar}")
    print("  SUMMARY")
    print(bar)
    print(f"  Date:  {date_str}")
    print(f"  Niche: {args.niche}")
    print(f"  Mode:  {mode}\n")
    for r in results:
        print(f"  {r['title']}")
        print(f"  {r['url']}\n")
    print(bar + "\n")


if __name__ == "__main__":
    main()
