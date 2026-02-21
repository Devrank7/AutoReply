"""URL shortener using the free spoo.me API (no auth needed, ~23 chars)."""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)


class ShortenError(Exception):
    pass


def shorten_url(long_url: str) -> str:
    """Shorten a URL using spoo.me API (~23 chars).

    Falls back to TinyURL if spoo.me fails.
    Raises ShortenError if all services fail.
    """
    # The demo URL may contain already-encoded chars (e.g. %3A in website= param).
    # Decode once so requests can re-encode cleanly without double-encoding.
    clean_url = urllib.parse.unquote(long_url)

    # spoo.me: free, no auth, short links (~23 chars), accepts winbix-ai.pp.ua.
    try:
        resp = requests.post(
            "https://spoo.me/",
            data={"url": clean_url},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        short = resp.json().get("short_url", "")
        if short.startswith("http"):
            logger.info("Shortened: %s -> %s", long_url[:60], short)
            return short
    except (requests.RequestException, ValueError) as e:
        logger.warning("spoo.me failed: %s", e)

    # Fallback: TinyURL (longer links ~29 chars, but very reliable).
    try:
        resp = requests.get(
            "https://tinyurl.com/api-create.php",
            params={"url": clean_url},
            timeout=10,
        )
        resp.raise_for_status()
        short = resp.text.strip()
        if short.startswith("http"):
            logger.info("Shortened via TinyURL: %s -> %s", long_url[:60], short)
            return short
    except requests.RequestException as e:
        logger.warning("TinyURL failed: %s", e)

    raise ShortenError("All URL shortener services failed. Copy the full URL manually.")
