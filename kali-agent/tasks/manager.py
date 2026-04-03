"""
Task Manager - Background task management for Kali Agent.

This module provides the TaskManager class for managing async tasks,
including creation, execution, cancellation, and status tracking.
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Optional

from .models import (
    Task,
    TaskCreate,
    TaskFilter,
    TaskList,
    TaskResult,
    TaskStats,
    TaskStatus,
    TaskType,
    TaskUpdate,
)

logger = logging.getLogger(__name__)


class TaskError(Exception):
    """Base exception for task-related errors."""
    pass


class TaskNotFoundError(TaskError):
    """Raised when a task is not found."""
    pass


class TaskTimeoutError(TaskError):
    """Raised when a task times out."""
    pass


class TaskCancelledError(TaskError):
    """Raised when a task is cancelled."""
    pass


class TaskManager:
    """
    Async task manager for Kali Agent.
    
    Manages the lifecycle of background tasks including creation,
    execution, monitoring, and cleanup.
    
    Example:
        async with TaskManager(store) as manager:
            task = await manager.create_task(task_create)
            result = await manager.wait_for_task(task.id)
    """
    
    def __init__(
        self,
        store: Any,  # SQLiteStore type hint avoided to prevent circular import
        max_concurrent_tasks: int = 10,
        default_timeout: int = 300,
    ) -> None:
        """
        Initialize the task manager.
        
        Args:
            store: The SQLite store for task persistence.
            max_concurrent_tasks: Maximum number of concurrent tasks.
            default_timeout: Default timeout for tasks in seconds.
        """
        self.store = store
        self.max_concurrent_tasks = max_concurrent_tasks
        self.default_timeout = default_timeout
        
        self._tasks: dict[str, Task] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._handlers: dict[TaskType, Callable] = {}
        self._lock = asyncio.Lock()
    
    def register_handler(
        self,
        task_type: TaskType,
        handler: Callable[[Task], AsyncGenerator[TaskResult, None]],
    ) -> None:
        """
        Register a handler for a task type.
        
        Args:
            task_type: The type of task to handle.
            handler: Async function that processes the task.
        """
        self._handlers[task_type] = handler
        logger.info(f"Registered handler for task type: {task_type}")
    
    async def create_task(
        self,
        task_create: TaskCreate,
    ) -> Task:
        """
        Create a new task.
        
        Args:
            task_create: The task creation model with task details.
        
        Returns:
            The created Task object.
        """
        task_id = str(uuid.uuid4())
        
        task = Task(
            id=task_id,
            user_id=task_create.user_id,
            conversation_id=task_create.conversation_id,
            task_type=task_create.task_type,
            command=task_create.command,
            parameters=task_create.parameters,
            priority=task_create.priority,
            timeout=task_create.timeout or self.default_timeout,
            metadata=task_create.metadata,
            require_confirmation=task_create.require_confirmation,
            status=TaskStatus.PENDING,
        )
        
        # Store task
        async with self._lock:
            self._tasks[task_id] = task
        
        # Persist to database
        await self.store.save_task(task.model_dump())
        
        logger.info(f"Created task {task_id}: {task_create.task_type}")
        return task
    
    async def get_task(self, task_id: str) -> Task:
        """
        Get a task by ID.
        
        Args:
            task_id: The task identifier.
        
        Returns:
            The Task object.
        
        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return task
        
        # Try to load from store
        task_data = await self.store.get_task(task_id)
        if task_data:
            task = Task(**task_data)
            async with self._lock:
                self._tasks[task_id] = task
            return task
        
        raise TaskNotFoundError(f"Task {task_id} not found")
    
    async def update_task(
        self,
        task_id: str,
        update: TaskUpdate,
    ) -> Task:
        """
        Update a task's state.
        
        Args:
            task_id: The task identifier.
            update: The update model with fields to change.
        
        Returns:
            The updated Task object.
        
        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        task = await self.get_task(task_id)
        
        update_data = update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                setattr(task, key, value)
        
        async with self._lock:
            self._tasks[task_id] = task
        
        await self.store.save_task(task.model_dump())
        logger.debug(f"Updated task {task_id}: {update_data}")
        
        return task
    
    async def start_task(self, task_id: str) -> None:
        """
        Start executing a task.
        
        Args:
            task_id: The task identifier.
        
        Raises:
            TaskNotFoundError: If task doesn't exist.
            TaskError: If task requires confirmation but isn't confirmed.
        """
        task = await self.get_task(task_id)
        
        if task.require_confirmation and not task.confirmed:
            raise TaskError(f"Task {task_id} requires confirmation")
        
        if task.status == TaskStatus.RUNNING:
            logger.warning(f"Task {task_id} is already running")
            return
        
        # Get handler for task type
        handler = self._handlers.get(TaskType(task.task_type))
        if not handler:
            raise TaskError(f"No handler registered for task type: {task.task_type}")
        
        # Update status
        await self.update_task(task_id, TaskUpdate(
            status=TaskStatus.RUNNING,
            started_at=datetime.utcnow(),
        ))
        
        # Create async task
        async_task = asyncio.create_task(
            self._execute_task(task, handler)
        )
        
        async with self._lock:
            self._running_tasks[task_id] = async_task
        
        logger.info(f"Started task {task_id}")
    
    async def _execute_task(
        self,
        task: Task,
        handler: Callable,
    ) -> TaskResult:
        """
        Execute a task with the registered handler.
        
        Args:
            task: The task to execute.
            handler: The handler function.
        
        Returns:
            The task result.
        """
        result = TaskResult(
            task_id=task.id,
            success=False,
            output="",
        )
        
        start_time = datetime.utcnow()
        
        try:
            async with self._semaphore:
                async with asyncio.timeout(task.timeout):
                    result = await handler(task)
                    result.success = True
        
        except asyncio.TimeoutError:
            result.error = f"Task timed out after {task.timeout} seconds"
            await self.update_task(task.id, TaskUpdate(status=TaskStatus.TIMEOUT))
            logger.warning(f"Task {task.id} timed out")
        
        except asyncio.CancelledError:
            result.error = "Task was cancelled"
            await self.update_task(task.id, TaskUpdate(status=TaskStatus.CANCELLED))
            logger.info(f"Task {task.id} cancelled")
        
        except Exception as e:
            result.error = str(e)
            await self.update_task(task.id, TaskUpdate(status=TaskStatus.FAILED))
            logger.exception(f"Task {task.id} failed: {e}")
        
        else:
            await self.update_task(task.id, TaskUpdate(
                status=TaskStatus.COMPLETED,
                completed_at=datetime.utcnow(),
            ))
            logger.info(f"Task {task.id} completed successfully")
        
        finally:
            result.execution_time = (datetime.utcnow() - start_time).total_seconds()
            result.completed_at = datetime.utcnow()
            
            # Save result
            await self.store.save_task_result(result.model_dump())
            
            # Cleanup
            async with self._lock:
                self._running_tasks.pop(task.id, None)
        
        return result
    
    async def cancel_task(self, task_id: str) -> None:
        """
        Cancel a running task.
        
        Args:
            task_id: The task identifier.
        
        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        task = await self.get_task(task_id)
        
        if task.status != TaskStatus.RUNNING:
            logger.warning(f"Task {task_id} is not running, cannot cancel")
            return
        
        async with self._lock:
            async_task = self._running_tasks.get(task_id)
        
        if async_task:
            async_task.cancel()
            try:
                await async_task
            except asyncio.CancelledError:
                pass
        
        await self.update_task(task_id, TaskUpdate(status=TaskStatus.CANCELLED))
        logger.info(f"Cancelled task {task_id}")
    
    async def confirm_task(self, task_id: str) -> None:
        """
        Confirm a task that requires confirmation.
        
        Args:
            task_id: The task identifier.
        
        Raises:
            TaskNotFoundError: If task doesn't exist.
        """
        await self.update_task(task_id, TaskUpdate(confirmed=True))
        logger.info(f"Confirmed task {task_id}")
    
    async def wait_for_task(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> TaskResult:
        """
        Wait for a task to complete and return its result.
        
        Args:
            task_id: The task identifier.
            timeout: Optional timeout for waiting.
        
        Returns:
            The task result.
        
        Raises:
            TaskNotFoundError: If task doesn't exist.
            asyncio.TimeoutError: If wait times out.
        """
        async with self._lock:
            async_task = self._running_tasks.get(task_id)
        
        if async_task:
            try:
                async with asyncio.timeout(timeout):
                    return await async_task
            except asyncio.TimeoutError:
                raise
        
        # Task already completed, get result from store
        result_data = await self.store.get_task_result(task_id)
        if result_data:
            return TaskResult(**result_data)
        
        raise TaskNotFoundError(f"No result found for task {task_id}")
    
    async def list_tasks(
        self,
        filter_params: Optional[TaskFilter] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TaskList:
        """
        List tasks with optional filtering and pagination.
        
        Args:
            filter_params: Optional filter parameters.
            page: Page number (1-indexed).
            page_size: Number of items per page.
        
        Returns:
            TaskList with tasks and pagination info.
        """
        tasks_data = await self.store.list_tasks(
            filter_params=filter_params.model_dump() if filter_params else None,
            page=page,
            page_size=page_size,
        )
        
        tasks = [Task(**t) for t in tasks_data["tasks"]]
        
        return TaskList(
            tasks=tasks,
            total=tasks_data["total"],
            page=page,
            page_size=page_size,
        )
    
    async def get_stats(self) -> TaskStats:
        """
        Get task statistics.
        
        Returns:
            TaskStats with counts and metrics.
        """
        stats_data = await self.store.get_task_stats()
        return TaskStats(**stats_data)
    
    async def cleanup_completed(self, max_age_hours: int = 24) -> int:
        """
        Clean up completed tasks older than the specified age.
        
        Args:
            max_age_hours: Maximum age in hours for completed tasks.
        
        Returns:
            Number of tasks cleaned up.
        """
        count = await self.store.cleanup_old_tasks(max_age_hours=max_age_hours)
        
        # Also clean up in-memory cache
        async with self._lock:
            to_remove = [
                task_id for task_id, task in self._tasks.items()
                if task.status in (
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                    TaskStatus.TIMEOUT,
                )
            ]
            for task_id in to_remove:
                del self._tasks[task_id]
        
        logger.info(f"Cleaned up {count} old tasks")
        return count
    
    @asynccontextmanager
    async def lifespan(self):
        """
        Async context manager for task manager lifecycle.
        
        Yields:
            The task manager instance.
        """
        try:
            yield self
        finally:
            # Cancel all running tasks
            async with self._lock:
                for task_id, async_task in list(self._running_tasks.items()):
                    async_task.cancel()
                    try:
                        await async_task
                    except asyncio.CancelledError:
                        pass
                self._running_tasks.clear()
            
            logger.info("Task manager shutdown complete")
