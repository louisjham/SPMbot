"""
SQLite Store - Persistent storage for Kali Agent.

This module provides async SQLite storage for conversations, tasks,
and skill executions using aiosqlite.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import aiosqlite

if TYPE_CHECKING:
    from tasks.models import AgentTask

logger = logging.getLogger(__name__)


class SQLiteStore:
    """
    Async SQLite storage backend for Kali Agent.
    
    Provides persistent storage for conversations, messages, tasks,
    and skill executions with async operations using aiosqlite.
    
    Example:
        async with SQLiteStore("./data/agent.db") as store:
            await store.save_conversation(conv_data)
    """
    
    def __init__(
        self,
        db_path: str = "./data/kali_agent.db",
        enable_wal: bool = True,
    ) -> None:
        """
        Initialize the SQLite store.
        
        Args:
            db_path: Path to the SQLite database file.
            enable_wal: Whether to enable WAL mode for better concurrency.
        """
        self.db_path = db_path
        self.enable_wal = enable_wal
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
    
    async def connect(self) -> None:
        """
        Establish database connection and create tables.
        
        Creates the database file and tables if they don't exist.
        """
        # Ensure directory exists
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._db = await aiosqlite.connect(self.db_path)
        
        # Enable WAL mode for better concurrency
        if self.enable_wal:
            await self._db.execute("PRAGMA journal_mode=WAL")
        
        # Enable foreign keys
        await self._db.execute("PRAGMA foreign_keys=ON")
        
        # Create tables
        await self._create_tables()
        
        logger.info(f"Connected to SQLite database: {self.db_path}")
    
    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        await self._db.executescript("""
            -- Conversations table
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            
            -- Messages table
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                tool_call_id TEXT,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
            );
            
            -- Tasks table
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                conversation_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                command TEXT NOT NULL,
                parameters TEXT DEFAULT '{}',
                priority INTEGER DEFAULT 5,
                timeout INTEGER DEFAULT 300,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                require_confirmation INTEGER DEFAULT 0,
                confirmed INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}'
            );
            
            -- Task results table
            CREATE TABLE IF NOT EXISTS task_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                success INTEGER NOT NULL,
                output TEXT DEFAULT '',
                data TEXT DEFAULT '{}',
                error TEXT,
                execution_time REAL DEFAULT 0.0,
                completed_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            
            -- Skill executions table
            CREATE TABLE IF NOT EXISTS skill_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                skill_name TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                success INTEGER NOT NULL,
                output TEXT DEFAULT '',
                data TEXT DEFAULT '{}',
                error TEXT,
                execution_time REAL DEFAULT 0.0,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            );
            
            -- Findings table: stores extracted IPs, domains, URLs, etc.
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                finding_type TEXT NOT NULL,
                value TEXT NOT NULL,
                target TEXT,
                source_skill TEXT NOT NULL,
                source_output TEXT,
                context TEXT DEFAULT '{}',
                confidence REAL DEFAULT 1.0,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                UNIQUE(task_id, finding_type, value, target)
            );
            
            -- Artifacts table: tracks files/outputs generated by skills
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                path TEXT,
                content_hash TEXT,
                size_bytes INTEGER,
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            
            -- Indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_skill_execs_user ON skill_executions(user_id);
            CREATE INDEX IF NOT EXISTS idx_skill_execs_skill ON skill_executions(skill_name);
            CREATE INDEX IF NOT EXISTS idx_findings_type ON findings(finding_type);
            CREATE INDEX IF NOT EXISTS idx_findings_value ON findings(value);
            CREATE INDEX IF NOT EXISTS idx_findings_task ON findings(task_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
        """)
        await self._db.commit()
    
    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("SQLite connection closed")
    
    @asynccontextmanager
    async def lifespan(self):
        """
        Async context manager for store lifecycle.
        
        Yields:
            The store instance.
        """
        await self.connect()
        try:
            yield self
        finally:
            await self.close()
    
    # ==================== Conversation Operations ====================
    
    async def save_conversation(self, data: dict[str, Any]) -> None:
        """
        Save or update a conversation.
        
        Args:
            data: Conversation data dictionary.
        """
        async with self._lock:
            await self._db.execute("""
                INSERT INTO conversations (conversation_id, user_id, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    metadata = excluded.metadata
            """, (
                data["conversation_id"],
                data["user_id"],
                data.get("created_at", datetime.utcnow().isoformat()),
                data.get("updated_at", datetime.utcnow().isoformat()),
                json.dumps(data.get("metadata", {})),
            ))
            await self._db.commit()
    
    async def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        """
        Get a conversation by ID.
        
        Args:
            conversation_id: The conversation identifier.
        
        Returns:
            Conversation data or None if not found.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (conversation_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "conversation_id": row[0],
                        "user_id": row[1],
                        "created_at": row[2],
                        "updated_at": row[3],
                        "metadata": json.loads(row[4]) if row[4] else {},
                    }
        return None
    
    async def get_user_conversations(
        self,
        user_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get conversations for a user.
        
        Args:
            user_id: The Telegram user ID.
            limit: Maximum number of conversations to return.
        
        Returns:
            List of conversation data dictionaries.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT * FROM conversations
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
            """, (user_id, limit)) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "conversation_id": row[0],
                        "user_id": row[1],
                        "created_at": row[2],
                        "updated_at": row[3],
                        "metadata": json.loads(row[4]) if row[4] else {},
                    }
                    for row in rows
                ]
    
    # ==================== Message Operations ====================
    
    async def save_message(self, data: dict[str, Any]) -> int:
        """
        Save a message to a conversation.
        
        Args:
            data: Message data dictionary.
        
        Returns:
            The inserted message ID.
        """
        async with self._lock:
            cursor = await self._db.execute("""
                INSERT INTO messages (conversation_id, role, content, timestamp, tool_call_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                data["conversation_id"],
                data["role"],
                data["content"],
                data.get("timestamp", datetime.utcnow().isoformat()),
                data.get("tool_call_id"),
                json.dumps(data.get("metadata", {})),
            ))
            await self._db.commit()
            return cursor.lastrowid
    
    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 100,
        before: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Get messages for a conversation.
        
        Args:
            conversation_id: The conversation identifier.
            limit: Maximum number of messages to return.
            before: Optional timestamp to get messages before.
        
        Returns:
            List of message data dictionaries.
        """
        async with aiosqlite.connect(self.db_path) as db:
            query = "SELECT * FROM messages WHERE conversation_id = ?"
            params = [conversation_id]
            
            if before:
                query += " AND timestamp < ?"
                params.append(before)
            
            query += " ORDER BY timestamp ASC LIMIT ?"
            params.append(limit)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "conversation_id": row[1],
                        "role": row[2],
                        "content": row[3],
                        "timestamp": row[4],
                        "tool_call_id": row[5],
                        "metadata": json.loads(row[6]) if row[6] else {},
                    }
                    for row in rows
                ]
    
    async def delete_messages(self, conversation_id: str) -> int:
        """
        Delete all messages for a conversation.
        
        Args:
            conversation_id: The conversation identifier.
        
        Returns:
            Number of messages deleted.
        """
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,)
            )
            await self._db.commit()
            return cursor.rowcount
    
    # ==================== Task Operations ====================
    
    async def save_task(self, data: dict[str, Any]) -> None:
        """
        Save or update a task.
        
        Args:
            data: Task data dictionary.
        """
        async with self._lock:
            await self._db.execute("""
                INSERT INTO tasks (
                    id, user_id, conversation_id, task_type, command,
                    parameters, priority, timeout, status, created_at,
                    started_at, completed_at, require_confirmation, confirmed, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    confirmed = excluded.confirmed,
                    metadata = excluded.metadata
            """, (
                data["id"],
                data["user_id"],
                data["conversation_id"],
                data["task_type"],
                data["command"],
                json.dumps(data.get("parameters", {})),
                data.get("priority", 5),
                data.get("timeout", 300),
                data.get("status", "pending"),
                data.get("created_at", datetime.utcnow().isoformat()),
                data.get("started_at"),
                data.get("completed_at"),
                1 if data.get("require_confirmation") else 0,
                1 if data.get("confirmed") else 0,
                json.dumps(data.get("metadata", {})),
            ))
            await self._db.commit()
    
    async def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """
        Get a task by ID.
        
        Args:
            task_id: The task identifier.
        
        Returns:
            Task data or None if not found.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_task(row)
        return None
    
    async def list_tasks(
        self,
        filter_params: Optional[dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        List tasks with optional filtering.
        
        Args:
            filter_params: Optional filter parameters.
            page: Page number (1-indexed).
            page_size: Number of items per page.
        
        Returns:
            Dictionary with tasks list and total count.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Build query
            query = "SELECT * FROM tasks WHERE 1=1"
            count_query = "SELECT COUNT(*) FROM tasks WHERE 1=1"
            params = []
            
            if filter_params:
                if filter_params.get("user_id"):
                    query += " AND user_id = ?"
                    count_query += " AND user_id = ?"
                    params.append(filter_params["user_id"])
                
                if filter_params.get("conversation_id"):
                    query += " AND conversation_id = ?"
                    count_query += " AND conversation_id = ?"
                    params.append(filter_params["conversation_id"])
                
                if filter_params.get("status"):
                    placeholders = ",".join("?" * len(filter_params["status"]))
                    query += f" AND status IN ({placeholders})"
                    count_query += f" AND status IN ({placeholders})"
                    params.extend(filter_params["status"])
                
                if filter_params.get("task_type"):
                    placeholders = ",".join("?" * len(filter_params["task_type"]))
                    query += f" AND task_type IN ({placeholders})"
                    count_query += f" AND task_type IN ({placeholders})"
                    params.extend(filter_params["task_type"])
            
            # Get total count
            async with db.execute(count_query, params) as cursor:
                total = (await cursor.fetchone())[0]
            
            # Get paginated results
            offset = (page - 1) * page_size
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([page_size, offset])
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                tasks = [self._row_to_task(row) for row in rows]
            
            return {"tasks": tasks, "total": total}
    
    def _row_to_task(self, row: tuple) -> dict[str, Any]:
        """Convert a database row to task dictionary."""
        return {
            "id": row[0],
            "user_id": row[1],
            "conversation_id": row[2],
            "task_type": row[3],
            "command": row[4],
            "parameters": json.loads(row[5]) if row[5] else {},
            "priority": row[6],
            "timeout": row[7],
            "status": row[8],
            "created_at": row[9],
            "started_at": row[10],
            "completed_at": row[11],
            "require_confirmation": bool(row[12]),
            "confirmed": bool(row[13]),
            "metadata": json.loads(row[14]) if row[14] else {},
        }
    
    async def save_task_result(self, data: dict[str, Any]) -> None:
        """
        Save a task result.
        
        Args:
            data: Task result data dictionary.
        """
        async with self._lock:
            await self._db.execute("""
                INSERT INTO task_results (
                    task_id, success, output, data, error, execution_time, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    success = excluded.success,
                    output = excluded.output,
                    data = excluded.data,
                    error = excluded.error,
                    execution_time = excluded.execution_time,
                    completed_at = excluded.completed_at
            """, (
                data["task_id"],
                1 if data.get("success") else 0,
                data.get("output", ""),
                json.dumps(data.get("data", {})),
                data.get("error"),
                data.get("execution_time", 0.0),
                data.get("completed_at", datetime.utcnow().isoformat()),
            ))
            await self._db.commit()
    
    async def get_task_result(self, task_id: str) -> Optional[dict[str, Any]]:
        """
        Get the result for a task.
        
        Args:
            task_id: The task identifier.
        
        Returns:
            Task result data or None if not found.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM task_results WHERE task_id = ?",
                (task_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "task_id": row[1],
                        "success": bool(row[2]),
                        "output": row[3],
                        "data": json.loads(row[4]) if row[4] else {},
                        "error": row[5],
                        "execution_time": row[6],
                        "completed_at": row[7],
                    }
        return None
    
    async def get_task_stats(self) -> dict[str, Any]:
        """
        Get task statistics.
        
        Returns:
            Dictionary with task counts and metrics.
        """
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            
            # Total tasks
            async with db.execute("SELECT COUNT(*) FROM tasks") as cursor:
                stats["total_tasks"] = (await cursor.fetchone())[0]
            
            # Tasks by status
            async with db.execute("""
                SELECT status, COUNT(*) FROM tasks GROUP BY status
            """) as cursor:
                for row in await cursor.fetchall():
                    stats[f"{row[0]}_tasks"] = row[1]
            
            # Set defaults for missing statuses
            for status in ["pending", "running", "completed", "failed", "cancelled"]:
                if f"{status}_tasks" not in stats:
                    stats[f"{status}_tasks"] = 0
            
            # Average execution time
            async with db.execute("""
                SELECT AVG(execution_time) FROM task_results WHERE success = 1
            """) as cursor:
                result = await cursor.fetchone()
                stats["avg_execution_time"] = result[0] if result[0] else 0.0
            
            return stats
    
    async def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """
        Clean up old completed tasks.
        
        Args:
            max_age_hours: Maximum age in hours for completed tasks.
        
        Returns:
            Number of tasks cleaned up.
        """
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        
        async with self._lock:
            cursor = await self._db.execute("""
                DELETE FROM tasks
                WHERE status IN ('completed', 'failed', 'cancelled', 'timeout')
                AND completed_at < ?
            """, (cutoff,))
            await self._db.commit()
            return cursor.rowcount
    
    # ==================== Skill Execution Operations ====================
    
    async def save_skill_execution(self, data: dict[str, Any]) -> int:
        """
        Save a skill execution record.
        
        Args:
            data: Skill execution data dictionary.
        
        Returns:
            The inserted record ID.
        """
        async with self._lock:
            cursor = await self._db.execute("""
                INSERT INTO skill_executions (
                    task_id, skill_name, user_id, success, output, data, error, execution_time, executed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("task_id"),
                data["skill_name"],
                data["user_id"],
                1 if data.get("success") else 0,
                data.get("output", ""),
                json.dumps(data.get("data", {})),
                data.get("error"),
                data.get("execution_time", 0.0),
                data.get("executed_at", datetime.utcnow().isoformat()),
            ))
            await self._db.commit()
            return cursor.lastrowid
    
    async def get_skill_executions(
        self,
        user_id: Optional[int] = None,
        skill_name: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get skill execution records.
        
        Args:
            user_id: Optional filter by user ID.
            skill_name: Optional filter by skill name.
            limit: Maximum number of records to return.
        
        Returns:
            List of skill execution records.
        """
        async with aiosqlite.connect(self.db_path) as db:
            query = "SELECT * FROM skill_executions WHERE 1=1"
            params = []
            
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            
            if skill_name:
                query += " AND skill_name = ?"
                params.append(skill_name)
            
            query += " ORDER BY executed_at DESC LIMIT ?"
            params.append(limit)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "task_id": row[1],
                        "skill_name": row[2],
                        "user_id": row[3],
                        "success": bool(row[4]),
                        "output": row[5],
                        "data": json.loads(row[6]) if row[6] else {},
                        "error": row[7],
                        "execution_time": row[8],
                        "executed_at": row[9],
                    }
                    for row in rows
                ]


class AgentStore:
    """
    Async SQLite storage backend for Agent tasks.
    
    Provides persistent storage for agent tasks, messages, and artifacts
    with async operations using aiosqlite.
    
    Example:
        store = AgentStore("./data/agent.db")
        await store.initialize()
        await store.save_task(task)
        await store.close()
    """
    
    def __init__(self, db_path: str) -> None:
        """
        Initialize the AgentStore.
        
        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """
        Establish database connection and create tables.
        
        Creates the database file and tables if they don't exist.
        """
        # Ensure directory exists
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._db = await aiosqlite.connect(self.db_path)
        
        # Enable foreign keys
        await self._db.execute("PRAGMA foreign_keys=ON")
        
        # Create tables
        await self._db.executescript("""
            -- Tasks table
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                state TEXT NOT NULL,
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                error TEXT
            );
            
            -- Task messages table
            CREATE TABLE IF NOT EXISTS task_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_call_id TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            
            -- Artifacts table
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                description TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            
            -- Indexes for faster lookups
            CREATE INDEX IF NOT EXISTS idx_task_messages_task_id ON task_messages(task_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_task_id ON artifacts(task_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
        """)
        
        await self._db.commit()
        
        logger.info(f"AgentStore connected to SQLite database: {self.db_path}")
    
    async def save_task(self, task: "AgentTask") -> None:
        """
        Save or update a task record.
        
        Performs an upsert operation - inserts if new, updates if exists.
        
        Args:
            task: The AgentTask object to save.
        """
        from tasks.models import TaskConfig
        
        config_json = task.config.model_dump_json() if isinstance(task.config, TaskConfig) else json.dumps(task.config)
        created_at = task.created_at.isoformat() if task.created_at else datetime.utcnow().isoformat()
        # AgentTask doesn't have completed_at, will be set when task completes
        completed_at = None
        state = task.state.value if hasattr(task.state, 'value') else str(task.state)
        
        await self._db.execute(
            """
            INSERT INTO tasks (id, goal, state, config_json, created_at, completed_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                goal = excluded.goal,
                state = excluded.state,
                config_json = excluded.config_json,
                completed_at = excluded.completed_at,
                error = excluded.error
            """,
            (
                task.task_id,
                task.config.goal,
                state,
                config_json,
                created_at,
                completed_at,
                task.error,
            ),
        )
        await self._db.commit()
        
        logger.debug(f"Saved task {task.task_id}")
    
    async def save_message(self, task_id: str, message: dict) -> None:
        """
        Save a message for a task.
        
        Args:
            task_id: The ID of the task the message belongs to.
            message: The message dictionary containing role, content, and optional tool_call_id.
        """
        timestamp = message.get("timestamp") or datetime.utcnow().isoformat()
        
        await self._db.execute(
            """
            INSERT INTO task_messages (task_id, role, content, tool_call_id, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                task_id,
                message.get("role", "unknown"),
                message.get("content", ""),
                message.get("tool_call_id"),
                timestamp,
            ),
        )
        await self._db.commit()
        
        logger.debug(f"Saved message for task {task_id}")
    
    async def get_task(self, task_id: str) -> Optional[dict]:
        """
        Retrieve a task by ID.
        
        Args:
            task_id: The ID of the task to retrieve.
        
        Returns:
            Task dictionary or None if not found.
        """
        async with self._db.execute(
            "SELECT id, goal, state, config_json, created_at, completed_at, error FROM tasks WHERE id = ?",
            (task_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            
            return {
                "id": row[0],
                "goal": row[1],
                "state": row[2],
                "config": json.loads(row[3]) if row[3] else {},
                "created_at": row[4],
                "completed_at": row[5],
                "error": row[6],
            }
    
    async def get_task_history(self, limit: int = 20) -> list[dict]:
        """
        Retrieve recent tasks.
        
        Args:
            limit: Maximum number of tasks to return.
        
        Returns:
            List of task dictionaries ordered by creation date (newest first).
        """
        async with self._db.execute(
            """
            SELECT id, goal, state, config_json, created_at, completed_at, error
            FROM tasks
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            
            return [
                {
                    "id": row[0],
                    "goal": row[1],
                    "state": row[2],
                    "config": json.loads(row[3]) if row[3] else {},
                    "created_at": row[4],
                    "completed_at": row[5],
                    "error": row[6],
                }
                for row in rows
            ]
    
    async def get_task_messages(self, task_id: str) -> list[dict]:
        """
        Retrieve all messages for a task.
        
        Args:
            task_id: The ID of the task.
        
        Returns:
            List of message dictionaries ordered by timestamp.
        """
        async with self._db.execute(
            """
            SELECT id, task_id, role, content, tool_call_id, timestamp
            FROM task_messages
            WHERE task_id = ?
            ORDER BY timestamp ASC
            """,
            (task_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            
            return [
                {
                    "id": row[0],
                    "task_id": row[1],
                    "role": row[2],
                    "content": row[3],
                    "tool_call_id": row[4],
                    "timestamp": row[5],
                }
                for row in rows
            ]
    
    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("AgentStore database connection closed")
    
    @asynccontextmanager
    async def transaction(self):
        """
        Async context manager for database transactions.
        
        Provides a transaction scope that commits on success or rolls back on error.
        
        Yields:
            The database connection for use within the transaction.
        """
        try:
            yield self._db
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise
    
    # ==================== Findings Operations ====================
    
    async def save_findings(self, findings: list[dict[str, Any]]) -> int:
        """
        Save or update findings with upsert logic.
        
        On conflict (same task_id, finding_type, value, target), updates last_seen
        and merges context.
        
        Args:
            findings: List of finding dictionaries with keys:
                - task_id: Required. The task that generated this finding.
                - conversation_id: Required. The conversation context.
                - finding_type: Required. Type: 'ip', 'domain', 'url', 'open_port', 'email', 'hash'.
                - value: Required. The actual finding value.
                - target: Optional. The host this finding relates to.
                - source_skill: Required. Which skill found it.
                - source_output: Optional. Short snippet of original output (max 200 chars).
                - context: Optional. Additional metadata dict.
                - confidence: Optional. Extraction confidence 0-1. Defaults to 1.0.
        
        Returns:
            Number of findings saved/updated.
        """
        if not findings:
            return 0
        
        now = datetime.utcnow().isoformat()
        saved_count = 0
        
        async with self._lock:
            for finding in findings:
                # Truncate source_output to 200 chars if provided
                source_output = finding.get("source_output")
                if source_output and len(source_output) > 200:
                    source_output = source_output[:200]
                
                # Use INSERT OR REPLACE for upsert
                # On conflict, this will replace the entire row
                await self._db.execute("""
                    INSERT OR REPLACE INTO findings (
                        task_id, conversation_id, finding_type, value, target,
                        source_skill, source_output, context, confidence,
                        first_seen, last_seen
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT first_seen FROM findings WHERE task_id = ? AND finding_type = ? AND value = ? AND target = ?), ?),
                        ?
                    )
                """, (
                    finding["task_id"],
                    finding["conversation_id"],
                    finding["finding_type"],
                    finding["value"],
                    finding.get("target"),
                    finding["source_skill"],
                    source_output,
                    json.dumps(finding.get("context", {})),
                    finding.get("confidence", 1.0),
                    # For COALESCE first_seen
                    finding["task_id"],
                    finding["finding_type"],
                    finding["value"],
                    finding.get("target"),
                    now,  # Default first_seen if new
                    now,  # last_seen always updated
                ))
                saved_count += 1
            
            await self._db.commit()
        
        logger.info(f"Saved {saved_count} findings")
        return saved_count
    
    async def get_findings(
        self,
        conversation_id: str,
        finding_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Get findings for a conversation, optionally filtered by type.
        
        Args:
            conversation_id: The conversation identifier.
            finding_type: Optional filter by finding type ('ip', 'domain', etc.).
            limit: Maximum number of findings to return.
        
        Returns:
            List of finding dictionaries ordered by last_seen descending.
        """
        async with aiosqlite.connect(self.db_path) as db:
            if finding_type:
                query = """
                    SELECT id, task_id, conversation_id, finding_type, value, target,
                           source_skill, source_output, context, confidence, first_seen, last_seen
                    FROM findings
                    WHERE conversation_id = ? AND finding_type = ?
                    ORDER BY last_seen DESC
                    LIMIT ?
                """
                params = [conversation_id, finding_type, limit]
            else:
                query = """
                    SELECT id, task_id, conversation_id, finding_type, value, target,
                           source_skill, source_output, context, confidence, first_seen, last_seen
                    FROM findings
                    WHERE conversation_id = ?
                    ORDER BY last_seen DESC
                    LIMIT ?
                """
                params = [conversation_id, limit]
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "task_id": row[1],
                        "conversation_id": row[2],
                        "finding_type": row[3],
                        "value": row[4],
                        "target": row[5],
                        "source_skill": row[6],
                        "source_output": row[7],
                        "context": json.loads(row[8]) if row[8] else {},
                        "confidence": row[9],
                        "first_seen": row[10],
                        "last_seen": row[11],
                    }
                    for row in rows
                ]
    
    # ==================== Artifacts Operations ====================
    
    async def save_artifact(self, artifact: dict[str, Any]) -> int:
        """
        Save an artifact generated by a skill.
        
        Args:
            artifact: Artifact dictionary with keys:
                - task_id: Required. The task that generated this artifact.
                - skill_name: Required. Which skill created it.
                - artifact_type: Required. Type (e.g., 'file', 'url', 'data').
                - path: Optional. File path if applicable.
                - content_hash: Optional. SHA256 hash of content.
                - size_bytes: Optional. Size in bytes.
                - metadata: Optional. Additional metadata dict.
        
        Returns:
            The inserted artifact ID.
        """
        now = datetime.utcnow().isoformat()
        
        async with self._lock:
            cursor = await self._db.execute("""
                INSERT INTO artifacts (
                    task_id, skill_name, artifact_type, path, content_hash,
                    size_bytes, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                artifact["task_id"],
                artifact["skill_name"],
                artifact["artifact_type"],
                artifact.get("path"),
                artifact.get("content_hash"),
                artifact.get("size_bytes"),
                now,
                json.dumps(artifact.get("metadata", {})),
            ))
            await self._db.commit()
            artifact_id = cursor.lastrowid
        
        logger.debug(f"Saved artifact {artifact_id} from {artifact['skill_name']}")
        return artifact_id
