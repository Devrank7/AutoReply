"""URL shortener using the free v.gd / is.gd API (no auth needed)."""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)


class ShortenError(Exception):
    pass


def shorten_url(long_url: str) -> str:
    """Shorten a URL using v.gd API (shortest domain, ~14 chars).

    Falls back to is.gd if v.gd fails.
    Raises ShortenError if all services fail.
    """
    # The demo URL may contain already-encoded chars (e.g. %3A in website= param).
    # Decode once so requests can re-encode cleanly without double-encoding.
    clean_url = urllib.parse.unquote(long_url)

    # TinyURL: free, no auth, tolerates complex nested URLs.
    # v.gd/is.gd blacklist winbix-ai.pp.ua ("looks like redirect service").
    try:
        resp = requests.get(
            "https://tinyurl.com/api-create.php",
            params={"url": clean_url},
            timeout=10,
        )
        resp.raise_for_status()
        short = resp.text.strip()
        if short.startswith("http"):
            logger.info("Shortened: %s -> %s", long_url[:60], short)
            return short
    except requests.RequestException as e:
        logger.warning("TinyURL failed: %s", e)

    # Fallback: is.gd (may reject some domains but worth trying)
    try:
        resp = requests.get(
            "https://is.gd/create.php",
            params={"format": "simple", "url": clean_url},
            timeout=10,
        )
        resp.raise_for_status()
        short = resp.text.strip()
        if short.startswith("http"):
            logger.info("Shortened via is.gd: %s -> %s", long_url[:60], short)
            return short
    except requests.RequestException as e:
        logger.warning("is.gd failed: %s", e)

    raise ShortenError("All URL shortener services failed. Copy the full URL manually.")
