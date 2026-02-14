import base64
import logging
import re
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GMAIL_CREDENTIALS_PATH, GMAIL_TOKEN_PATH

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailService:
    def __init__(self):
        self.service = None
        self.my_email = None
        self._last_history_id = None

    def authenticate(self):
        creds = None
        token_path = Path(GMAIL_TOKEN_PATH)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(GMAIL_CREDENTIALS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)

        profile = self.service.users().getProfile(userId="me").execute()
        self.my_email = profile["emailAddress"]
        logger.info("Gmail authenticated as %s", self.my_email)

    def get_new_messages(self, max_results: int = 10) -> list[dict]:
        results = (
            self.service.users()
            .messages()
            .list(
                userId="me",
                labelIds=["INBOX"],
                q="is:unread category:primary",
                maxResults=max_results,
            )
            .execute()
        )
        return results.get("messages", [])

    def get_thread(self, thread_id: str) -> dict:
        thread = (
            self.service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
        return thread

    def parse_thread_messages(self, thread: dict) -> list[dict]:
        messages = []
        for msg in thread.get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
            sender = headers.get("from", "")
            subject = headers.get("subject", "")
            date = headers.get("date", "")

            body = self._extract_body(msg["payload"])

            sender_email = self._extract_email(sender)
            sender_name = self._extract_name(sender)
            is_from_client = sender_email != self.my_email

            messages.append({
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "sender_email": sender_email,
                "sender_name": sender_name,
                "subject": subject,
                "date": date,
                "body": body,
                "is_from_client": is_from_client,
            })
        return messages

    def send_reply(self, thread_id: str, message_id: str,
                   to: str, subject: str, body: str):
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        message["In-Reply-To"] = message_id
        message["References"] = message_id

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            self.service.users()
            .messages()
            .send(userId="me", body={"raw": raw, "threadId": thread_id})
            .execute()
        )
        logger.info("Reply sent to %s, message id: %s", to, sent["id"])
        return sent

    def mark_as_read(self, message_id: str):
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()

    def _extract_body(self, payload: dict) -> str:
        if payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        parts = payload.get("parts", [])
        for part in parts:
            if part["mimeType"] == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

        for part in parts:
            if part["mimeType"] == "text/html" and part.get("body", {}).get("data"):
                html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                return self._html_to_text(html)

        for part in parts:
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        return ""

    @staticmethod
    def _html_to_text(html: str) -> str:
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _extract_email(from_header: str) -> str:
        match = re.search(r"<(.+?)>", from_header)
        return match.group(1) if match else from_header.strip()

    @staticmethod
    def _extract_name(from_header: str) -> str:
        match = re.match(r'^"?(.+?)"?\s*<', from_header)
        return match.group(1).strip() if match else ""
