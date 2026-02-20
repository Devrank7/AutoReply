"""AI-powered client website analysis and outreach message generation."""

import logging
import re

import requests
from google import genai

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.0-flash"


class AnalysisError(Exception):
    pass


class ClientAnalyzer:
    """Analyzes client websites and generates outreach content via Gemini."""

    _SOCIAL_PATTERNS = [
        (r'https?://(?:www\.)?facebook\.com/[^\s"\'<>]+', "Facebook"),
        (r'https?://(?:www\.)?instagram\.com/[^\s"\'<>]+', "Instagram"),
        (r'https?://(?:www\.)?twitter\.com/[^\s"\'<>]+', "Twitter/X"),
        (r'https?://(?:www\.)?x\.com/[^\s"\'<>]+', "Twitter/X"),
        (r'https?://(?:www\.)?linkedin\.com/[^\s"\'<>]+', "LinkedIn"),
        (r'https?://(?:www\.)?youtube\.com/[^\s"\'<>]+', "YouTube"),
        (r'https?://(?:www\.)?tiktok\.com/[^\s"\'<>]+', "TikTok"),
        (r'https?://(?:www\.)?t\.me/[^\s"\'<>]+', "Telegram"),
        (r'https?://(?:www\.)?wa\.me/[^\s"\'<>]+', "WhatsApp"),
        (r'https?://(?:www\.)?pinterest\.com/[^\s"\'<>]+', "Pinterest"),
    ]

    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)

    def fetch_website_content(self, url: str) -> str:
        """Fetch HTML from a client's website (truncated to 50K chars)."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text[:50000]
            logger.info("Fetched %d chars from %s", len(html), url)
            return html
        except requests.RequestException as e:
            logger.error("Failed to fetch %s: %s", url, e)
            raise AnalysisError(f"Could not fetch website: {e}") from e

    def extract_social_links(self, html: str) -> dict:
        """Extract social media links from HTML content.

        Returns dict: {"Instagram": ["https://..."], "Facebook": [...]}
        """
        found = {}
        for pattern, platform in self._SOCIAL_PATTERNS:
            matches = re.findall(pattern, html)
            if matches:
                unique = list(dict.fromkeys(matches))
                found[platform] = unique[:3]
        return found

    def analyze_business(self, website_url: str) -> str:
        """Full pipeline: fetch site -> extract socials -> AI analysis.

        Returns pain points summary (max 500 chars).
        """
        html = self.fetch_website_content(website_url)
        social_links = self.extract_social_links(html)

        if social_links:
            parts = []
            for platform, urls in social_links.items():
                parts.append(f"  {platform}: {', '.join(urls)}")
            social_info = "Social media profiles found:\n" + "\n".join(parts)
        else:
            social_info = "No social media links found on the website."

        prompt = f"""Analyze this business website and provide a concise summary of:
1. What the business does
2. Their likely pain points related to customer communication
3. Small details and hooks that could be used in a sales outreach
4. Opportunities where an AI chat assistant could help them

Website URL: {website_url}

{social_info}

Website HTML content (excerpt):
{html[:30000]}

RULES:
- Maximum 500 characters total in your response
- Be specific to THIS business, not generic
- Focus on pain points and hooks that we can reference in outreach
- No headers or bullet symbols, just plain flowing text
- Write in the SAME language as the website content (if site is in Russian, write in Russian; if in English, write in English)

YOUR ANALYSIS:"""

        try:
            response = self.client.models.generate_content(model=_MODEL, contents=prompt)
            analysis = response.text.strip()
            if len(analysis) > 500:
                analysis = analysis[:497] + "..."
            logger.info("Business analysis complete (%d chars)", len(analysis))
            return analysis
        except Exception as e:
            logger.error("Gemini analysis error: %s", e)
            raise AnalysisError(f"AI analysis failed: {e}") from e

    def generate_first_message(
        self, client_name: str, pain_points: str, short_demo_url: str, website_url: str
    ) -> str:
        """Generate an outreach first message (150-200 words).

        Focuses on business pain points, mentions demo, includes short link.
        No self-introduction.
        """
        prompt = f"""Generate a cold outreach first message for this business.

Business name: {client_name}
Website: {website_url}
Short demo link: {short_demo_url}

Pain points analysis:
{pain_points}

RULES — follow these EXACTLY:
1. 150-200 words, NOT MORE
2. Do NOT introduce who you are or what company you're from
3. Focus entirely on THEIR business pain points
4. Reference specific details about their business from the analysis
5. Mention that a demo has ALREADY been made specifically for their website
6. Include the short demo link naturally in the message
7. End with a soft call-to-action (question, not a command)
8. Write in a conversational, friendly tone — not corporate
9. No subject line, no greeting like "Dear...", just the message body
10. Write in the SAME language as the pain points analysis above

YOUR MESSAGE:"""

        try:
            response = self.client.models.generate_content(model=_MODEL, contents=prompt)
            message = response.text.strip()
            logger.info("First message generated (%d chars)", len(message))
            return message
        except Exception as e:
            logger.error("Gemini message generation error: %s", e)
            raise AnalysisError(f"Message generation failed: {e}") from e
