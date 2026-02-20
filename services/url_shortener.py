"""URL shortener using the free v.gd / is.gd API (no auth needed)."""

import logging

import requests

logger = logging.getLogger(__name__)


class ShortenError(Exception):
    pass


def shorten_url(long_url: str) -> str:
    """Shorten a URL using v.gd API (shortest domain, ~14 chars).

    Falls back to is.gd if v.gd fails.
    Raises ShortenError if all services fail.
    """
    for api_base in ("https://v.gd", "https://is.gd"):
        try:
            resp = requests.get(
                f"{api_base}/create.php",
                params={"format": "simple", "url": long_url},
                timeout=10,
            )
            resp.raise_for_status()
            short = resp.text.strip()
            if short.startswith("http"):
                logger.info("Shortened: %s -> %s", long_url[:60], short)
                return short
        except requests.RequestException as e:
            logger.warning("Shortener %s failed: %s", api_base, e)
            continue

    raise ShortenError("All URL shortener services failed. Copy the full URL manually.")
