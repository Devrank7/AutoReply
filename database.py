import aiosqlite
from datetime import datetime
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_thread_id TEXT UNIQUE NOT NULL,
                sender_email TEXT NOT NULL,
                sender_name TEXT DEFAULT '',
                subject TEXT DEFAULT '',
                last_message_at TEXT NOT NULL,
                status TEXT DEFAULT 'new'
                    CHECK(status IN ('new', 'pending', 'replied', 'skipped'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL
                    CHECK(role IN ('client', 'manager', 'ai_suggestion')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)
        await db.commit()


async def upsert_conversation(thread_id: str, sender_email: str,
                               sender_name: str, subject: str) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM conversations WHERE gmail_thread_id = ?",
            (thread_id,),
        )
        row = await cursor.fetchone()
        if row:
            await db.execute(
                "UPDATE conversations SET last_message_at = ? WHERE id = ?",
                (now, row[0]),
            )
            await db.commit()
            return row[0]
        else:
            cursor = await db.execute(
                """INSERT INTO conversations
                   (gmail_thread_id, sender_email, sender_name, subject, last_message_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (thread_id, sender_email, sender_name, subject, now),
            )
            await db.commit()
            return cursor.lastrowid


async def add_message(conversation_id: int, role: str, content: str) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO messages (conversation_id, role, content, created_at)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, role, content, now),
        )
        await db.commit()
        return cursor.lastrowid


async def get_conversation_messages(conversation_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT role, content, created_at FROM messages
               WHERE conversation_id = ?
               ORDER BY created_at ASC""",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_conversation_by_thread(thread_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM conversations WHERE gmail_thread_id = ?",
            (thread_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_conversation_status(conversation_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE conversations SET status = ? WHERE id = ?",
            (status, conversation_id),
        )
        await db.commit()


async def get_pending_conversations() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM conversations
               WHERE status IN ('new', 'pending')
               ORDER BY last_message_at DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
