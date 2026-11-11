"""HTML-to-text, Markdown, and structured metadata extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, Tag
from lxml import etree

try:
    from markdownify import markdownify as _markdownify
except ImportError:  # pragma: no cover - optional dependency fallback
    _markdownify = None

_BLOCK_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "table", "figcaption"]
_HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
_HARD_NOISE_TAGS = ["script", "style", "noscript", "svg", "iframe"]
_SOFT_NOISE_TAGS = ["nav", "footer", "header", "aside", "form"]
# Common boilerplate lines that add no knowledge to the index.
_BOILERPLATE = re.compile(
    r"^(accept all|cookie settings|privacy policy|terms of (use|service)|"
    r"subscribe to our newsletter|follow us|back to top)$",
    re.IGNORECASE,
)
_DEFAULT_CHUNK_SIZE = 4000
_DEFAULT_CHUNK_OVERLAP = 400


@dataclass
class PageContent:
    """Structured result of extracting a single HTML document."""

    url: str = ""
    title: str = "Untitled page"
    description: str = ""
    author: str = ""
    published_time: str = ""
    canonical_url: str = ""
    markdown: str = ""
    text: str = ""
    html: str = ""
    links: list[str] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)
    word_count: int = 0
    status_code: int = 0
    selector_matched: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "published_time": self.published_time,
            "canonical_url": self.canonical_url,
            "markdown": self.markdown,
            "text": self.text,
            "html": self.html,
            "links": self.links,
            "images": self.images,
            "headings": self.headings,
            "chunks": self.chunks,
            "schema": self.schema,
            "word_count": self.word_count,
            "status_code": self.status_code,
            "selector_matched": self.selector_matched,
        }


def _text_score(element: Tag) -> int:
    """Estimate whether a div holds readable content rather than navigation chrome."""
    text = " ".join(element.stripped_strings)
    paragraph_count = len(element.find_all("p"))
    link_text = sum(len(link.get_text(" ", strip=True)) for link in element.find_all("a"))
    # Link-heavy containers are menus, not article content.
    return len(text) - link_text + paragraph_count * 200


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_XPATH_PREFIX = "xpath:"


def _is_xpath(selector: str) -> bool:
    """Return True for explicit ``xpath:`` selectors and common XPath syntax."""
    value = (selector or "").strip()
    if value.lower().startswith(_XPATH_PREFIX):
        return True
    return value.startswith(("//", ".//", "(//", "(.//", "./"))


def _xpath_expression(selector: str) -> str:
    value = (selector or "").strip()
    if value.lower().startswith(_XPATH_PREFIX):
        return value[len(_XPATH_PREFIX):].strip()
    return value


def _xpath_elements(html: str, selector: str) -> list[etree._Element]:
    try:
        tree = etree.HTML(html)
    except (etree.ParserError, ValueError) as exc:
        raise ValueError(f"invalid document for XPath selector '{selector}'") from exc
    if tree is None:
        return []
    try:
        nodes = tree.xpath(_xpath_expression(selector))
    except etree.XPathError as exc:
        raise ValueError(f"invalid XPath selector '{selector}'") from exc
    return [node for node in nodes if isinstance(node, etree._Element)]


def _xpath_root(html: str, selector: str) -> Tag | None:
    elements = _xpath_elements(html, selector)
    if not elements:
        return None
    serialized = etree.tostring(elements[0], encoding="unicode", method="html")
    fragment = BeautifulSoup(serialized, "lxml")
    container = fragment.body or fragment
    first = container.find() if isinstance(container, Tag) else None
    return first or (container if isinstance(container, Tag) else None)


def _remove_xpath_matches(soup: BeautifulSoup, selector: str) -> BeautifulSoup:
    """Remove elements matching an XPath expression and return a fresh soup."""
    try:
        tree = etree.HTML(str(soup))
    except (etree.ParserError, ValueError):
        return soup
    if tree is None:
        return soup
    try:
        nodes = tree.xpath(_xpath_expression(selector))
    except etree.XPathError as exc:
        raise ValueError(f"invalid XPath selector '{selector}'") from exc

    removed = False
    for node in nodes:
        if not isinstance(node, etree._Element):
            continue
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
            removed = True
    if not removed:
        return soup
    return BeautifulSoup(etree.tostring(tree, encoding="unicode", method="html"), "lxml")


def _element_string(node: Any, attribute: str | None, base_url: str) -> str | None:
    if attribute:
        value = node.get(attribute)
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            value = " ".join(str(item) for item in value)
        text = str(value).strip()
        if not text:
            return None
        if attribute.lower() in {"href", "src"} and base_url:
            if not text.startswith(("data:", "mailto:", "tel:", "javascript:", "#")):
                text = urljoin(base_url, text)
        return _normalize(text) or None
    if isinstance(node, Tag):
        text = node.get_text(" ", strip=True)
    else:
        text = " ".join("".join(node.itertext()).split())
    return _normalize(text) or None


def _select_schema_nodes(soup: BeautifulSoup, selector: str) -> list[Any]:
    if _is_xpath(selector):
        return list(_xpath_elements(str(soup), selector))
    try:
        return list(soup.select(selector))
    except Exception as exc:
        raise ValueError(f"invalid CSS selector '{selector}'") from exc


def _extract_schema(
    soup: BeautifulSoup,
    schema: dict[str, Any],
    base_url: str,
) -> dict[str, Any]:
    """Extract custom fields from a selector map.

    Each field accepts either a selector string (text content) or an object with
    ``selector``/``css``/``xpath``, optional ``attr``, and optional ``all``.
    """
    result: dict[str, Any] = {}
    for field_name, spec in schema.items():
        selector: str | None = None
        attribute: str | None = None
        multiple = False

        if isinstance(spec, str):
            selector = spec
        elif isinstance(spec, dict):
            attribute = str(spec.get("attr") or spec.get("attribute") or "").strip() or None
            multiple = bool(spec.get("all"))
            if spec.get("xpath"):
                selector = "xpath:" + str(spec["xpath"]).strip()
            else:
                selector = spec.get("selector") or spec.get("css")

        selector = str(selector).strip() if selector else ""
        if not selector:
            result[field_name] = [] if multiple else None
            continue

        nodes = _select_schema_nodes(soup, selector)
        values = [
            value
            for node in nodes
            if (value := _element_string(node, attribute, base_url))
        ]
        result[field_name] = values if multiple else (values[0] if values else None)
    return result


def parse_schema(value: Any) -> dict[str, Any]:
    """Normalize a schema spec supplied as a dict or a JSON object string."""
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        data = value
    else:
        try:
            data = json.loads(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("schema must be a JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("schema must be a JSON object mapping field names to selectors")

    normalized: dict[str, Any] = {}
    for field_name, spec in data.items():
        key = str(field_name).strip()
        if not key:
            raise ValueError("schema field names cannot be empty")
        if isinstance(spec, str):
            if not spec.strip():
                raise ValueError(f"schema field '{key}' has an empty selector")
            normalized[key] = spec.strip()
        elif isinstance(spec, dict):
            if not (spec.get("selector") or spec.get("css") or spec.get("xpath")):
                raise ValueError(f"schema field '{key}' needs a 'selector', 'css', or 'xpath' key")
            normalized[key] = spec
        else:
            raise ValueError(f"schema field '{key}' must be a selector string or an object")
    return normalized


def _element_text(element: Tag) -> str:
    """Readable text for a block element without spaces before punctuation."""
    for br in element.find_all("br"):
        br.replace_with("\n")
    return _normalize(element.get_text("", strip=False))


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        for attrs in ({"name": name}, {"property": name}, {"itemprop": name}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                value = _normalize(str(tag["content"]))
                if value:
                    return value
    return ""


def _document_metadata(soup: BeautifulSoup) -> dict[str, str]:
    title = ""
    if soup.title:
        title = _normalize(soup.title.get_text(" ", strip=True))
    title = title or _meta_content(soup, "og:title", "twitter:title") or "Untitled page"

    published = _meta_content(
        soup,
        "article:published_time",
        "og:published_time",
        "datePublished",
        "date",
        "pubdate",
        "publish-date",
    )
    if not published:
        time_tag = soup.find("time", attrs={"datetime": True})
        if isinstance(time_tag, Tag):
            published = str(time_tag.get("datetime", "")).strip()

    canonical = ""
    canonical_tag = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    if isinstance(canonical_tag, Tag) and canonical_tag.get("href"):
        canonical = str(canonical_tag["href"]).strip()

    return {
        "title": title,
        "description": _meta_content(soup, "description", "og:description", "twitter:description"),
        "author": _meta_content(soup, "author", "article:author", "og:article:author", "twitter:creator"),
        "published_time": published,
        "canonical_url": canonical,
    }


def _remove_noise(soup: BeautifulSoup, aggressive: bool = True) -> None:
    """Remove scripts/styles, plus navigation chrome during automatic extraction."""
    tags = _HARD_NOISE_TAGS + (_SOFT_NOISE_TAGS if aggressive else [])
    for node in soup.find_all(tags):
        node.decompose()
    if aggressive:
        for node in soup.find_all(attrs={"role": "navigation"}):
            node.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()


def _absolutize(root: Tag, base_url: str) -> None:
    if not base_url:
        return
    for link in root.find_all("a", href=True):
        href = str(link["href"]).strip()
        if href and not href.startswith(("mailto:", "tel:", "javascript:", "#")):
            link["href"] = urljoin(base_url, href)
    for image in root.find_all("img", src=True):
        src = str(image["src"]).strip()
        if src and not src.startswith("data:"):
            image["src"] = urljoin(base_url, src)


def _find_root(soup: BeautifulSoup, target_selector: str | None) -> tuple[Tag, bool]:
    if target_selector:
        if _is_xpath(target_selector):
            selected = _xpath_root(str(soup), target_selector)
        else:
            try:
                selected = soup.select_one(target_selector)
            except Exception as exc:
                raise ValueError(f"invalid target selector '{target_selector}'") from exc
        if selected is not None:
            return selected, True

    root = soup.find(["article", "main"])
    if root is None:
        all_divs = soup.find_all("div")
        meaningful = [d for d in all_divs if d.find("p") or d.find(["h1", "h2", "h3"])]
        candidates = meaningful if meaningful else all_divs
        root = max(candidates, key=_text_score, default=None)
    if root is None:
        root = soup.body or soup
    return root, target_selector is None


def _extract_text(root: Tag) -> str:
    paragraphs: list[str] = []
    seen: set[str] = set()
    for block in root.find_all(_BLOCK_TAGS):
        if block.name == "table":
            text = _normalize(block.get_text(" ", strip=False))
        else:
            text = _element_text(block)
        if not text or _BOILERPLATE.match(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        paragraphs.append(text)

    if paragraphs:
        text = "\n\n".join(paragraphs)
    else:
        lines = (_normalize(line) for line in root.get_text("\n").splitlines())
        text = "\n\n".join(line for line in lines if line)

    # Collapse duplicate blank lines introduced by removed elements.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _fallback_markdown(root: Tag) -> str:
    """Very small HTML-to-Markdown converter used when markdownify is missing."""
    lines: list[str] = []
    for element in root.find_all(True):
        if element.name in _HEADING_TAGS:
            text = _element_text(element)
            if text:
                level = int(element.name[1])
                lines.append(f"{'#' * level} {text}")
        elif element.name == "p":
            text = _element_text(element)
            if text:
                lines.append(text)
        elif element.name == "li":
            text = _element_text(element)
            if text:
                lines.append(f"- {text}")
        elif element.name == "pre":
            text = element.get_text("\n", strip=True)
            if text:
                lines.append(f"```\n{text}\n```")
        elif element.name == "table":
            for row in element.find_all("tr"):
                cells = [_element_text(cell) for cell in row.find_all(["th", "td"])]
                if cells:
                    lines.append("| " + " | ".join(cells) + " |")
    if not lines:
        return _extract_text(root)
    return "\n\n".join(dict.fromkeys(lines))


def _to_markdown(root: Tag) -> str:
    if _markdownify is not None:
        try:
            converted = _markdownify(
                root.decode_contents(),
                heading_style="ATX",
                bullets="-",
                strip=["script", "style"],
            )
            converted = _normalize_markdown(converted)
            if converted:
                return converted
        except Exception:
            pass
    return _normalize_markdown(_fallback_markdown(root))


def _normalize_markdown(markdown: str) -> str:
    lines = [line.rstrip() for line in markdown.replace("\r\n", "\n").splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove empty links such as [](/somewhere) and consecutive blank bullets.
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)
    return text.strip()


def _collect_links_and_images(root: Tag, base_url: str) -> tuple[list[str], list[dict[str, str]]]:
    links: list[str] = []
    seen_links: set[str] = set()
    for link in root.find_all("a", href=True):
        href = str(link["href"]).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        href = urljoin(base_url, href) if base_url else href
        if href not in seen_links:
            seen_links.add(href)
            links.append(href)

    images: list[dict[str, str]] = []
    seen_images: set[str] = set()
    for image in root.find_all("img", src=True):
        src = str(image["src"]).strip()
        if not src or src.startswith("data:"):
            continue
        src = urljoin(base_url, src) if base_url else src
        if src in seen_images:
            continue
        seen_images.add(src)
        images.append({"src": src, "alt": _normalize(str(image.get("alt", "")))})

    return links, images


def validate_selectors(
    target_selector: str | None = None,
    exclude_selectors: list[str] | None = None,
) -> None:
    """Raise ValueError when any CSS or XPath selector is invalid."""
    soup = BeautifulSoup("<html><body></body></html>", "lxml")
    candidates = ([target_selector] if target_selector else []) + list(exclude_selectors or [])
    for selector in candidates:
        if _is_xpath(selector):
            _xpath_elements("<html><body></body></html>", selector)
            continue
        try:
            soup.select(selector)
        except Exception as exc:
            raise ValueError(f"invalid CSS selector '{selector}'") from exc


def chunk_text(
    text: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping character chunks at paragraph boundaries.

    ``chunk_size`` is measured in characters (roughly four characters per token),
    and ``chunk_overlap`` is the number of characters repeated between chunks.
    """
    if not text.strip() or chunk_size <= 0:
        return []
    if chunk_overlap < 0:
        chunk_overlap = 0
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 10)

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            flush()
            step = chunk_size - chunk_overlap
            for start in range(0, len(paragraph), step):
                piece = paragraph[start : start + chunk_size].strip()
                if piece:
                    chunks.append(piece)
                if start + chunk_size >= len(paragraph):
                    break
            continue

        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        flush()
        # Carry the tail of the previous chunk into the next one for context.
        if chunks and chunk_overlap:
            tail = chunks[-1][-chunk_overlap:].strip()
            current = f"{tail}\n\n{paragraph}" if tail else paragraph
            if len(current) > chunk_size:
                current = paragraph
        else:
            current = paragraph

    flush()
    return chunks


def extract_structured(
    html: str,
    url: str = "",
    target_selector: str | None = None,
    exclude_selectors: list[str] | None = None,
    chunk_size: int = 0,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    schema: dict[str, Any] | str | None = None,
) -> PageContent:
    """Extract text, Markdown, metadata, links, images, and headings.

    ``target_selector`` limits extraction to the first matching CSS or XPath
    selector. ``exclude_selectors`` strips matching elements (ads, cookie
    banners, sidebars) before extraction. ``chunk_size`` > 0 also produces
    overlapping ``chunks``. ``schema`` maps custom field names to selectors.
    """
    schema_spec = parse_schema(schema)
    soup = BeautifulSoup(html, "lxml")
    metadata = _document_metadata(soup)
    if metadata["canonical_url"] and url:
        metadata["canonical_url"] = urljoin(url, metadata["canonical_url"])
    _remove_noise(soup, aggressive=not target_selector)

    for selector in exclude_selectors or []:
        if _is_xpath(selector):
            soup = _remove_xpath_matches(soup, selector)
            continue
        try:
            matches = soup.select(selector)
        except Exception as exc:
            raise ValueError(f"invalid exclude selector '{selector}'") from exc
        for node in matches:
            node.decompose()

    schema_values = _extract_schema(soup, schema_spec, url) if schema_spec else {}
    root, selector_matched = _find_root(soup, target_selector)
    _absolutize(root, url)
    links, images = _collect_links_and_images(root, url)
    headings = [
        _normalize(heading.get_text(" ", strip=True))
        for heading in root.find_all(_HEADING_TAGS)
        if heading.get_text(strip=True)
    ]

    markdown = _to_markdown(root)
    text = _extract_text(root)
    chunk_source = markdown or text
    chunks = chunk_text(chunk_source, chunk_size, chunk_overlap) if chunk_size > 0 else []

    return PageContent(
        url=url,
        title=metadata["title"],
        description=metadata["description"],
        author=metadata["author"],
        published_time=metadata["published_time"],
        canonical_url=metadata["canonical_url"],
        markdown=markdown,
        text=text,
        html=str(root),
        links=links,
        images=images,
        headings=headings,
        chunks=chunks,
        schema=schema_values,
        word_count=len(text.split()),
        selector_matched=selector_matched,
    )


def extract_content(html: str) -> tuple[str, str]:
    """Return the document title and readable text from an HTML document."""
    document = extract_structured(html)
    return document.title, document.text
