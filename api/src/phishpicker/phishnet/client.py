import httpx


class PhishNetError(Exception):
    pass


class PhishNetClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.phish.net/v5",
        timeout: float = 30.0,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> "PhishNetClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get(self, path: str, params: dict) -> list[dict]:
        # Put apikey FIRST so generated URLs have predictable query-string order
        # (matters for test URL matching in pytest-httpx).
        params = {"apikey": self._api_key, **params}
        try:
            r = self._client.get(f"{self._base_url}/{path}", params=params)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PhishNetError(f"HTTP {exc.response.status_code} from {path}") from exc
        except httpx.RequestError as exc:
            raise PhishNetError(f"Request failed for {path}: {exc}") from exc
        body = r.json()
        if body.get("error"):
            raise PhishNetError(body.get("error_message") or "phish.net error")
        return body.get("data", [])

    def fetch_all_shows(self) -> list[dict]:
        """Fetch all shows from phish.net, unfiltered. v5 returns full history."""
        return self._get("shows.json", {"order_by": "showdate", "direction": "desc"})

    def fetch_upcoming_shows(self, from_date: str) -> list[dict]:
        """Phish-only shows on or after from_date (YYYY-MM-DD), asc by date.

        NB: phish.net v5 `shows.json` ignores `direction=asc` in practice —
        results come back newest-first. So we sort the filtered slice in
        Python before returning.
        """
        data = self._get("shows.json", {"order_by": "showdate"})
        filtered = [
            d
            for d in data
            if str(d.get("artist_name")) == "Phish"
            and str(d.get("showdate", "")) >= from_date
        ]
        filtered.sort(key=lambda d: str(d.get("showdate", "")))
        return filtered

    def fetch_setlist_by_date(self, show_date: str) -> list[dict]:
        """Phish-only rows for the show on show_date."""
        data = self._get(f"setlists/showdate/{show_date}.json", {})
        return [d for d in data if str(d.get("artist_name")) == "Phish"]

    def fetch_setlist(self, show_id: int) -> list[dict]:
        # v5 takes showid as a path parameter, not a query string. The older
        # ?showid=X form returns {data: []} silently — no error, no data — so
        # the bug went undetected until the first real ingest.
        return self._get(f"setlists/showid/{show_id}.json", {})

    def fetch_songs(self) -> list[dict]:
        return self._get("songs.json", {})

    def fetch_venues(self) -> list[dict]:
        return self._get("venues.json", {})

    def close(self) -> None:
        self._client.close()
