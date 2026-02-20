"""Client API service for fetching demo client data from Winbix API."""

import logging
import time

import requests

from config import CLIENT_API_BASE_URL

logger = logging.getLogger(__name__)


class ClientAPIError(Exception):
    pass


class ClientAPI:
    """Fetches and caches client data from the Winbix AI API."""

    def __init__(self, base_url: str = None):
        self.base_url = (base_url or CLIENT_API_BASE_URL).rstrip("/")
        self._cache = None
        self._cache_time = None

    def fetch_clients(self, force_refresh: bool = False) -> list:
        """GET /api/clients/demo — returns list of client dicts.

        Caches results for 5 minutes.
        """
        if (
            not force_refresh
            and self._cache is not None
            and self._cache_time
            and time.time() - self._cache_time < 300
        ):
            return self._cache

        url = f"{self.base_url}/api/clients/demo"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Client API request failed: %s", e)
            raise ClientAPIError(f"Failed to fetch clients: {e}") from e

        if not data.get("success"):
            raise ClientAPIError("API returned success=false")

        clients = data.get("clients", [])
        self._cache = clients
        self._cache_time = time.time()
        logger.info("Fetched %d clients from API", len(clients))
        return clients

    def search_clients(self, query: str, date_from: str = None, date_to: str = None) -> list:
        """Filter cached clients by name and optional date range.

        Args:
            query: substring match against client name (case-insensitive)
            date_from: ISO date "YYYY-MM-DD" — on or after
            date_to: ISO date "YYYY-MM-DD" — on or before
        """
        clients = self._cache or []
        results = []

        for c in clients:
            if query and query.lower() not in c.get("name", "").lower():
                continue

            created = c.get("createdAt", "") or ""
            if date_from and created[:10] < date_from:
                continue
            if date_to and created[:10] > date_to:
                continue

            results.append(c)

        return results
