from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import sys
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_TARGET = "https://app.852941.xyz/"
DEFAULT_TIMEOUT = 12.0
DEFAULT_MAX_BYTES = 1_500_000
DEFAULT_MAX_SCRIPTS = 24
USER_AGENT = "MowanEntertainment-PublicMarketProbe/1.0"

# Deliberately small and non-bruteforce. These are normal browser-facing files.
COMMON_PUBLIC_PATHS = (
    "/robots.txt",
    "/manifest.json",
    "/site.webmanifest",
    "/manifest.webmanifest",
    "/sw.js",
    "/service-worker.js",
)

URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+", re.IGNORECASE)
PATH_PATTERN = re.compile(
    r"[\"'](?P<path>/(?:api|data|market|price|prices|history|items|ammo|ammunition|graphql)[^\"']*)[\"']",
    re.IGNORECASE,
)
FETCH_PATTERN = re.compile(
    r"(?:fetch|axios\.(?:get|request))\s*\(\s*[\"'](?P<url>[^\"']+)[\"']",
    re.IGNORECASE,
)
INTERESTING_MARKERS = (
    "/api/",
    ".json",
    "graphql",
    "supabase.co",
    "firebaseio.com",
    "firebasedatabase.app",
    "workers.dev",
    "vercel.app",
    "cloudfront.net",
    "storage.googleapis.com",
    "market",
    "price",
    "history",
)


@dataclass(frozen=True)
class FetchRecord:
    url: str
    status: int | None = None
    content_type: str = ""
    final_url: str = ""
    bytes_read: int = 0
    error: str = ""


@dataclass
class ProbeReport:
    target: str
    host: str
    resolved_addresses: list[str] = field(default_factory=list)
    fetches: list[FetchRecord] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    candidate_urls: list[str] = field(default_factory=list)
    markers: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class _HtmlAssets(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.scripts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag.lower() == "script" and values.get("src"):
            self.scripts.append(urljoin(self.base_url, str(values["src"])))
        elif tag.lower() == "link" and values.get("href"):
            self.links.append(urljoin(self.base_url, str(values["href"])))


def _same_origin(a: str, b: str) -> bool:
    left = urlparse(a)
    right = urlparse(b)
    return (
        left.scheme.lower(),
        left.hostname or "",
        left.port or (443 if left.scheme == "https" else 80),
    ) == (
        right.scheme.lower(),
        right.hostname or "",
        right.port or (443 if right.scheme == "https" else 80),
    )


def _normalize_candidate(base_url: str, raw: str) -> str | None:
    raw = str(raw or "").strip().rstrip(".,;:")
    if not raw or raw.startswith(("javascript:", "data:", "mailto:")):
        return None
    url = urljoin(base_url, raw)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return url


def extract_candidates(text: str, *, base_url: str) -> tuple[str, ...]:
    values: set[str] = set()
    for match in URL_PATTERN.finditer(text or ""):
        candidate = _normalize_candidate(base_url, match.group(0))
        if candidate and any(marker in candidate.lower() for marker in INTERESTING_MARKERS):
            values.add(candidate)
    for match in PATH_PATTERN.finditer(text or ""):
        candidate = _normalize_candidate(base_url, match.group("path"))
        if candidate:
            values.add(candidate)
    for match in FETCH_PATTERN.finditer(text or ""):
        candidate = _normalize_candidate(base_url, match.group("url"))
        if candidate:
            values.add(candidate)
    return tuple(sorted(values))


def extract_marker_lines(text: str, *, max_per_marker: int = 12) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    for marker in INTERESTING_MARKERS:
        matched = [line[:500] for line in lines if marker.lower() in line.lower() and line]
        if matched:
            result[marker] = matched[:max_per_marker]
    return result


def resolve_host(host: str) -> list[str]:
    addresses: set[str] = set()
    for family, _, _, _, sockaddr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if family in {socket.AF_INET, socket.AF_INET6} and sockaddr:
            addresses.add(str(sockaddr[0]))
    return sorted(addresses)


def fetch_public_text(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[FetchRecord, str]:
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json,text/plain,application/javascript,text/javascript,*/*;q=0.5",
        },
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            content_type = str(response.headers.get("content-type") or "")
            body = response.read(max_bytes + 1)
            truncated = len(body) > max_bytes
            body = body[:max_bytes]
            charset = response.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")
            record = FetchRecord(
                url=url,
                status=int(getattr(response, "status", 200) or 200),
                content_type=content_type,
                final_url=str(response.geturl() or url),
                bytes_read=len(body),
                error="truncated" if truncated else "",
            )
            return record, text
    except HTTPError as exc:
        return FetchRecord(url=url, status=int(exc.code), error=f"HTTP {exc.code}"), ""
    except (URLError, TimeoutError, OSError, ssl.SSLError) as exc:
        return FetchRecord(url=url, error=f"{type(exc).__name__}: {exc}"), ""


def _merge_markers(target: dict[str, list[str]], source: dict[str, list[str]]) -> None:
    for marker, lines in source.items():
        bucket = target.setdefault(marker, [])
        for line in lines:
            if line not in bucket and len(bucket) < 20:
                bucket.append(line)


def run_probe(
    target: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_scripts: int = DEFAULT_MAX_SCRIPTS,
) -> ProbeReport:
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target must be an absolute http(s) URL")

    report = ProbeReport(target=target, host=parsed.hostname)
    try:
        report.resolved_addresses = resolve_host(parsed.hostname)
    except OSError as exc:
        report.notes.append(f"DNS resolution failed: {type(exc).__name__}: {exc}")
        return report

    root_record, root_text = fetch_public_text(target, timeout=timeout, max_bytes=max_bytes)
    report.fetches.append(root_record)
    if not root_text:
        report.notes.append("Root page could not be read; no asset discovery was attempted.")
        return report

    root_base = root_record.final_url or target
    assets = _HtmlAssets(root_base)
    try:
        assets.feed(root_text)
    except Exception as exc:
        report.notes.append(f"HTML asset parsing was partial: {type(exc).__name__}: {exc}")

    report.scripts = list(dict.fromkeys(assets.scripts))[:max_scripts]
    candidates = set(extract_candidates(root_text, base_url=root_base))
    _merge_markers(report.markers, extract_marker_lines(root_text))

    # Probe only ordinary public browser files plus scripts actually referenced by the page.
    resources: list[str] = []
    for path in COMMON_PUBLIC_PATHS:
        resources.append(urljoin(root_base, path))
    resources.extend(report.scripts)

    seen: set[str] = {target}
    for resource in resources:
        if resource in seen:
            continue
        seen.add(resource)
        # Scripts are followed only when they are same-origin. CDN/vendor bundles are not needed
        # for discovering the site's own public data endpoints and would create extra traffic.
        if resource in report.scripts and not _same_origin(root_base, resource):
            continue
        record, text = fetch_public_text(resource, timeout=timeout, max_bytes=max_bytes)
        report.fetches.append(record)
        if not text or (record.status is not None and record.status >= 400):
            continue
        base = record.final_url or resource
        candidates.update(extract_candidates(text, base_url=base))
        _merge_markers(report.markers, extract_marker_lines(text))

    # Report candidates, but never automatically request discovered API/data URLs. This keeps the
    # probe discovery-only and prevents accidental invocation of unknown endpoints.
    report.candidate_urls = sorted(candidates)
    if not report.candidate_urls:
        report.notes.append("No obvious public API/JSON candidate was discovered in fetched browser resources.")
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only probe for public market website resources. Performs GET requests only.",
    )
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--max-scripts", type=int, default=DEFAULT_MAX_SCRIPTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        report = run_probe(
            args.target,
            timeout=max(1.0, min(float(args.timeout), 30.0)),
            max_bytes=max(50_000, min(int(args.max_bytes), 5_000_000)),
            max_scripts=max(1, min(int(args.max_scripts), 50)),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(asdict(report), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"Report: {args.output}")
    print(payload)

    # A DNS/HTTP failure is useful diagnostic output, not a script crash.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
