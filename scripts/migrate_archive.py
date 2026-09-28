#!/usr/bin/env python3
"""Mirror the public jeremy.chevallier.net archive into the static site.

This is intentionally a one-way migration helper. It reads the current public
sitemap, extracts each page's rendered Notion content, localizes images, and
emits clean, branded static pages at the same paths.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Comment
from PIL import Image, ImageOps


ORIGIN = "https://jeremy.chevallier.net"
ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
CACHE = ROOT / ".migration-cache"
HTML_CACHE = CACHE / "html"
ASSET_DIR = DIST / "archive-assets"
FILE_DIR = DIST / "archive-files"
USER_AGENT = "Mozilla/5.0 (compatible; JeremyChevallierArchiveMigration/1.0)"
MAX_WORKERS = 10

INDEX_PATHS = {"/writing", "/work", "/art", "/eclectic", "/education", "/toolkit"}
SHARED_FOOTER_MARKERS = ("Site built on Notion", "© 1993-2026 Jérémy Chevallier", "© 1993-2022 Jérémy Chevallier")
FILE_EXTENSIONS = {".pdf", ".doc", ".docx", ".zip", ".ppt", ".pptx", ".xls", ".xlsx"}


@dataclass
class Page:
    url: str
    path: str
    title: str
    description: str
    image: str
    kind: str
    body: str
    date: str = ""
    migrated_images: int = 0


def request(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - retry network failures uniformly
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def get_sitemap_urls() -> list[str]:
    xml = request(f"{ORIGIN}/sitemap.xml")
    root = ET.fromstring(xml)
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    urls = [node.text.strip() for node in root.findall(f"{namespace}url/{namespace}loc") if node.text]
    return list(dict.fromkeys(urls))


def cache_path(url: str) -> Path:
    digest = hashlib.sha1(url.encode()).hexdigest()
    return HTML_CACHE / f"{digest}.html"


def fetch_page(url: str) -> tuple[str, bytes]:
    cached = cache_path(url)
    if cached.exists():
        return url, cached.read_bytes()
    data = request(url)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return url, data


def category_for(path: str) -> str:
    first = path.strip("/").split("/", 1)[0] or "home"
    return {
        "writing": "Writing",
        "work": "Project",
        "art": "Art",
        "eclectic": "Music curation",
        "education": "Education",
        "toolkit": "Toolkit",
        "home": "Home",
    }.get(first, "Page")


def meta_content(soup: BeautifulSoup, *, name: str = "", prop: str = "") -> str:
    tag = soup.find("meta", attrs={"name": name}) if name else soup.find("meta", attrs={"property": prop})
    return (tag.get("content") or "").strip() if tag else ""


def strip_shared_footer(article) -> None:
    for block in list(article.select(".notion-callout, .notion-text, .notion-column-list")):
        text = block.get_text(" ", strip=True)
        if any(marker in text for marker in SHARED_FOOTER_MARKERS):
            block.decompose()


def clean_article(article) -> None:
    strip_shared_footer(article)
    for bad in list(article.find_all(["script", "style", "noscript", "button"])):
        bad.decompose()
    for comment in list(article.find_all(string=lambda item: isinstance(item, Comment))):
        comment.extract()
    for tag in article.find_all(True):
        for attribute in ("id", "data-nimg", "data-server-link", "data-link-uri", "style"):
            tag.attrs.pop(attribute, None)
        if tag.name == "img":
            tag.attrs.pop("srcset", None)
            tag.attrs.pop("sizes", None)
            tag["loading"] = "lazy"
            tag["decoding"] = "async"
        if tag.name == "a":
            href = tag.get("href", "")
            if href.startswith(ORIGIN):
                tag["href"] = urllib.parse.urlparse(href).path or "/"
            if re.fullmatch(r"/[a-f0-9]{32}", tag.get("href", "")):
                tag["href"] = "/archive"
            if href.startswith("http") and not href.startswith(ORIGIN):
                tag["target"] = "_blank"
                tag["rel"] = "noreferrer"


def choose_image_url(img) -> str:
    url = (img.get("data-full-size") or img.get("data-lightbox-src") or img.get("src") or "").strip()
    if url.startswith("/_next/image?"):
        proxied = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("url", [])
        if proxied:
            return proxied[0]
    return url


def safe_extension(url: str, content_type: str) -> str:
    path_ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if path_ext in FILE_EXTENSIONS:
        return path_ext
    mapping = {
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }
    return mapping.get(content_type.split(";", 1)[0].lower(), path_ext or ".bin")


def localize_image(url: str) -> str:
    if not url.startswith("http"):
        return url
    digest = hashlib.sha1(url.encode()).hexdigest()[:20]
    output = ASSET_DIR / f"{digest}.webp"
    if output.exists():
        return f"/archive-assets/{output.name}"
    try:
        data = request(url, timeout=10)
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            if image.width > 1800 or image.height > 1800:
                image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output.parent.mkdir(parents=True, exist_ok=True)
            image.save(output, "WEBP", quality=82, method=6)
        return f"/archive-assets/{output.name}"
    except Exception:
        return url


def localize_file(url: str) -> str:
    if not url.startswith("http"):
        return url
    parsed = urllib.parse.urlparse(url)
    if Path(parsed.path).suffix.lower() not in FILE_EXTENSIONS:
        return url
    digest = hashlib.sha1(url.encode()).hexdigest()[:20]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
        ext = safe_extension(url, content_type)
        if ext not in FILE_EXTENSIONS:
            return url
        output = FILE_DIR / f"{digest}{ext}"
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            output.write_bytes(data)
        return f"/archive-files/{output.name}"
    except Exception:
        return url


def parse_page(url: str, raw: bytes) -> Page:
    soup = BeautifulSoup(raw, "html.parser")
    path = urllib.parse.urlparse(url).path or "/"
    title_tag = soup.select_one("h1.notion-header__title")
    title = (title_tag.get_text(" ", strip=True) if title_tag else "") or meta_content(soup, prop="og:title")
    if not title:
        title = soup.title.get_text(" ", strip=True) if soup.title else path.rsplit("/", 1)[-1].replace("-", " ").title()
    description = meta_content(soup, name="description") or meta_content(soup, prop="og:description")
    image = meta_content(soup, prop="og:image")
    article = soup.find("article", class_=lambda classes: classes and "notion-root" in classes)
    if not article:
        article = soup.new_tag("article")
        article.string = description or "This page is part of Jérémy Chevallier’s archive."
    clean_article(article)
    date = ""
    date_match = re.search(r"Originally published\s*@?\s*([^\n]+)", article.get_text(" ", strip=True), re.I)
    if date_match:
        date = date_match.group(1).strip()
    return Page(
        url=url,
        path=path,
        title=title,
        description=description,
        image=image,
        kind=category_for(path),
        body=str(article),
        date=date,
    )


def unavailable_page(url: str) -> Page:
    path = urllib.parse.urlparse(url).path or "/"
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    title = re.sub(r"[-_]+", " ", slug).strip().title() or "Archived page"
    body = (
        '<article class="legacy-unavailable">'
        '<p>This URL appeared in the previous site’s public sitemap, but the source page was already unavailable when the archive was migrated.</p>'
        '<p>The path has been preserved so old links do not break. Its original content may be restored here if another copy is found.</p>'
        '<p><a href="/archive">Browse the complete available archive →</a></p>'
        '</article>'
    )
    return Page(
        url=url,
        path=path,
        title=title,
        description="A preserved legacy URL from Jérémy Chevallier’s archive.",
        image="",
        kind=category_for(path),
        body=body,
    )


def localize_page_media(page: Page) -> Page:
    soup = BeautifulSoup(page.body, "html.parser")
    images = list(soup.find_all("img"))
    for img in images:
        remote = choose_image_url(img)
        if not remote:
            continue
        local = localize_image(remote)
        img["src"] = local
        for wrapper in img.parents:
            if wrapper.name == "span" and (wrapper.get("data-full-size") or wrapper.get("data-lightbox-src")):
                wrapper.attrs.pop("data-full-size", None)
                wrapper.attrs.pop("data-lightbox-src", None)
                break
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("http"):
            link["href"] = localize_file(href)
    page.body = str(soup.find("article") or soup)
    page.migrated_images = sum(1 for img in images if (img.get("src") or "").startswith("/archive-assets/"))
    if page.image:
        page.image = localize_image(page.image)
    return page


def page_head(title: str, description: str, image: str = "") -> str:
    title_escaped = html.escape(title)
    description_escaped = html.escape(description or "Ideas, projects, and creative work by Jérémy Chevallier.")
    image_meta = f'<meta property="og:image" content="{html.escape(image)}" />' if image else ""
    return f"""
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#10130f" />
    <meta name="description" content="{description_escaped}" />
    <meta property="og:title" content="{title_escaped}" />
    <meta property="og:description" content="{description_escaped}" />
    {image_meta}
    <title>{title_escaped} — Jérémy Chevallier</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,300;6..72,400;6..72,500&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="/styles.css" />
    <link rel="stylesheet" href="/archive.css" />
    <script src="/script.js" defer></script>
    <script src="/archive.js" defer></script>
    """


def shell_header() -> str:
    return """
    <a class="skip-link" href="#main">Skip to content</a>
    <header class="site-header scrolled archive-header" data-header>
      <a class="wordmark" href="/" aria-label="Jérémy Chevallier, home">
        <span class="wordmark-mark" aria-hidden="true">J<span>•</span>C</span>
        <span class="wordmark-name">Jérémy<br />Chevallier</span>
      </a>
      <button class="menu-toggle" type="button" aria-expanded="false" aria-controls="site-nav"><span>Menu</span><span class="menu-icon" aria-hidden="true"><i></i><i></i></span></button>
      <nav class="site-nav" id="site-nav" aria-label="Primary navigation">
        <a href="/work">Projects</a><a href="/writing">Writing</a><a href="/art">Art</a><a href="/about-me">About</a><a class="nav-contact" href="mailto:jeremy@permascaping.com">Start a conversation</a>
      </nav>
    </header>
    """


def shell_footer() -> str:
    return """
    <footer class="site-footer archive-footer">
      <p>© <span data-year></span> Jérémy Chevallier</p>
      <div><a href="/work">Projects</a><a href="/writing">Writing</a><a href="/art">Art</a><a href="/music">Music</a></div>
      <a href="#top">Back to top ↑</a>
    </footer>
    """


def render_page(page: Page) -> str:
    description = page.description or f"{page.title}, from the archive of Jérémy Chevallier."
    return f"""<!doctype html><html lang="en"><head>{page_head(page.title, description, page.image)}</head><body class="archive-page">
    {shell_header()}
    <main id="main" class="archive-main">
      <header class="archive-hero" id="top">
        <a class="archive-kind" href="/{page.path.strip('/').split('/', 1)[0] if page.path != '/' else ''}">{html.escape(page.kind)}</a>
        <h1>{html.escape(page.title)}</h1>
        {f'<p>{html.escape(page.description)}</p>' if page.description else ''}
      </header>
      <div class="archive-layout">
        <aside class="archive-rail"><span>{html.escape(page.kind)}</span><span>{html.escape(page.date)}</span><a href="/archive">View full archive ↗</a></aside>
        <div class="archive-content">{page.body}</div>
      </div>
    </main>
    {shell_footer()}
    </body></html>"""


def render_index(title: str, description: str, pages: Iterable[Page], active_kind: str = "") -> str:
    items = []
    for page in pages:
        summary = page.description or BeautifulSoup(page.body, "html.parser").get_text(" ", strip=True)[:180]
        items.append(
            f'<a class="archive-card" href="{html.escape(page.path)}" data-kind="{html.escape(page.kind.lower())}" data-search="{html.escape((page.title + " " + summary).lower())}">'
            f'<span>{html.escape(page.kind)}</span><h2>{html.escape(page.title)}</h2><p>{html.escape(summary[:220])}</p><b>Read more ↗</b></a>'
        )
    count = len(items)
    return f"""<!doctype html><html lang="en"><head>{page_head(title, description)}</head><body class="archive-page archive-index-page">
    {shell_header()}
    <main id="main" class="archive-main">
      <header class="archive-index-hero" id="top"><p class="eyebrow"><span></span> The living archive</p><h1>{html.escape(title)}</h1><p>{html.escape(description)}</p><span>{count} published pieces</span></header>
      <section class="archive-browser" aria-label="{html.escape(title)} archive">
        <div class="archive-controls"><label for="archive-search">Search this archive</label><input id="archive-search" type="search" placeholder="Search titles and descriptions…" autocomplete="off" /><span data-result-count>{count} results</span></div>
        <div class="archive-grid">{''.join(items)}</div>
        <p class="archive-empty" hidden>No matching pieces yet. Try a broader search.</p>
      </section>
    </main>
    {shell_footer()}
    </body></html>"""


def output_path(path: str) -> Path:
    if path == "/":
        return DIST / "index.html"
    return DIST / path.strip("/") / "index.html"


def write_page(path: str, content: str) -> None:
    output = output_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def build_archive_index(pages: list[Page]) -> str:
    listed = [page for page in pages if page.path != "/" and page.path not in INDEX_PATHS and "/pages/" not in page.path]
    return render_index(
        "Everything, in one place.",
        "Projects, essays, poems, artwork, music discoveries, experiments, tools, and the long trail of ideas that connects them.",
        sorted(listed, key=lambda page: (page.kind, page.title.lower())),
    )


def main() -> int:
    urls = get_sitemap_urls()
    print(f"Discovered {len(urls)} sitemap URLs", flush=True)
    fetched: dict[str, bytes] = {}
    source_unavailable: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_page, url): url for url in urls}
        for index, future in enumerate(as_completed(futures), 1):
            url = futures[future]
            try:
                fetched_url, raw = future.result()
                fetched[fetched_url] = raw
            except Exception as exc:  # noqa: BLE001
                source_unavailable.append({"url": url, "error": str(exc)})
            if index % 50 == 0 or index == len(urls):
                print(f"Fetched {index}/{len(urls)}", flush=True)

    pages = [parse_page(url, fetched[url]) for url in urls if url in fetched]
    pages.extend(unavailable_page(url) for url in urls if url not in fetched)
    print(f"Parsed {len(pages)} pages; localizing media", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(localize_page_media, page): page.path for page in pages}
        localized: list[Page] = []
        for index, future in enumerate(as_completed(futures), 1):
            try:
                localized.append(future.result())
            except Exception as exc:  # noqa: BLE001
                failures.append({"url": futures[future], "error": f"media: {exc}"})
            if index % 50 == 0 or index == len(pages):
                print(f"Localized {index}/{len(pages)}", flush=True)
    pages = localized

    for page in pages:
        if page.path == "/" or page.path in INDEX_PATHS:
            continue
        write_page(page.path, render_page(page))

    collections = {
        "/writing": ("Writing", "Essays, ideas, poems, dreams, and notes on work, culture, design, regeneration, and being human."),
        "/work": ("Projects", "Regenerative ventures, products, community experiments, client work, and entrepreneurial chapters."),
        "/art": ("Art", "Photomanipulation, album artwork, traditional media, photography, and visual experiments."),
        "/eclectic": ("Ecléctic", "Music discoveries, deep cuts, album notes, and curation for ears that wander."),
        "/education": ("Education", "Formal programs, unconventional learning, and the sources that shaped the work."),
        "/toolkit": ("Toolkit", "Tools, templates, and systems for making thoughtful work easier to do."),
    }
    for path, (title, description) in collections.items():
        prefix = path + "/"
        members = [page for page in pages if page.path.startswith(prefix) and page.path != path and "/pages/" not in page.path]
        members.sort(key=lambda page: page.title.lower())
        write_page(path, render_index(title, description, members))

    write_page("/archive", build_archive_index(pages))

    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls + [f"{ORIGIN}/archive"]:
        sitemap.append(f"  <url><loc>{html.escape(url)}</loc></url>")
    sitemap.append("</urlset>")
    (DIST / "sitemap.xml").write_text("\n".join(sitemap), encoding="utf-8")

    report = {
        "source": f"{ORIGIN}/sitemap.xml",
        "discovered_urls": len(urls),
        "migrated_pages": len(pages),
        "localized_images": sum(page.migrated_images for page in pages),
        "source_unavailable": source_unavailable,
        "failures": failures,
        "pages": [asdict(page) | {"body": ""} for page in sorted(pages, key=lambda page: page.path)],
    }
    (ROOT / "migration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "pages"}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
