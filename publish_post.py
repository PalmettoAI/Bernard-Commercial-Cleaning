#!/usr/bin/env python3
"""
publish_post.py — Blog publishing system for bernardjanitorial.com

Usage (CLI):
    python publish_post.py --title "My Post" --excerpt "Short summary" --tag "Office Cleaning" --body-file body.html

Designed to be imported and called from weekly_generator.py for automated publishing.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).parent
BLOG_DIR     = REPO_ROOT / "blog"
BLOG_INDEX   = BLOG_DIR / "index.html"
SITEMAP      = REPO_ROOT / "sitemap.xml"
PUBLISH_LOG  = REPO_ROOT / "publish_log.json"
SITE_URL     = os.environ.get("SITE_URL", "https://bernardjanitorial.com")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "PalmettoAI/Bernard-Commercial-Cleaning")


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]


def format_date_display(date_str: str) -> str:
    """'2026-03-27' → 'March 27, 2026'"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%B %-d, %Y")


# ── HTML generators ───────────────────────────────────────────────────────────

def generate_faq_schema(faqs: list) -> str:
    """Render a FAQPage JSON-LD script tag from a list of {question, answer} dicts."""
    if not faqs:
        return ""
    items = [
        {
            "@type": "Question",
            "name": q["question"],
            "acceptedAnswer": {"@type": "Answer", "text": q["answer"]},
        }
        for q in faqs
        if q.get("question") and q.get("answer")
    ]
    if not items:
        return ""
    schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": items}
    return f'  <script type="application/ld+json">\n  {json.dumps(schema, indent=2)}\n  </script>'


def generate_post_html(title, slug, date_str, excerpt, tag, body_html, faqs=None):
    date_display = format_date_display(date_str)
    canonical    = f"{SITE_URL}/blog/{slug}.html"
    jl_title     = title.replace('"', '\\"')
    jl_excerpt   = excerpt.replace('"', '\\"')
    faq_schema   = generate_faq_schema(faqs or [])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} | Bernard Commercial Cleaning</title>

  <meta name="description" content="{excerpt}" />
  <meta name="robots" content="index, follow" />
  <link rel="canonical" href="{canonical}" />

  <meta property="og:type" content="article" />
  <meta property="og:title" content="{title}" />
  <meta property="og:description" content="{excerpt}" />
  <meta property="og:url" content="{canonical}" />

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": "{jl_title}",
    "description": "{jl_excerpt}",
    "datePublished": "{date_str}",
    "dateModified": "{date_str}",
    "author": {{
      "@type": "Organization",
      "name": "Bernard Commercial Cleaning",
      "url": "{SITE_URL}"
    }},
    "publisher": {{
      "@type": "Organization",
      "name": "Bernard Commercial Cleaning",
      "url": "{SITE_URL}",
      "logo": {{
        "@type": "ImageObject",
        "url": "{SITE_URL}/logo.png"
      }}
    }},
    "mainEntityOfPage": {{
      "@type": "WebPage",
      "@id": "{canonical}"
    }}
  }}
  </script>
{faq_schema}
  <!-- Favicon -->
  <link rel="icon" type="image/x-icon" href="/favicon.ico">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="192x192" href="/favicon-192x192.png">

  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@400;600;700&display=swap" rel="stylesheet" />

  <style>
    :root {{
      --surface-0:    #04090f;
      --surface-1:    #080f1c;
      --surface-2:    #0d1a30;
      --surface-3:    #112244;
      --primary:      #0d2f6e;
      --accent:       #1a6dff;
      --accent-light: #4d9fff;
      --accent-glow:  #1a6dff33;
      --chrome:       #c2d8ef;
      --chrome-dim:   #7a9cc0;
      --chrome-dark:  #3a5878;
      --text:         #e4f0fc;
      --text-muted:   #8aadcc;
      --white:        #f0f8ff;

      --space-xs:  0.375rem;
      --space-sm:  0.75rem;
      --space-md:  1.5rem;
      --space-lg:  3rem;
      --space-xl:  6rem;

      --font-display: 'Bebas Neue', sans-serif;
      --font-body:    'Barlow', sans-serif;
      --font-label:   'Barlow Condensed', sans-serif;

      --shadow-md: 0 6px 24px rgba(0,0,0,.5), 0 0 0 1px rgba(26,109,255,.12);
      --glow-accent: 0 0 20px rgba(26,109,255,.5), 0 0 60px rgba(26,109,255,.2);
      --border-chrome: 1px solid rgba(194,216,239,.2);
      --border-accent: 1px solid rgba(26,109,255,.4);
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      background: var(--surface-0);
      color: var(--text);
      font-family: var(--font-body);
      font-size: 16px;
      line-height: 1.6;
      overflow-x: hidden;
    }}

    /* NAV */
    .nav {{
      position: fixed;
      top: 0; left: 0; right: 0;
      z-index: 100;
      background: rgba(4, 9, 15, 0.92);
      backdrop-filter: blur(12px);
      border-bottom: var(--border-chrome);
      padding: 0 var(--space-md);
    }}
    .nav__inner {{
      max-width: 1200px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 72px;
    }}
    .nav__logo {{ display: flex; align-items: center; gap: var(--space-sm); text-decoration: none; }}
    .nav__logo img {{ height: 52px; width: auto; }}
    .nav__links {{ display: flex; align-items: center; gap: var(--space-md); list-style: none; }}
    .nav__links a {{
      font-family: var(--font-label);
      font-size: 0.85rem;
      font-weight: 600;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--chrome-dim);
      text-decoration: none;
      transition: color 0.2s;
    }}
    .nav__links a:hover,
    .nav__links a[aria-current="page"] {{ color: var(--chrome); }}
    .nav__cta {{
      font-family: var(--font-label);
      font-size: 0.85rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--white) !important;
      background: var(--accent);
      padding: 0.5rem 1.25rem;
      border-radius: 2px;
      text-decoration: none;
      transition: background 0.2s, box-shadow 0.2s;
    }}
    .nav__cta:hover {{ background: var(--accent-light); box-shadow: var(--glow-accent); }}
    .nav__hamburger {{
      display: none;
      flex-direction: column;
      gap: 5px;
      background: none;
      border: none;
      cursor: pointer;
      padding: 4px;
    }}
    .nav__hamburger span {{ display: block; width: 24px; height: 2px; background: var(--chrome); transition: all 0.3s; }}
    @media (max-width: 768px) {{
      .nav__links {{ display: none; }}
      .nav__hamburger {{ display: flex; }}
    }}

    /* MOBILE MENU */
    .mobile-menu {{
      display: none;
      position: fixed;
      inset: 0;
      z-index: 200;
      background: var(--surface-0);
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--space-lg);
    }}
    .mobile-menu.open {{ display: flex; }}
    .mobile-menu ul {{ list-style: none; text-align: center; display: flex; flex-direction: column; gap: var(--space-md); }}

    /* POST HERO */
    .post-hero {{
      position: relative;
      padding: calc(72px + var(--space-xl)) var(--space-md) var(--space-lg);
      overflow: hidden;
    }}
    .post-hero__bg {{
      position: absolute;
      inset: 0;
      background:
        radial-gradient(ellipse 70% 50% at 50% 20%, rgba(13,47,110,.6) 0%, transparent 70%),
        linear-gradient(180deg, #04090f 0%, #080f1c 60%, #04090f 100%);
    }}
    .post-hero__grid {{
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(45deg, rgba(194,216,239,.03) 1px, transparent 1px),
        linear-gradient(-45deg, rgba(194,216,239,.03) 1px, transparent 1px);
      background-size: 40px 40px;
    }}
    .post-hero__content {{
      position: relative;
      z-index: 2;
      max-width: 800px;
      margin: 0 auto;
    }}
    .post-hero__back {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-family: var(--font-label);
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--chrome-dim);
      text-decoration: none;
      margin-bottom: var(--space-md);
      transition: color 0.2s;
    }}
    .post-hero__back:hover {{ color: var(--chrome); }}
    .post-hero__meta {{
      font-family: var(--font-label);
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: var(--accent-light);
      margin-bottom: var(--space-sm);
    }}
    .post-hero__title {{
      font-family: var(--font-display);
      font-size: clamp(2rem, 5.5vw, 4rem);
      line-height: 1.05;
      letter-spacing: 0.04em;
      color: var(--white);
      text-transform: uppercase;
      margin-bottom: var(--space-md);
    }}

    /* POST CONTENT */
    .post-content {{
      padding: var(--space-xl) var(--space-md);
      background: var(--surface-1);
    }}
    .post-content__inner {{
      max-width: 800px;
      margin: 0 auto;
    }}
    .post-content__inner p {{
      color: var(--text-muted);
      font-size: 1.05rem;
      line-height: 1.8;
      margin-bottom: var(--space-md);
    }}
    .post-content__inner h2 {{
      font-family: var(--font-display);
      font-size: clamp(1.6rem, 3.5vw, 2.4rem);
      letter-spacing: 0.04em;
      color: var(--white);
      text-transform: uppercase;
      margin: var(--space-lg) 0 var(--space-sm);
      padding-left: var(--space-md);
      border-left: 3px solid var(--accent);
    }}
    .post-content__inner h3 {{
      font-family: var(--font-label);
      font-size: 1.1rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--chrome);
      margin: var(--space-md) 0 var(--space-sm);
    }}
    .post-content__inner ul,
    .post-content__inner ol {{
      margin: 0 0 var(--space-md) var(--space-lg);
      color: var(--text-muted);
      font-size: 1.05rem;
      line-height: 1.8;
    }}
    .post-content__inner li {{ margin-bottom: var(--space-xs); }}
    .post-content__inner strong {{ color: var(--chrome); }}

    .callout {{
      background: rgba(26,109,255,.08);
      border: var(--border-accent);
      padding: var(--space-md);
      margin: var(--space-lg) 0;
    }}
    .callout p {{ margin-bottom: 0; color: var(--chrome); }}

    .post-cta {{
      background: var(--surface-2);
      border: var(--border-chrome);
      padding: var(--space-lg);
      text-align: center;
      margin-top: var(--space-xl);
      position: relative;
    }}
    .post-cta::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 2px;
      background: linear-gradient(90deg, var(--accent), transparent);
    }}
    .post-cta__title {{
      font-family: var(--font-display);
      font-size: clamp(1.8rem, 4vw, 3rem);
      color: var(--white);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: var(--space-sm);
    }}
    .post-cta__title em {{ font-style: normal; color: var(--accent-light); }}
    .post-cta p {{ color: var(--text-muted); margin-bottom: var(--space-md); }}
    .btn-primary {{
      font-family: var(--font-label);
      font-size: 1rem;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--white);
      background: var(--accent);
      border: none;
      padding: 1rem 2.5rem;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
      clip-path: polygon(12px 0%, 100% 0%, calc(100% - 12px) 100%, 0% 100%);
      transition: background 0.2s, box-shadow 0.2s, transform 0.2s;
    }}
    .btn-primary:hover {{
      background: var(--accent-light);
      box-shadow: var(--glow-accent);
      transform: translateY(-2px);
    }}

    /* DIVIDER */
    .divider {{
      position: relative;
      height: 48px;
      overflow: hidden;
    }}
    .divider::before {{
      content: '';
      position: absolute;
      top: 50%;
      left: -5%;
      right: -5%;
      height: 1px;
      background: linear-gradient(90deg, transparent 0%, var(--chrome-dark) 20%, var(--accent) 50%, var(--chrome-dark) 80%, transparent 100%);
      transform: skewX(-20deg);
    }}
    .divider--diamond::after {{
      content: '◆';
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      color: var(--accent);
      font-size: 0.85rem;
      background: var(--surface-0);
      padding: 0 12px;
    }}

    /* FOOTER */
    .footer {{
      background: var(--surface-1);
      border-top: var(--border-chrome);
      padding: var(--space-lg) var(--space-md);
    }}
    .footer__inner {{
      max-width: 1200px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: var(--space-md);
    }}
    .footer__logo img {{ height: 48px; width: auto; opacity: 0.75; }}
    .footer__links {{ display: flex; gap: var(--space-md); flex-wrap: wrap; }}
    .footer__links a {{
      font-family: var(--font-label);
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--chrome-dim);
      text-decoration: none;
      transition: color 0.2s;
    }}
    .footer__links a:hover {{ color: var(--chrome); }}
    .footer__copy {{
      font-family: var(--font-label);
      font-size: 0.75rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--chrome-dark);
      width: 100%;
      text-align: center;
      margin-top: var(--space-sm);
      padding-top: var(--space-sm);
      border-top: var(--border-chrome);
    }}

    /* SKIP LINK */
    .skip-link {{
      position: absolute;
      top: -40px;
      left: 0;
      background: var(--accent);
      color: var(--white);
      padding: 8px 16px;
      text-decoration: none;
      font-family: var(--font-label);
      font-size: 0.85rem;
      z-index: 999;
      transition: top 0.2s;
    }}
    .skip-link:focus {{ top: 0; }}
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to main content</a>

  <!-- NAV -->
  <nav class="nav" aria-label="Main navigation">
    <div class="nav__inner">
      <a class="nav__logo" href="/" aria-label="Bernard Commercial Cleaning — Home">
        <img src="/logo.png" alt="Bernard Commercial Cleaning logo" />
      </a>
      <ul class="nav__links" role="list">
        <li><a href="/#services">Services</a></li>
        <li><a href="/#industries">Industries</a></li>
        <li><a href="/#about">About</a></li>
        <li><a href="/blog/" aria-current="page">Blog</a></li>
        <li><a href="/#contact" class="nav__cta">Get a Free Quote</a></li>
      </ul>
      <button class="nav__hamburger" aria-label="Open navigation menu" aria-expanded="false" aria-controls="mobile-menu" onclick="toggleMobileMenu(this)">
        <span></span><span></span><span></span>
      </button>
    </div>
  </nav>

  <!-- Mobile menu -->
  <div id="mobile-menu" class="mobile-menu" role="dialog" aria-modal="true" aria-label="Mobile navigation">
    <button onclick="closeMobileMenu()" style="position:absolute;top:20px;right:20px;background:none;border:none;color:var(--chrome);font-size:1.5rem;cursor:pointer;" aria-label="Close navigation menu">&#x2715;</button>
    <ul role="list">
      <li><a href="/#services" onclick="closeMobileMenu()" style="font-family:var(--font-display);font-size:2.5rem;color:var(--white);text-decoration:none;letter-spacing:.04em;">Services</a></li>
      <li><a href="/#industries" onclick="closeMobileMenu()" style="font-family:var(--font-display);font-size:2.5rem;color:var(--white);text-decoration:none;letter-spacing:.04em;">Industries</a></li>
      <li><a href="/#about" onclick="closeMobileMenu()" style="font-family:var(--font-display);font-size:2.5rem;color:var(--white);text-decoration:none;letter-spacing:.04em;">About</a></li>
      <li><a href="/blog/" onclick="closeMobileMenu()" style="font-family:var(--font-display);font-size:2.5rem;color:var(--accent-light);text-decoration:none;letter-spacing:.04em;">Blog</a></li>
      <li><a href="/#contact" onclick="closeMobileMenu()" style="font-family:var(--font-display);font-size:2.5rem;color:var(--accent-light);text-decoration:none;letter-spacing:.04em;">Get a Quote</a></li>
    </ul>
  </div>

  <main id="main">

    <!-- POST HERO -->
    <header class="post-hero" aria-label="Article header">
      <div class="post-hero__bg" aria-hidden="true"></div>
      <div class="post-hero__grid" aria-hidden="true"></div>
      <div class="post-hero__content">
        <a class="post-hero__back" href="/blog/">&#8592; Back to Blog</a>
        <p class="post-hero__meta">{date_display} &nbsp;&middot;&nbsp; {tag} &nbsp;&middot;&nbsp; Midlands SC</p>
        <h1 class="post-hero__title">{title}</h1>
      </div>
    </header>

    <div class="divider divider--diamond" aria-hidden="true"></div>

    <!-- POST BODY -->
    <article class="post-content">
      <div class="post-content__inner">

{body_html}

        <!-- CTA -->
        <div class="post-cta">
          <h2 class="post-cta__title">Get a <em>Free Quote</em> Today</h2>
          <p>Tell us about your space and we'll put together a cleaning plan that fits your schedule and budget. No obligation.</p>
          <a class="btn-primary" href="/#contact">Request a Free Quote</a>
        </div>

      </div>
    </article>

  </main>

  <!-- FOOTER -->
  <footer class="footer" role="contentinfo">
    <div class="footer__inner">
      <div class="footer__logo">
        <a href="/" aria-label="Bernard Commercial Cleaning — Home">
          <img src="/logo.png" alt="Bernard Commercial Cleaning" />
        </a>
      </div>
      <nav class="footer__links" aria-label="Footer navigation">
        <a href="/#services">Services</a>
        <a href="/#industries">Industries</a>
        <a href="/#about">About</a>
        <a href="/blog/">Blog</a>
        <a href="/#contact">Get a Quote</a>
        <a href="tel:8039770454">803-977-0454</a>
      </nav>
      <p class="footer__copy">&copy; 2026 Bernard Commercial Cleaning LLC &mdash; Midlands, South Carolina. All rights reserved.</p>
    </div>
  </footer>

  <script>
    function toggleMobileMenu(btn) {{
      const menu = document.getElementById('mobile-menu');
      const open = menu.classList.toggle('open');
      btn.setAttribute('aria-expanded', open);
      document.body.style.overflow = open ? 'hidden' : '';
    }}
    function closeMobileMenu() {{
      const menu = document.getElementById('mobile-menu');
      menu.classList.remove('open');
      document.body.style.overflow = '';
      const btn = document.querySelector('.nav__hamburger');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    }}
  </script>
</body>
</html>
"""


def generate_card_html(title, slug, date_str, excerpt, tag):
    date_display = format_date_display(date_str)
    return (
        f'        <article class="post-card">\n'
        f'          <div class="post-card__body">\n'
        f'            <p class="post-card__meta">{date_display} &middot; {tag}</p>\n'
        f'            <h2 class="post-card__title"><a href="{slug}.html">{title}</a></h2>\n'
        f'            <p class="post-card__excerpt">{excerpt}</p>\n'
        f'            <a class="post-card__link" href="{slug}.html">Read Article</a>\n'
        f'          </div>\n'
        f'        </article>'
    )


# ── File updaters ─────────────────────────────────────────────────────────────

def update_blog_index(title, slug, date_str, excerpt, tag):
    content  = BLOG_INDEX.read_text(encoding="utf-8")
    card     = generate_card_html(title, slug, date_str, excerpt, tag)
    marker   = '<div class="grid">'
    idx      = content.find(marker)
    if idx == -1:
        raise ValueError('Could not find <div class="grid"> in blog/index.html')
    insert_at   = idx + len(marker)
    new_content = content[:insert_at] + "\n" + card + "\n" + content[insert_at:]
    BLOG_INDEX.write_text(new_content, encoding="utf-8")


def update_sitemap(slug, date_str):
    content = SITEMAP.read_text(encoding="utf-8")
    new_url = (
        f"  <url>\n"
        f"    <loc>{SITE_URL}/blog/{slug}.html</loc>\n"
        f"    <lastmod>{date_str}</lastmod>\n"
        f"    <changefreq>monthly</changefreq>\n"
        f"    <priority>0.7</priority>\n"
        f"  </url>\n"
    )
    content = content.replace("</urlset>", new_url + "</urlset>")
    SITEMAP.write_text(content, encoding="utf-8")


# ── Validation ────────────────────────────────────────────────────────────────

def validate_post_file(post_path: Path):
    content = post_path.read_text(encoding="utf-8")
    # Check relative ../file href references resolve to real files
    refs   = re.findall(r'href="\.\./([^"#?]+)"', content)
    errors = []
    for ref in refs:
        target = REPO_ROOT / ref
        if not target.exists():
            errors.append(f"  Broken link: ../{ref}")
    if errors:
        raise ValueError("Validation failed — broken internal links:\n" + "\n".join(errors))


# ── Git ───────────────────────────────────────────────────────────────────────

def git_push(files: list, commit_msg: str):
    if not GITHUB_TOKEN:
        raise EnvironmentError("GITHUB_TOKEN is not set")

    remote_with_token = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
    clean_remote      = f"https://github.com/{GITHUB_REPO}.git"

    def run(cmd, **kw):
        result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, **kw)
        if result.returncode != 0:
            raise RuntimeError(f"git command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
        return result.stdout.strip()

    run(["git", "add"] + [str(f) for f in files])
    run(["git", "commit", "-m", commit_msg])
    run(["git", "remote", "set-url", "origin", remote_with_token])
    try:
        run(["git", "-c", "credential.helper=", "push", "origin", "main"])
    finally:
        subprocess.run(["git", "remote", "set-url", "origin", clean_remote],
                       cwd=REPO_ROOT, capture_output=True)


# ── Post-publish ──────────────────────────────────────────────────────────────

def ping_sitemap():
    sitemap_url = f"{SITE_URL}/sitemap.xml"
    engines = [
        ("Google", f"https://www.google.com/ping?sitemap={sitemap_url}"),
        ("Bing",   f"https://www.bing.com/ping?sitemap={sitemap_url}"),
    ]
    for name, ping_url in engines:
        try:
            req = urllib.request.Request(ping_url, headers={"User-Agent": "BernardPublisher/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                print(f"  {name} sitemap ping: HTTP {r.status}")
        except Exception as e:
            print(f"  {name} sitemap ping skipped (non-fatal): {e}")


def regenerate_rss():
    """Rebuild rss.xml from publish_log.json after every publish."""
    log = []
    if PUBLISH_LOG.exists():
        try:
            log = json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log = []

    items = []
    for p in reversed(log):  # newest first
        title   = p["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        url     = p["url"]
        # support both "published" and "date" field names
        pub     = p.get("published") or p.get("date", "")
        excerpt = p.get("excerpt", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        try:
            from email.utils import format_datetime
            from datetime import datetime as _dt
            dt = _dt.strptime(pub, "%Y-%m-%d")
            pub_rfc = format_datetime(dt)
        except Exception:
            pub_rfc = pub
        items.append(
            f"  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{url}</link>\n"
            f"    <guid isPermaLink=\"true\">{url}</guid>\n"
            f"    <description>{excerpt}</description>\n"
            f"    <pubDate>{pub_rfc}</pubDate>\n"
            f"  </item>"
        )

    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '<channel>\n'
        f'  <title>Bernard Commercial Cleaning Blog</title>\n'
        f'  <link>{SITE_URL}/blog/</link>\n'
        f'  <description>Commercial cleaning tips and industry insights for Midlands SC businesses.</description>\n'
        f'  <atom:link href="{SITE_URL}/rss.xml" rel="self" type="application/rss+xml"/>\n'
        + "\n".join(items) + "\n"
        "</channel>\n</rss>"
    )
    rss_file = REPO_ROOT / "rss.xml"
    rss_file.write_text(rss, encoding="utf-8")
    return rss_file


def append_publish_log(title, slug, date_str, excerpt="", category="") -> str:
    url = f"{SITE_URL}/blog/{slug}.html"
    log = []
    if PUBLISH_LOG.exists():
        try:
            log = json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log = []
    log.append({
        "slug":       slug,
        "title":      title,
        "date":       date_str,
        "published":  date_str,
        "category":   category,
        "file":       f"blog/{slug}.html",
        "url":        url,
        "excerpt":    excerpt,
        "logged_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    PUBLISH_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return url


# ── Main publish function (importable) ────────────────────────────────────────

def publish(title: str, slug: str, date_str: str, excerpt: str, tag: str, body_html: str, faqs: list = None) -> str:
    """
    Publish a blog post. Returns the live URL.

    Imported and called by weekly_generator.py for automated publishing.
    Atomic commit: blog/[slug].html + blog/index.html + sitemap.xml + publish_log.json + rss.xml
    """
    if not slug:
        slug = slugify(title)
    slug = slug.removesuffix(".html")

    post_file = BLOG_DIR / f"{slug}.html"
    if post_file.exists():
        raise FileExistsError(f"Post already exists: {post_file.name}\nChoose a different slug or delete the existing file.")

    print(f"[1/6] Creating post file: blog/{slug}.html")
    post_html = generate_post_html(title, slug, date_str, excerpt, tag, body_html, faqs=faqs)
    post_file.write_text(post_html, encoding="utf-8")

    print("[2/6] Validating internal links...")
    try:
        validate_post_file(post_file)
        print("      OK")
    except ValueError as e:
        post_file.unlink()
        raise

    print("[3/6] Updating blog index...")
    update_blog_index(title, slug, date_str, excerpt, tag)

    print("[4/6] Updating sitemap.xml...")
    update_sitemap(slug, date_str)

    print("[5/6] Logging publish record...")
    url = append_publish_log(title, slug, date_str, excerpt=excerpt, category=tag)

    print("[5b/6] Regenerating RSS feed...")
    rss_file = regenerate_rss()

    print("[6/6] Committing and pushing to GitHub...")
    git_push(
        files=[post_file, BLOG_INDEX, SITEMAP, PUBLISH_LOG, rss_file],
        commit_msg=f"blog: publish \"{title}\"",
    )

    print("\nPinging search engines...")
    ping_sitemap()

    print(f"\n✓ Live at: {url}\n")
    return url


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Publish a blog post to bernardjanitorial.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python publish_post.py --title "My Post" --excerpt "Summary" --tag "Office Cleaning" --body-file body.html
        """,
    )
    parser.add_argument("--title",     help="Post title")
    parser.add_argument("--slug",      default="", help="URL slug (auto-generated from title if omitted)")
    parser.add_argument("--date",      default=datetime.today().strftime("%Y-%m-%d"), help="Publish date YYYY-MM-DD")
    parser.add_argument("--excerpt",   help="Short description (used in index card and meta description)")
    parser.add_argument("--tag",       default="Commercial Cleaning", help="Category tag (e.g. Office Cleaning, Floor Care)")
    parser.add_argument("--body",      default="", help="Full HTML body content as a string")
    parser.add_argument("--body-file", default="", help="Path to file containing HTML body content")
    args = parser.parse_args()

    missing = [f for f, v in [("--title", args.title), ("--excerpt", args.excerpt)] if not v]
    if missing:
        parser.error(f"Required: {', '.join(missing)}")

    body_html = args.body
    if args.body_file:
        body_html = Path(args.body_file).read_text(encoding="utf-8")

    if not body_html.strip():
        parser.error("Provide post content via --body or --body-file")

    publish(args.title, args.slug, args.date, args.excerpt, args.tag, body_html)


if __name__ == "__main__":
    main()
