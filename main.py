import asyncio
import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import GMAIL_POLL_INTERVAL, TELEGRAM_MANAGER_CHAT_ID
from database import init_db, upsert_conversation, add_message, get_conversation_by_thread
from services.gmail_service import GmailService
from services.ai_agent import AIAgent
from services.telegram_bot import TelegramBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Shared services
gmail_service = GmailService()
ai_agent = AIAgent()
telegram_bot = TelegramBot(gmail_service=gmail_service, ai_agent=ai_agent)

# Track processed message IDs to avoid duplicates
_processed_message_ids: set[str] = set()


async def poll_gmail():
    """Check Gmail for new unread messages and process them."""
    try:
        new_messages = gmail_service.get_new_messages(max_results=5)

        if not new_messages:
            return

        for msg_info in new_messages:
            msg_id = msg_info["id"]
            thread_id = msg_info["threadId"]

            if msg_id in _processed_message_ids:
                continue

            # Get full thread
            thread = gmail_service.get_thread(thread_id)
            parsed_messages = gmail_service.parse_thread_messages(thread)

            if not parsed_messages:
                continue

            last_msg = parsed_messages[-1]

            # Skip if last message is from us (we already replied)
            if not last_msg["is_from_client"]:
                _processed_message_ids.add(msg_id)
                gmail_service.mark_as_read(msg_id)
                continue

            # Upsert conversation in DB
            conv_id = await upsert_conversation(
                thread_id=thread_id,
                sender_email=last_msg["sender_email"],
                sender_name=last_msg["sender_name"],
                subject=last_msg["subject"],
            )

            # Store client message
            await add_message(conv_id, "client", last_msg["body"])

            # Generate AI suggestion
            logger.info(
                "New email from %s — generating AI reply...",
                last_msg["sender_email"],
            )
            ai_suggestion = await ai_agent.generate_reply(
                parsed_messages, channel="email"
            )

            # Store AI suggestion
            await add_message(conv_id, "ai_suggestion", ai_suggestion)

            # Notify manager via Telegram
            conversation_data = {
                "conversation_id": conv_id,
                "thread_id": thread_id,
                "sender_email": last_msg["sender_email"],
                "sender_name": last_msg["sender_name"],
                "subject": last_msg["subject"],
                "last_message_body": last_msg["body"],
                "last_message_id": last_msg["id"],
                "thread_messages": parsed_messages,
            }

            await telegram_bot.notify_new_email(conversation_data, ai_suggestion)

            # Mark as read and track
            gmail_service.mark_as_read(msg_id)
            _processed_message_ids.add(msg_id)

            logger.info(
                "Processed email from %s, conversation #%d",
                last_msg["sender_email"],
                conv_id,
            )

    except Exception as e:
        logger.error("Gmail polling error: %s", e, exc_info=True)


async def main():
    logger.info("=" * 50)
    logger.info("AutoReply — AI Sales Assistant")
    logger.info("=" * 50)

    # Validate config
    if not TELEGRAM_MANAGER_CHAT_ID or TELEGRAM_MANAGER_CHAT_ID == "your_chat_id_here":
        logger.error(
            "TELEGRAM_MANAGER_CHAT_ID is not set. "
            "Send /start to your bot and check the logs for your chat_id, "
            "then add it to .env"
        )

    # Init database
    await init_db()
    logger.info("Database initialized")

    # Authenticate Gmail
    gmail_service.authenticate()
    logger.info("Gmail authenticated")

    # Start scheduler for Gmail polling
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_gmail,
        "interval",
        seconds=GMAIL_POLL_INTERVAL,
        id="gmail_poll",
        max_instances=1,
    )
    scheduler.start()
    logger.info("Gmail polling started (every %ds)", GMAIL_POLL_INTERVAL)

    # Run initial poll
    await poll_gmail()

    # Start Telegram bot (this runs forever)
    logger.info("Starting Telegram bot...")
    app = telegram_bot.get_application()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Bot is running! Send /start to your bot in Telegram.")

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
