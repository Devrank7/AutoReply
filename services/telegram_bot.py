import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_MANAGER_CHAT_ID

logger = logging.getLogger(__name__)

# Store pending edits: chat_id -> conversation data
_pending_edits: dict[int, dict] = {}


def _is_manager(chat_id: int) -> bool:
    return str(chat_id) == str(TELEGRAM_MANAGER_CHAT_ID)


def _truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for ch in text:
        if ch in special:
            escaped += "\\" + ch
        else:
            escaped += ch
    return escaped


class TelegramBot:
    def __init__(self, gmail_service=None, ai_agent=None):
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.gmail_service = gmail_service
        self.ai_agent = ai_agent

        # Register handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_manager(update.effective_chat.id):
            await update.message.reply_text("Access denied.")
            return

        await update.message.reply_text(
            "AutoReply Bot activated!\n\n"
            "I'll notify you when new client emails arrive "
            "and suggest AI-generated responses.\n\n"
            "Commands:\n"
            "/status — Show pending conversations\n"
            "/help — Show help"
        )
        logger.info("Manager started bot, chat_id: %s", update.effective_chat.id)

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_manager(update.effective_chat.id):
            return

        from database import get_pending_conversations
        conversations = await get_pending_conversations()

        if not conversations:
            await update.message.reply_text("No pending conversations.")
            return

        lines = [f"Pending conversations: {len(conversations)}\n"]
        for conv in conversations[:10]:
            lines.append(
                f"• {conv['sender_name'] or conv['sender_email']} — "
                f"{conv['subject'] or '(no subject)'} [{conv['status']}]"
            )
        await update.message.reply_text("\n".join(lines))

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "AutoReply — AI Sales Assistant\n\n"
            "How it works:\n"
            "1. New email arrives → I send you the message + AI suggestion\n"
            "2. You choose: Send / Edit / Regenerate / Skip\n"
            "3. If you tap Send — reply goes to the client via Gmail\n\n"
            "Commands:\n"
            "/status — Pending conversations\n"
            "/help — This message"
        )

    async def notify_new_email(self, conversation_data: dict, ai_suggestion: str):
        """Send notification to manager about a new email with AI suggestion."""
        chat_id = int(TELEGRAM_MANAGER_CHAT_ID)

        sender = conversation_data.get("sender_name") or conversation_data.get("sender_email", "Unknown")
        subject = conversation_data.get("subject", "(no subject)")
        last_message = conversation_data.get("last_message_body", "")
        conv_id = conversation_data.get("conversation_id")
        thread_id = conversation_data.get("thread_id")

        text = (
            f"📩 New email from: {sender}\n"
            f"📋 Subject: {subject}\n\n"
            f"💬 Client's message:\n"
            f"{_truncate(last_message, 500)}\n\n"
            f"{'─' * 30}\n\n"
            f"🤖 AI suggests:\n"
            f"{ai_suggestion}"
        )

        callback_data = json.dumps({
            "cid": conv_id,
            "tid": thread_id,
        })

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Send", callback_data=f"send|{conv_id}"),
                InlineKeyboardButton("✏️ Edit", callback_data=f"edit|{conv_id}"),
            ],
            [
                InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen|{conv_id}"),
                InlineKeyboardButton("❌ Skip", callback_data=f"skip|{conv_id}"),
            ],
        ])

        # Store the suggestion and conversation data for later use
        self.app.bot_data[f"conv_{conv_id}"] = {
            **conversation_data,
            "ai_suggestion": ai_suggestion,
        }

        await self.app.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
        )
        logger.info("Notification sent to manager for conversation %s", conv_id)

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if not _is_manager(query.from_user.id):
            return

        data = query.data
        action, conv_id_str = data.split("|", 1)
        conv_id = int(conv_id_str)

        conv_data = context.bot_data.get(f"conv_{conv_id}")
        if not conv_data:
            await query.edit_message_text("Conversation data expired. Please wait for next poll.")
            return

        if action == "send":
            await self._action_send(query, conv_data)
        elif action == "edit":
            await self._action_edit(query, conv_data)
        elif action == "regen":
            await self._action_regen(query, conv_data)
        elif action == "skip":
            await self._action_skip(query, conv_data)

    async def _action_send(self, query, conv_data: dict):
        """Send the AI-suggested reply via Gmail."""
        from database import update_conversation_status, add_message

        suggestion = conv_data["ai_suggestion"]
        thread_id = conv_data["thread_id"]
        sender_email = conv_data["sender_email"]
        subject = conv_data.get("subject", "")
        last_msg_id = conv_data.get("last_message_id", "")
        conv_id = conv_data["conversation_id"]

        try:
            self.gmail_service.send_reply(
                thread_id=thread_id,
                message_id=last_msg_id,
                to=sender_email,
                subject=subject,
                body=suggestion,
            )
            await add_message(conv_id, "manager", suggestion)
            await update_conversation_status(conv_id, "replied")
            await query.edit_message_text(
                f"✅ Reply sent to {sender_email}!\n\n"
                f"Sent message:\n{_truncate(suggestion, 200)}"
            )
            logger.info("Reply sent for conversation %s", conv_id)
        except Exception as e:
            logger.error("Failed to send reply: %s", e)
            await query.edit_message_text(f"❌ Error sending reply: {e}")

    async def _action_edit(self, query, conv_data: dict):
        """Prompt manager to type a custom reply."""
        conv_id = conv_data["conversation_id"]
        chat_id = query.from_user.id

        _pending_edits[chat_id] = conv_data

        await query.edit_message_text(
            f"✏️ Editing reply for: {conv_data.get('sender_name', conv_data['sender_email'])}\n\n"
            f"Current AI suggestion:\n{conv_data['ai_suggestion']}\n\n"
            f"Type your message below. It will be sent as the reply."
        )

    async def _action_regen(self, query, conv_data: dict):
        """Regenerate AI suggestion with a different angle."""
        from database import get_conversation_messages

        conv_id = conv_data["conversation_id"]
        old_suggestion = conv_data["ai_suggestion"]

        await query.edit_message_text("🔄 Regenerating AI suggestion...")

        try:
            messages = await get_conversation_messages(conv_id)
            thread_messages = conv_data.get("thread_messages", [])

            new_suggestion = await self.ai_agent.regenerate_reply(
                thread_messages, old_suggestion, channel="email"
            )

            conv_data["ai_suggestion"] = new_suggestion
            self.app.bot_data[f"conv_{conv_id}"] = conv_data

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Send", callback_data=f"send|{conv_id}"),
                    InlineKeyboardButton("✏️ Edit", callback_data=f"edit|{conv_id}"),
                ],
                [
                    InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen|{conv_id}"),
                    InlineKeyboardButton("❌ Skip", callback_data=f"skip|{conv_id}"),
                ],
            ])

            sender = conv_data.get("sender_name") or conv_data.get("sender_email", "Unknown")
            text = (
                f"📩 Email from: {sender}\n\n"
                f"🤖 NEW AI suggestion:\n"
                f"{new_suggestion}"
            )
            await query.edit_message_text(text=text, reply_markup=keyboard)
        except Exception as e:
            logger.error("Regeneration error: %s", e)
            await query.edit_message_text(f"❌ Regeneration failed: {e}")

    async def _action_skip(self, query, conv_data: dict):
        """Skip this conversation."""
        from database import update_conversation_status

        conv_id = conv_data["conversation_id"]
        await update_conversation_status(conv_id, "skipped")
        sender = conv_data.get("sender_name", conv_data["sender_email"])
        await query.edit_message_text(f"⏭️ Skipped conversation with {sender}")

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle free-text messages — check if manager is editing a reply."""
        chat_id = update.effective_chat.id

        if not _is_manager(chat_id):
            return

        if chat_id not in _pending_edits:
            await update.message.reply_text(
                "No active edit session. Wait for a new email notification."
            )
            return

        conv_data = _pending_edits.pop(chat_id)
        custom_reply = update.message.text
        conv_id = conv_data["conversation_id"]
        thread_id = conv_data["thread_id"]
        sender_email = conv_data["sender_email"]
        subject = conv_data.get("subject", "")
        last_msg_id = conv_data.get("last_message_id", "")

        from database import update_conversation_status, add_message

        try:
            self.gmail_service.send_reply(
                thread_id=thread_id,
                message_id=last_msg_id,
                to=sender_email,
                subject=subject,
                body=custom_reply,
            )
            await add_message(conv_id, "manager", custom_reply)
            await update_conversation_status(conv_id, "replied")
            await update.message.reply_text(
                f"✅ Your custom reply sent to {sender_email}!"
            )
        except Exception as e:
            logger.error("Failed to send custom reply: %s", e)
            await update.message.reply_text(f"❌ Error sending reply: {e}")

    def get_application(self) -> Application:
        return self.app
