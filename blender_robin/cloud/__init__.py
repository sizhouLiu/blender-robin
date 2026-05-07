"""
Cloud integration module for distributed rendering.
Supports object storage, task queues, notifications, and K8s orchestration.

All modules are optional — import only what you need:
    from blender_robin.cloud.storage import ObjectStore
    from blender_robin.cloud.queue import TaskQueue
    from blender_robin.cloud.notify import Notifier

Or use the worker directly:
    python -m blender_robin.cloud.worker
"""

__version__ = "0.1.0"

# Lazy imports — only load when accessed
__all__ = [
    "ObjectStore",
    "StorageError",
    "TaskQueue",
    "QueueError",
    "Notifier",
    "NotifyError",
]


def __getattr__(name):
    if name == "ObjectStore" or name == "StorageError":
        from blender_robin.cloud.storage import ObjectStore, StorageError
        return ObjectStore if name == "ObjectStore" else StorageError
    if name == "TaskQueue" or name == "QueueError":
        from blender_robin.cloud.queue import TaskQueue, QueueError
        return TaskQueue if name == "TaskQueue" else QueueError
    if name == "Notifier" or name == "NotifyError":
        from blender_robin.cloud.notify import Notifier, NotifyError
        return Notifier if name == "Notifier" else NotifyError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
