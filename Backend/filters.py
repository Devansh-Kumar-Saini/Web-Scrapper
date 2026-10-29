"""URL include/exclude filtering using shell globs or regular expressions."""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from urllib.parse import urlparse

_GLOB_CHARS = set("*?[")


def parse_patterns(value: str | list[str] | None) -> list[str]:
    """Normalize a string or list of patterns from CLI/API input.

    Strings may be comma- or newline-separated. Empty values are dropped.
    """
    if value is None:
        return []
    values = [value] if isinstance(value, str) else list(value)
    patterns: list[str] = []
    for item in values:
        lines = str(item).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Regex patterns may contain commas (e.g. ``{1,3}``), so only
            # split comma-separated lists for plain glob patterns.
            parts = [line] if line.startswith("re:") else line.split(",")
            for part in parts:
                part = part.strip()
                if part:
                    patterns.append(part)
    return list(dict.fromkeys(patterns))


def parse_selectors(value: str | list[str] | None) -> list[str]:
    """Normalize CSS exclude selectors, accepting lists or newline-separated strings.

    Commas are preserved because a single CSS selector may be a group such as
    ``aside, .advertisement``.
    """
    if value is None:
        return []
    values = [value] if isinstance(value, str) else list(value)
    selectors: list[str] = []
    for item in values:
        for part in str(item).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            part = part.strip()
            if part:
                selectors.append(part)
    return list(dict.fromkeys(selectors))


def matches_pattern(url: str, pattern: str) -> bool:
    """Return True when ``url`` matches ``pattern``.

    Patterns are shell globs matched against the full URL and its path. Prefix a
    pattern with ``re:`` to use a Python regular expression instead, e.g.
    ``re:^https://example\\.com/docs/\\d+``.
    """
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern.startswith("re:"):
        try:
            return re.search(pattern[3:], url) is not None
        except re.error:
            return False

    parsed = urlparse(url)
    candidates = {url, parsed.path or "/"}
    if _GLOB_CHARS.intersection(pattern):
        return any(fnmatchcase(candidate, pattern) for candidate in candidates)
    # Plain text without wildcards behaves as a substring search, so
    # `--exclude-pattern login` matches `/login` and `/accounts/login`.
    return any(pattern in candidate for candidate in candidates)


class URLFilter:
    """Combined include/exclude URL filter.

    Include patterns act as an allow-list: when present, only matching URLs may
    be followed. Exclude patterns always win. Seed URLs bypass filtering.
    """

    def __init__(
        self,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self.include_patterns = parse_patterns(include_patterns)
        self.exclude_patterns = parse_patterns(exclude_patterns)

    def excluded_by(self, url: str) -> str | None:
        """Return a human-readable reason when the URL is filtered out."""
        for pattern in self.exclude_patterns:
            if matches_pattern(url, pattern):
                return f"excluded by pattern '{pattern}'"
        if self.include_patterns and not any(matches_pattern(url, p) for p in self.include_patterns):
            return "does not match include patterns"
        return None

    def allows(self, url: str) -> bool:
        return self.excluded_by(url) is None
