"""Keyless international internet source fetchers."""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from urllib.parse import quote
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger("your_own_life.fetchers")

USER_AGENT = (
    "astrbot_plugin_your_own_life/0.1 "
    "(+https://github.com/kazamisama/astrbot_plugin_your_own_life)"
)

_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text: Any, limit: int = 300) -> str:
    if not text:
        return ""
    cleaned = _TAG_RE.sub(" ", str(text))
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


@dataclass(frozen=True)
class FetchedItem:
    source: str
    url: str
    title: str
    summary: str = ""
    published_at: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def url_hash(self) -> str:
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None,
                    headers: dict | None = None) -> dict:
    resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def _safe(coro) -> list[FetchedItem]:
    try:
        return await coro
    except Exception as exc:  # a broken source must not kill the whole session
        logger.debug("source fetch failed: %s", exc)
        return []


def parse_hn_payload(data: dict) -> list[FetchedItem]:
    out: list[FetchedItem] = []
    for hit in data.get("hits", []) or []:
        title = hit.get("title") or hit.get("story_title") or ""
        object_id = hit.get("objectID") or ""
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        summary = clean_text(hit.get("story_text"), 300)
        out.append(
            FetchedItem(
                source="hacker-news",
                url=url,
                title=title,
                summary=summary,
                published_at=hit.get("created_at") or "",
                extra={"points": hit.get("points"), "author": hit.get("author")},
            )
        )
    return out


def parse_github_payload(data: dict) -> list[FetchedItem]:
    out: list[FetchedItem] = []
    for repo in data.get("items", []) or []:
        full_name = repo.get("full_name") or ""
        if not full_name:
            continue
        desc = repo.get("description") or ""
        out.append(
            FetchedItem(
                source="github",
                url=repo.get("html_url") or f"https://github.com/{full_name}",
                title=full_name,
                summary=clean_text(desc, 300),
                published_at=repo.get("pushed_at") or "",
                extra={
                    "stars": repo.get("stargazers_count"),
                    "language": repo.get("language"),
                },
            )
        )
    return out


def parse_reddit_payload(data: dict, subreddit: str = "") -> list[FetchedItem]:
    out: list[FetchedItem] = []
    children = (((data.get("data") or {}).get("children")) or []) if isinstance(data, dict) else []
    for child in children:
        post = (child or {}).get("data") or {}
        title = post.get("title") or ""
        permalink = post.get("permalink") or ""
        url = post.get("url") or f"https://www.reddit.com{permalink}"
        if not title:
            continue
        out.append(
            FetchedItem(
                source=f"reddit/{subreddit or (post.get('subreddit') or '')}",
                url=url,
                title=title,
                summary=clean_text(post.get("selftext"), 300),
                published_at=str(post.get("created_utc") or ""),
                extra={"score": post.get("score"), "subreddit": post.get("subreddit")},
            )
        )
    return out


def parse_rss_text(xml_text: str, source_url: str = "") -> list[FetchedItem]:
    root = ET.fromstring(xml_text)
    tag = root.tag.lower().rsplit("}", 1)[-1]
    out: list[FetchedItem] = []
    if tag == "rss":
        for item in root.findall("./channel/item"):
            title = _node_text(item, "title")
            link = _node_text(item, "link")
            summary = clean_text(_node_text(item, "description"), 300)
            published = _node_text(item, "pubDate")
            if title and link:
                out.append(
                    FetchedItem(
                        source="rss",
                        url=link,
                        title=title,
                        summary=summary,
                        published_at=published,
                    )
                )
    elif tag == "feed":
        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            title = _node_text(entry, "{http://www.w3.org/2005/Atom}title")
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = (link_el.get("href") or "") if link_el is not None else ""
            summary = clean_text(
                _node_text(entry, "{http://www.w3.org/2005/Atom}summary")
                or _node_text(entry, "{http://www.w3.org/2005/Atom}content"),
                300,
            )
            published = _node_text(entry, "{http://www.w3.org/2005/Atom}published") or _node_text(
                entry, "{http://www.w3.org/2005/Atom}updated"
            )
            if title and link:
                out.append(
                    FetchedItem(
                        source="rss",
                        url=link,
                        title=title,
                        summary=summary,
                        published_at=published,
                    )
                )
    return out


def _node_text(parent: ET.Element, name: str) -> str:
    node = parent.find(name)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


async def fetch_hn(client: httpx.AsyncClient, query: str | None = None,
                   hits: int = 30) -> list[FetchedItem]:
    params: dict[str, Any] = {"tags": "story", "hitsPerPage": hits}
    if query:
        params["query"] = query
    data = await _get_json(client, "https://hn.algolia.com/api/v1/search_by_date", params)
    return parse_hn_payload(data)


async def fetch_github(client: httpx.AsyncClient, query: str | None = None,
                       per_page: int = 20) -> list[FetchedItem]:
    default_q = "stars:>100 pushed:>" + (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    params = {
        "q": query or default_q,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    data = await _get_json(
        client,
        "https://api.github.com/search/repositories",
        params,
        headers={"Accept": "application/vnd.github+json"},
    )
    return parse_github_payload(data)


async def fetch_reddit(client: httpx.AsyncClient, subreddits: Sequence[str],
                       per_sub: int = 10) -> list[FetchedItem]:
    out: list[FetchedItem] = []
    for sub in subreddits:
        try:
            data = await _get_json(
                client,
                f"https://www.reddit.com/r/{quote(sub)}/hot.json",
                {"limit": per_sub},
                headers={"User-Agent": USER_AGENT},
            )
            out.extend(parse_reddit_payload(data, sub))
        except Exception as exc:
            logger.debug("reddit/%s failed: %s", sub, exc)
    return out


async def fetch_rss(client: httpx.AsyncClient, url: str) -> list[FetchedItem]:
    resp = await client.get(url)
    resp.raise_for_status()
    return parse_rss_text(resp.text, url)


async def fetch_tavily(client: httpx.AsyncClient, api_key: str, query: str,
                       limit: int = 10) -> list[FetchedItem]:
    resp = await client.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": limit, "include_answer": False},
    )
    resp.raise_for_status()
    data = resp.json()
    out: list[FetchedItem] = []
    for result in data.get("results", []) or []:
        out.append(
            FetchedItem(
                source="tavily",
                url=result.get("url") or "",
                title=result.get("title") or "",
                summary=clean_text(result.get("content"), 300),
            )
        )
    return out


async def fetch_all(config: Any, client: httpx.AsyncClient,
                    queries: Sequence[str]) -> list[FetchedItem]:
    """Fetch from every enabled source and dedupe by url hash, preserving order."""
    tasks: list[asyncio.Task] = []
    first_query = queries[0] if queries else None

    if config.hn_enabled:
        tasks.append(asyncio.create_task(_safe(fetch_hn(client, first_query))))
    if config.github_enabled:
        tasks.append(asyncio.create_task(_safe(fetch_github(client, first_query))))
    if config.reddit_enabled and config.reddit_subreddits:
        tasks.append(asyncio.create_task(_safe(fetch_reddit(client, config.reddit_subreddits))))
    for feed in config.rss_feeds:
        tasks.append(asyncio.create_task(_safe(fetch_rss(client, feed))))
    if config.tavily_api_key and first_query:
        tasks.append(asyncio.create_task(_safe(fetch_tavily(client, config.tavily_api_key, first_query))))

    results = await asyncio.gather(*tasks)
    dedup: dict[str, FetchedItem] = {}
    for items in results:
        for item in items:
            dedup.setdefault(item.url_hash, item)
    return list(dedup.values())