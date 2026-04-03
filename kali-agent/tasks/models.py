"""
Task Models - Data models for task management in Kali Agent.

This module defines Pydantic models for tasks, including task status,
priorities, and result structures.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task in the system."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(int, Enum):
    """Priority levels for tasks."""
    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


class TaskType(str, Enum):
    """Types of tasks that can be executed."""
    SKILL_EXECUTION = "skill_execution"
    AGENT_QUERY = "agent_query"
    SHELL_COMMAND = "shell_command"
    SCHEDULED_TASK = "scheduled_task"
    BACKGROUND_JOB = "background_job"


class TaskBase(BaseModel):
    """Base model for task data."""
    task_type: TaskType = Field(..., description="Type of task")
    command: str = Field(..., description="Command or query to execute")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters for the task",
    )
    priority: TaskPriority = Field(
        default=TaskPriority.NORMAL,
        description="Task priority level",
    )
    timeout: Optional[int] = Field(
        default=300,
        description="Timeout in seconds",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class TaskCreate(TaskBase):
    """Model for creating a new task."""
    user_id: int = Field(..., description="Telegram user ID")
    conversation_id: str = Field(..., description="Conversation/chat ID")
    require_confirmation: bool = Field(
        default=False,
        description="Whether task requires user confirmation",
    )


class Task(TaskBase):
    """
    Full task model with all fields.
    
    Represents a task in the system with its current state and results.
    """
    id: str = Field(..., description="Unique task identifier")
    user_id: int = Field(..., description="Telegram user ID")
    conversation_id: str = Field(..., description="Conversation/chat ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Current task status",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Task creation timestamp",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Task execution start timestamp",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Task completion timestamp",
    )
    require_confirmation: bool = Field(
        default=False,
        description="Whether task requires user confirmation",
    )
    confirmed: bool = Field(
        default=False,
        description="Whether task has been confirmed by user",
    )
    
    class Config:
        """Pydantic model configuration."""
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
        }


class TaskResult(BaseModel):
    """
    Result of a task execution.
    
    Contains the output, status, and metadata from executing a task.
    """
    task_id: str = Field(..., description="ID of the associated task")
    success: bool = Field(..., description="Whether the task succeeded")
    output: str = Field(
        default="",
        description="Text output from the task",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured data from the task",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if task failed",
    )
    execution_time: float = Field(
        default=0.0,
        description="Execution time in seconds",
    )
    completed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Result creation timestamp",
    )
    
    class Config:
        """Pydantic model configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
        }


class TaskUpdate(BaseModel):
    """
    Model for updating task state.
    
    Only includes fields that can be modified after creation.
    """
    status: Optional[TaskStatus] = Field(
        default=None,
        description="New task status",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Execution start timestamp",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Completion timestamp",
    )
    confirmed: Optional[bool] = Field(
        default=None,
        description="Confirmation status",
    )
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Updated metadata",
    )


class TaskList(BaseModel):
    """
    Paginated list of tasks.
    
    Used for returning multiple tasks with pagination info.
    """
    tasks: list[Task] = Field(
        default_factory=list,
        description="List of tasks",
    )
    total: int = Field(
        default=0,
        description="Total number of tasks matching query",
    )
    page: int = Field(
        default=1,
        description="Current page number",
    )
    page_size: int = Field(
        default=20,
        description="Number of items per page",
    )
    
    @property
    def total_pages(self) -> int:
        """Calculate total number of pages."""
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


class TaskFilter(BaseModel):
    """
    Filter options for querying tasks.
    
    Used to filter tasks by various criteria.
    """
    user_id: Optional[int] = Field(
        default=None,
        description="Filter by user ID",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Filter by conversation ID",
    )
    status: Optional[list[TaskStatus]] = Field(
        default=None,
        description="Filter by status list",
    )
    task_type: Optional[list[TaskType]] = Field(
        default=None,
        description="Filter by task type list",
    )
    priority_min: Optional[TaskPriority] = Field(
        default=None,
        description="Minimum priority filter",
    )
    priority_max: Optional[TaskPriority] = Field(
        default=None,
        description="Maximum priority filter",
    )
    created_after: Optional[datetime] = Field(
        default=None,
        description="Filter tasks created after this time",
    )
    created_before: Optional[datetime] = Field(
        default=None,
        description="Filter tasks created before this time",
    )


class TaskStats(BaseModel):
    """
    Statistics about tasks in the system.
    
    Provides counts and aggregations for monitoring.
    """
    total_tasks: int = Field(default=0, description="Total number of tasks")
    pending_tasks: int = Field(default=0, description="Pending tasks")
    running_tasks: int = Field(default=0, description="Currently running tasks")
    completed_tasks: int = Field(default=0, description="Completed tasks")
    failed_tasks: int = Field(default=0, description="Failed tasks")
    cancelled_tasks: int = Field(default=0, description="Cancelled tasks")
    avg_execution_time: float = Field(default=0.0, description="Average execution time")
    
    @property
    def success_rate(self) -> float:
        """Calculate task success rate."""
        total_finished = self.completed_tasks + self.failed_tasks
        if total_finished == 0:
            return 0.0
        return self.completed_tasks / total_finished
