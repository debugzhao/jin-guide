from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


SUPPORTED_SUFFIXES = {
    ".html", ".htm", ".xlsx", ".xls", ".csv", ".pdf", ".json", ".xml",
    ".rar", ".jpg", ".jpeg", ".png",
}


@dataclass(frozen=True)
class DiscoveredLink:
    url: str
    title: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = dict(attrs)
        self._href = values.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            title = re.sub(r"\s+", " ", "".join(self._text)).strip()
            self.links.append((self._href, title))
            self._href = None
            self._text = []


def discover_links(
    html: str,
    *,
    base_url: str,
    title_pattern: str | None = None,
    include_pages: bool = False,
) -> list[DiscoveredLink]:
    parser = _LinkParser()
    parser.feed(html)
    pattern = re.compile(title_pattern) if title_pattern else None
    seen: set[str] = set()
    discovered: list[DiscoveredLink] = []
    for href, title in parser.links:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        suffix = parsed.path.lower()
        supported = any(suffix.endswith(item) for item in SUPPORTED_SUFFIXES)
        if not supported and not include_pages:
            continue
        searchable = f"{title} {absolute}"
        if pattern and not pattern.search(searchable):
            continue
        canonical = parsed._replace(fragment="").geturl()
        if canonical in seen:
            continue
        seen.add(canonical)
        discovered.append(DiscoveredLink(url=canonical, title=title))
    return discovered
