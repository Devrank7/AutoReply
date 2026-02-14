import logging
from PIL import Image
import google.generativeai as genai

from config import GEMINI_API_KEY, SYSTEM_PROMPT_PATH

logger = logging.getLogger(__name__)


class AIAgent:
    def __init__(self):
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    def _load_system_prompt(self) -> str:
        """Load system prompt from file (re-reads each time for hot-reload)."""
        with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()

    # ── Universal text-based method (primary for desktop app) ────────

    def generate_reply_from_text(self, extracted_text: str, app_name: str = "Unknown",
                                  previous_suggestion: str | None = None) -> str:
        """Generate a sales reply from extracted conversation text.

        This is the primary method — uses macOS Accessibility API
        to read actual text from any chat window.
        """
        system_prompt = self._load_system_prompt()

        regen_note = ""
        if previous_suggestion:
            regen_note = f"""

IMPORTANT: The manager REJECTED the previous suggestion below.
Generate a COMPLETELY DIFFERENT reply with a different approach/angle.
Do NOT repeat or rephrase the same message.

REJECTED SUGGESTION:
{previous_suggestion}
"""

        prompt = f"""{system_prompt}

---

## YOUR TASK

Below is the raw text extracted from a chat window in the application "{app_name}".
The text was captured programmatically — it may contain some UI elements (buttons, labels)
mixed in with the actual conversation. Your job is to:

1. IDENTIFY which parts are the actual conversation messages (ignore UI noise like button labels, menu items, timestamps markers)
2. DETERMINE who is the CLIENT and who is the MANAGER in this conversation
3. IDENTIFY the latest client message that needs a reply
4. DETERMINE the platform (Telegram, Instagram, Gmail, WhatsApp, etc.) from the app name and context
5. GENERATE the best possible reply following your system prompt guidelines
{regen_note}
RULES:
- Write ONLY the reply text — no headers, no "AI suggests:", no explanations
- Match the client's language (Russian, Ukrainian, English, etc.)
- Follow the response format rules for the detected platform
- Be specific to their question/business
- End with a question or clear next step
- Keep it concise: 2-5 sentences for chat, 5-8 for email

---

## RAW TEXT FROM CHAT WINDOW:

{extracted_text}

---

YOUR REPLY:
"""
        try:
            response = self.model.generate_content(prompt)
            reply = response.text.strip()
            logger.info("Text-based AI generated reply (%d chars)", len(reply))
            return reply
        except Exception as e:
            logger.error("Gemini API error (text-based): %s", e)
            raise

    # ── Vision-based method (fallback for desktop app) ─────────────

    def generate_reply_from_screenshot(self, image_path: str,
                                        previous_suggestion: str | None = None) -> str:
        """Read a chat screenshot with Gemini Vision and generate a sales reply."""
        system_prompt = self._load_system_prompt()
        img = Image.open(image_path)

        regen_note = ""
        if previous_suggestion:
            regen_note = f"""

IMPORTANT: The manager REJECTED the previous suggestion below.
Generate a COMPLETELY DIFFERENT reply with a different approach/angle.
Do NOT repeat or rephrase the same message.

REJECTED SUGGESTION:
{previous_suggestion}
"""

        vision_prompt = f"""{system_prompt}

---

## YOUR TASK

Look at the screenshot above. It shows a chat conversation between a client and a manager.

1. READ the conversation carefully — identify all messages and who sent them.
2. IDENTIFY the latest client message that needs a reply.
3. DETERMINE which platform this is (Telegram, Instagram, Gmail, WhatsApp, etc.)
4. GENERATE the best possible reply following your system prompt guidelines.
{regen_note}
RULES:
- Write ONLY the reply text — no headers, no "AI suggests:", no explanations
- Match the client's language (Russian, Ukrainian, English, etc.)
- Follow the response format rules for the detected platform
- Be specific to their question/business
- End with a question or clear next step
- Keep it concise: 2-5 sentences for chat, 5-8 for email

YOUR REPLY:
"""
        try:
            response = self.model.generate_content([vision_prompt, img])
            reply = response.text.strip()
            logger.info("Vision AI generated reply (%d chars)", len(reply))
            return reply
        except Exception as e:
            logger.error("Gemini Vision API error: %s", e)
            raise

    # ── Text-based methods (for Gmail bot mode) ───────────────────

    def _build_context(self, thread_messages: list[dict], channel: str = "email") -> str:
        """Build the full context for the AI from conversation thread."""
        system_prompt = self._load_system_prompt()

        conversation_text = ""
        for msg in thread_messages:
            role = "CLIENT" if msg.get("is_from_client") else "MANAGER (you)"
            name = msg.get("sender_name", msg.get("sender_email", "Unknown"))
            body = msg.get("body", "").strip()
            conversation_text += f"\n[{role} — {name}]:\n{body}\n"

        context = f"""{system_prompt}

---

## CURRENT TASK

You are now helping the manager respond to a real client conversation.
Channel: {channel}

Below is the full conversation thread. The last message is from the CLIENT.
Generate the BEST possible reply that follows your system prompt guidelines.

IMPORTANT:
- Write ONLY the reply text — no headers, no metadata, no explanations
- Follow the response format rules for {channel} from your system prompt
- Match the client's language
- Be specific to their business/question
- End with a question or clear next step

---

## CONVERSATION THREAD:
{conversation_text}

---

## YOUR RESPONSE (write only the reply text):
"""
        return context

    async def generate_reply(self, thread_messages: list[dict],
                             channel: str = "email") -> str:
        """Generate a sales reply based on conversation context."""
        context = self._build_context(thread_messages, channel)

        try:
            response = self.model.generate_content(context)
            reply = response.text.strip()
            logger.info("AI generated reply (%d chars)", len(reply))
            return reply
        except Exception as e:
            logger.error("Gemini API error: %s", e)
            raise

    async def regenerate_reply(self, thread_messages: list[dict],
                               previous_suggestion: str,
                               channel: str = "email") -> str:
        """Generate a different reply, avoiding the previous suggestion."""
        context = self._build_context(thread_messages, channel)
        context += f"""

NOTE: The manager rejected the previous suggestion below. Generate a DIFFERENT reply
with a different approach/angle. Do NOT repeat the same message.

REJECTED SUGGESTION:
{previous_suggestion}

YOUR NEW RESPONSE (write only the reply text):
"""
        try:
            response = self.model.generate_content(context)
            reply = response.text.strip()
            logger.info("AI regenerated reply (%d chars)", len(reply))
            return reply
        except Exception as e:
            logger.error("Gemini API error on regeneration: %s", e)
            raise
