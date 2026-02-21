"""Google Sheets service — list 'Проверенные лиды' sheets and extract websites."""

import logging
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",  # full access needed for mark-as-written
]
_SHEET_SUFFIX = "Проверенные лиды"


class SheetsServiceError(Exception):
    pass


def normalize_url(url: str) -> str:
    """Strip protocol, www, and trailing slash so URLs can be compared."""
    url = url.lower().strip()
    for prefix in ("https://www.", "http://www.", "https://", "http://", "www."):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    return url.rstrip("/")


def _col_letter(idx: int) -> str:
    """0-based column index → A1 column letter (0→A, 25→Z, 26→AA, …)."""
    result = ""
    n = idx + 1
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


class SheetsService:
    """List 'Проверенные лиды' sheets and extract non-written-to websites."""

    def __init__(self, service_account_path: str | Path):
        self._sa_path = str(service_account_path)
        self._credentials = None

    def _get_creds(self):
        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_file(
                self._sa_path, scopes=_SCOPES,
            )
        return self._credentials

    def list_sheets(self) -> list[dict]:
        """Return [{id, name}] for sheets matching 'Проверен* Лиды/лиды'.

        Fetches all spreadsheets accessible to the service account and filters
        in Python using case-insensitive matching so it handles:
          - "Проверенные Лиды" (capital Л)
          - "Провереные лиды" (typo variant)
        Results are sorted newest-first (name starts with DD.MM.YYYY).
        """
        try:
            drive = build("drive", "v3", credentials=self._get_creds(),
                          cache_discovery=False)
        except Exception as exc:
            raise SheetsServiceError(f"Auth failed: {exc}") from exc

        results = []
        page_token = None
        while True:
            try:
                resp = drive.files().list(
                    q="mimeType='application/vnd.google-apps.spreadsheet'",
                    fields="nextPageToken, files(id, name)",
                    pageSize=100,
                    pageToken=page_token,
                ).execute()
            except Exception as exc:
                raise SheetsServiceError(f"Drive API error: {exc}") from exc

            for f in resp.get("files", []):
                nl = f["name"].lower()
                # Match any "Провер…" sheet that ends with "лиды"
                if "провер" in nl and nl.endswith("лиды"):
                    results.append({"id": f["id"], "name": f["name"]})

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        results.sort(key=lambda x: x["name"], reverse=True)
        logger.info("Found %d verified-leads sheets", len(results))
        return results

    def get_allowed_websites(self, spreadsheet_id: str) -> set[str]:
        """Read the sheet; return normalized websites where Written != yes/true."""
        try:
            svc = build("sheets", "v4", credentials=self._get_creds(),
                        cache_discovery=False)
        except Exception as exc:
            raise SheetsServiceError(f"Auth failed: {exc}") from exc

        try:
            result = svc.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range="A:ZZ",
            ).execute()
        except Exception as exc:
            raise SheetsServiceError(f"Sheets API error: {exc}") from exc

        values = result.get("values", [])
        if len(values) < 2:
            return set()

        headers = [h.strip().lower() for h in values[0]]
        website_col = next((i for i, h in enumerate(headers) if "website" in h), None)
        written_col = next((i for i, h in enumerate(headers) if "written" in h), None)

        if website_col is None:
            logger.warning("Sheet %s has no 'Website' column", spreadsheet_id)
            return set()

        allowed: set[str] = set()
        for row in values[1:]:
            # Skip rows where Written == yes / true / 1
            if written_col is not None and len(row) > written_col:
                if row[written_col].strip().lower() in ("yes", "true", "1"):
                    continue
            if len(row) > website_col:
                url = row[website_col].strip()
                if url:
                    allowed.add(normalize_url(url))

        logger.info("Sheet %s → %d unwritten websites", spreadsheet_id, len(allowed))
        return allowed

    def mark_as_written(self, spreadsheet_id: str, website: str) -> None:
        """Set Written=yes for the row matching the given website URL.

        If the 'Written' column does not exist it is created automatically.
        Raises SheetsServiceError if the website row cannot be found.
        """
        try:
            svc = build("sheets", "v4", credentials=self._get_creds(),
                        cache_discovery=False)
        except Exception as exc:
            raise SheetsServiceError(f"Auth failed: {exc}") from exc

        # Read all data to locate the target row
        try:
            result = svc.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range="A:ZZ",
            ).execute()
        except Exception as exc:
            raise SheetsServiceError(f"Sheets API error: {exc}") from exc

        values = result.get("values", [])
        if not values:
            raise SheetsServiceError("Sheet is empty")

        headers = [h.strip().lower() for h in values[0]]
        website_col = next((i for i, h in enumerate(headers) if "website" in h), None)
        written_col = next((i for i, h in enumerate(headers) if "written" in h), None)

        if website_col is None:
            raise SheetsServiceError("Sheet has no 'Website' column")

        norm = normalize_url(website)
        target_row_idx = None  # position in values[] (0 = header)
        for i, row in enumerate(values[1:], start=1):
            if len(row) > website_col and normalize_url(row[website_col].strip()) == norm:
                target_row_idx = i
                break

        if target_row_idx is None:
            raise SheetsServiceError(f"No sheet row found for website '{website}'")

        # Create 'Written' column header if it doesn't exist yet
        if written_col is None:
            written_col = len(headers)
            col = _col_letter(written_col)
            try:
                svc.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{col}1",
                    valueInputOption="RAW",
                    body={"values": [["Written"]]},
                ).execute()
                logger.info("Created 'Written' column %s in sheet %s", col, spreadsheet_id)
            except Exception as exc:
                raise SheetsServiceError(
                    f"Could not create 'Written' column: {exc}") from exc

        # Write "yes" to the matching row
        col = _col_letter(written_col)
        sheet_row = target_row_idx + 1  # 1-indexed (row 1 = header)
        try:
            svc.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{col}{sheet_row}",
                valueInputOption="RAW",
                body={"values": [["yes"]]},
            ).execute()
        except Exception as exc:
            raise SheetsServiceError(
                f"Could not write to {col}{sheet_row}: {exc}") from exc

        logger.info("Marked '%s' as written (sheet %s, row %d, col %s)",
                    website, spreadsheet_id, sheet_row, col)
