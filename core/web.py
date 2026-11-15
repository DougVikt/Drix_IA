import httpx
import html2text
import ipaddress
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
import yaml
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from duckduckgo_search import DDGS

from core import logs

_converter = html2text.HTML2Text()
_converter.ignore_links = False
_converter.ignore_images = True
_converter.body_width = 0

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

_PRIVATE_NETS = (
    ("10.0.0.0", 8), ("172.16.0.0", 12), ("192.168.0.0", 16),
    ("127.0.0.0", 8), ("169.254.0.0", 16), ("0.0.0.0", 8),
    ("100.64.0.0", 10), ("192.0.0.0", 24), ("192.0.2.0", 24),
    ("198.18.0.0", 15), ("198.51.100.0", 24), ("203.0.113.0", 24),
    ("240.0.0.0", 4), ("::", 128), ("::1", 128), ("fc00::", 7),
    ("fe80::", 10), ("2001:db8::", 32), ("ff00::", 8),
)


def _is_blocked_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return True
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    for net, prefix in _PRIVATE_NETS:
        if ip in ipaddress.ip_network(f"{net}/{prefix}"):
            return True
    return False


def _net_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    net = cfg.get("network", {}) or {}
    return {
        "block_local": bool(net.get("block_local_network", True)),
        "allowed_domains": net.get("allowed_domains", []) or [],
        "timeout": net.get("request_timeout", 15),
    }


def _hostname_allowed(hostname: str, allowed: list) -> bool:
    if not allowed:
        return True
    h = hostname.lower().rstrip(".")
    for d in allowed:
        d = d.lower().strip().lstrip("*.")
        if not d:
            continue
        if h == d or h.endswith("." + d):
            return True
    return False


def _resolve_ips(hostname: str) -> list:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    ips = []
    for info in infos:
        addr = info[4][0]
        if addr not in ips:
            ips.append(addr)
    return ips


def check_url(url: str, net: dict = None) -> str:
    net = net or _net_config()
    try:
        parts = urlparse(url)
    except ValueError:
        raise ValueError("Invalid URL")
    if parts.scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed")
    hostname = parts.hostname
    if not hostname:
        raise ValueError("Invalid host")
    if not _hostname_allowed(hostname, net["allowed_domains"]):
        raise ValueError("Domain not allowed")
    if not net["block_local"]:
        return hostname
    ips = _resolve_ips(hostname)
    if not ips:
        raise ValueError("Could not resolve host")
    for ip in ips:
        if _is_blocked_ip(ip):
            raise ValueError(f"Private/loopback address blocked: {ip}")
    return hostname


_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas",
    "de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos",
    "por", "para", "pra", "com", "sobre", "que", "se",
    "me", "minha", "meu", "favor",
    "the", "an", "of", "to", "for", "and", "in", "on", "please",
}


def _clean_query(query: str) -> str:
    """Turn a spoken request into a search query.

    DuckDuckGo returns zero results for full sentences such as
    "Pesquise na internet e me diga uma notícia...".  Stripping the command
    part leaves the actual subject and makes the search work.
    """
    original = " ".join(str(query or "").split())
    if not original:
        return ""
    q = original
    q = re.sub(r"^\s*(por favor[,\s]+)?", "", q, flags=re.I)
    q = re.sub(
        r"^\s*(pesquise|pesquisar|busque|buscar|procure|procurar|"
        r"search(?:\s+the\s+web)?|look\s+up|google)\b[:\s,]*",
        "", q, flags=re.I,
    )
    q = re.sub(
        r"^\s*(na\s+internet|na\s+web|online|no\s+google|no\s+navegador)"
        r"\b[:\s,]*", "", q, flags=re.I,
    )
    q = re.sub(
        r"^\s*(e\s+)?(me\s+)?(diga|fale|mostre|conte|informe)"
        r"\b[:\s,]*", "", q, flags=re.I,
    )
    q = re.sub(
        r"^\s*(uma|um|a|o|as|os|por|sobre|for|the|a|an)"
        r"\b[:\s,]*", "", q, flags=re.I,
    )
    q = q.strip(" \t,.:;!?-\u2013\u2014")
    return q if len(q) >= 3 else original


def _fallback_queries(query: str) -> list[str]:
    """Shorter keyword queries tried when the cleaned phrase finds nothing."""
    tokens = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]+", query)
    useful = [t for t in tokens if t.lower() not in _STOPWORDS and len(t) > 1]
    candidates = []
    if len(useful) >= 2:
        candidates.append(" ".join(useful[-2:]))
    if len(useful) >= 3:
        candidates.append(" ".join(useful[-3:]))
    return candidates


_NEWS_WORDS = (
    "notícia", "noticia", "notícias", "noticias",
    "manchete", "manchetes", "news", "últimas", "ultimas",
)

_NEWS_STOPWORDS = _STOPWORDS | {
    "notícia", "noticia", "notícias", "noticias", "manchete", "manchetes",
    "news", "hoje", "agora", "últimas", "ultimas", "recente", "recentes",
}


def _is_news_query(query: str) -> bool:
    low = str(query or "").lower()
    return any(word in low for word in _NEWS_WORDS)


def _news_query(query: str) -> str:
    """Reduce "notícia de tecnologia de hoje" to "tecnologia"."""
    tokens = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]+", query)
    useful = [t for t in tokens if t.lower() not in _NEWS_STOPWORDS and len(t) > 1]
    return " ".join(useful) if useful else query


def _gnews_search(query: str, max_results: int) -> list:
    """Current headlines from the Google News RSS feed."""
    url = (
        "https://news.google.com/rss/search?q=" + quote_plus(query or "tecnologia")
        + "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    )
    timeout = _net_config()["timeout"]
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
    root = ET.fromstring(resp.content)
    results = []
    for item in root.findall(".//item")[:max_results]:
        title = " ".join((item.findtext("title") or "").split())
        published = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = item.find("source")
        source_name = " ".join((source.text or "").split()) if source is not None else ""
        source_url = (source.get("url") or "").strip() if source is not None else ""
        if not title:
            continue
        source_line = source_name or "Google News"
        if source_url:
            source_line += f" ({source_url})"
        results.append(f"{title}\n  {source_line}\n  {published or link}")
    return results


def _search_once(query: str, max_results: int) -> list:
    with DDGS() as ddgs:
        return [
            f"{r['title']}\n  {r['href']}\n  {r.get('body', '')}"
            for r in ddgs.text(query, max_results=max_results)
        ]


_search_cache: dict[tuple[str, int], tuple[float, list]] = {}
_search_cache_lock = threading.Lock()
_SEARCH_CACHE_TTL = 300.0
_SEARCH_CACHE_MAX = 64


def _cache_get(key: tuple[str, int]):
    now = time.monotonic()
    with _search_cache_lock:
        row = _search_cache.get(key)
        if not row:
            return None
        stored, value = row
        if now - stored > _SEARCH_CACHE_TTL:
            _search_cache.pop(key, None)
            return None
        return list(value)


def _cache_put(key: tuple[str, int], value: list) -> None:
    if not value:
        return
    with _search_cache_lock:
        if len(_search_cache) >= _SEARCH_CACHE_MAX:
            _search_cache.clear()
        _search_cache[key] = (time.monotonic(), list(value))


def search(query: str, max_results: int = 5) -> list:
    net = _net_config()
    # Respect config permission (tools.py also checks; this keeps web.py safe as a standalone API).
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if not (cfg.get("network") or {}).get("allow_internet_access", False):
            logs.warn(f"WEB search blocked by config query={query[:200]!r}")
            return ["Blocked: network.allow_internet_access=false"]
    except Exception:
        # If config can't be read, fail closed for safety.
        logs.warn(f"WEB search blocked (config read error) query={query[:200]!r}")
        return ["Blocked: unable to verify network permissions"]

    cleaned = _clean_query(query)
    cache_key = (query, max_results)
    cached = _cache_get(cache_key)
    if cached is not None:
        logs.info(f"WEB search cache input={query[:120]!r} results={len(cached)}")
        return cached

    last_error = None

    if _is_news_query(query):
        news_query = _news_query(cleaned)
        try:
            news = _gnews_search(news_query, max_results)
        except Exception as e:
            last_error = e
            news = []
        logs.info(
            f"WEB news input={query[:120]!r} query={news_query[:200]!r} "
            f"results={len(news)}"
        )
        if news:
            _cache_put(cache_key, news)
            return news

    attempts = [cleaned]
    for candidate in _fallback_queries(cleaned):
        if candidate and candidate not in attempts:
            attempts.append(candidate)

    for attempt in attempts:
        try:
            results = _search_once(attempt, max_results)
        except Exception as e:
            last_error = e
            results = []
        logs.info(
            f"WEB search input={query[:120]!r} query={attempt[:200]!r} "
            f"results={len(results)}"
        )
        if results:
            _cache_put(cache_key, results)
            return results

    if last_error is not None:
        logs.warn(f"WEB search failed query={cleaned[:200]!r}: {last_error}")
        return [f"Search failed: {last_error}"]
    return []


def fetch(url: str, timeout: int = None) -> str:
    net = _net_config()
    if timeout is None:
        timeout = net["timeout"]
    current = url
    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            for _ in range(6):
                check_url(current, net)
                resp = client.get(current)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        break
                    next_url = str(httpx.URL(current).join(location))
                    logs.info(f"WEB redirect {current} -> {next_url}")
                    current = next_url
                    continue
                resp.raise_for_status()
                text = _converter.handle(resp.text)
                lines = [l for l in text.split("\n") if l.strip()]
                logs.info(f"WEB fetch {current} status={resp.status_code} len={len(text)}")
                return "\n".join(lines[:200])
            raise ValueError("Too many redirects")
    except ValueError as e:
        logs.warn(f"WEB blocked url={url[:200]!r}: {e}")
        return f"Blocked: {e}"
    except Exception as e:
        logs.warn(f"WEB fetch failed url={url[:200]!r}: {e}")
        return f"Failed to fetch {url}: {e}"
