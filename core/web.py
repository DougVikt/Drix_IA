import httpx
import html2text
import ipaddress
import socket
import yaml
from pathlib import Path
from urllib.parse import urlparse
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
    try:
        with DDGS() as ddgs:
            results = [
                f"{r['title']}\n  {r['href']}\n  {r.get('body', '')}"
                for r in ddgs.text(query, max_results=max_results)
            ]
        logs.info(f"WEB search query={query[:200]!r} results={len(results)}")
        return results
    except Exception as e:
        logs.warn(f"WEB search failed query={query[:200]!r}: {e}")
        return [f"Search failed: {e}"]


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
