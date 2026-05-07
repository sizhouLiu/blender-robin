"""
Generic task queue client for distributed rendering.
Supports Redis (via redis-py), RabbitMQ (via pika), and Celery.

All backends implement the same interface:
    push(task)   → enqueue a render task dict
    pop(timeout) → blocking dequeue, returns dict or None on timeout
    ack(task_id) → mark task done (Redis streams / AMQP ack)

Configure via environment variables:
    ROBIN_QUEUE_BACKEND   redis | rabbitmq | celery  (default: redis)
    ROBIN_QUEUE_URL       connection URL
    ROBIN_QUEUE_NAME      queue / stream name        (default: robin-renders)
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional


class QueueError(Exception):
    pass


# ── Base interface ─────────────────────────────────────────────────────────────

class TaskQueue:
    """Abstract base — do not instantiate directly."""

    def push(self, task: dict) -> str:
        """Enqueue a task. Returns a task_id string."""
        raise NotImplementedError

    def pop(self, timeout: int = 30) -> Optional[dict]:
        """Blocking dequeue. Returns task dict or None on timeout."""
        raise NotImplementedError

    def ack(self, task_id: str) -> None:
        """Acknowledge task completion (if backend requires it)."""

    @classmethod
    def from_env(cls) -> "TaskQueue":
        backend = os.environ.get("ROBIN_QUEUE_BACKEND", "redis").lower()
        url = os.environ.get("ROBIN_QUEUE_URL", "redis://localhost:6379/0")
        name = os.environ.get("ROBIN_QUEUE_NAME", "robin-renders")
        if backend == "redis":
            return RedisQueue(url=url, name=name)
        if backend == "rabbitmq":
            return RabbitMQQueue(url=url, name=name)
        if backend == "celery":
            return CeleryQueue(url=url, name=name)
        raise QueueError(f"Unknown queue backend: {backend!r}")


# ── Redis backend ──────────────────────────────────────────────────────────────

class RedisQueue(TaskQueue):
    """
    Redis-backed queue using a List (LPUSH / BRPOP).
    Simple and fast; no per-message ack — use RedisStreamQueue for that.

    pip install redis
    """

    def __init__(self, url: str = "redis://localhost:6379/0", name: str = "robin-renders"):
        self._url = url
        self._name = name
        self._client = None

    def _conn(self):
        if self._client is None:
            try:
                import redis
            except ImportError:
                raise QueueError("redis is required: pip install redis")
            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    def push(self, task: dict) -> str:
        task = dict(task)
        if "task_id" not in task:
            task["task_id"] = str(uuid.uuid4())
        self._conn().lpush(self._name, json.dumps(task))
        return task["task_id"]

    def pop(self, timeout: int = 30) -> Optional[dict]:
        result = self._conn().brpop(self._name, timeout=timeout)
        if result is None:
            return None
        _, raw = result
        return json.loads(raw)

    def qsize(self) -> int:
        return self._conn().llen(self._name)


class RedisStreamQueue(TaskQueue):
    """
    Redis Streams backend — supports explicit ACK and consumer groups.
    Use this when you need at-least-once delivery guarantees.

    pip install redis
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        name: str = "robin-renders",
        group: str = "workers",
        consumer: str = "worker-1",
    ):
        self._url = url
        self._name = name
        self._group = group
        self._consumer = consumer
        self._client = None

    def _conn(self):
        if self._client is None:
            try:
                import redis
            except ImportError:
                raise QueueError("redis is required: pip install redis")
            self._client = redis.from_url(self._url, decode_responses=True)
            # Ensure group exists
            try:
                self._client.xgroup_create(self._name, self._group, id="0", mkstream=True)
            except Exception:
                pass  # group already exists
        return self._client

    def push(self, task: dict) -> str:
        task = dict(task)
        if "task_id" not in task:
            task["task_id"] = str(uuid.uuid4())
        payload = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                   for k, v in task.items()}
        self._conn().xadd(self._name, payload)
        return task["task_id"]

    def pop(self, timeout: int = 30) -> Optional[dict]:
        r = self._conn()
        entries = r.xreadgroup(
            groupname=self._group,
            consumername=self._consumer,
            streams={self._name: ">"},
            count=1,
            block=timeout * 1000,
        )
        if not entries:
            return None
        stream_name, messages = entries[0]
        msg_id, fields = messages[0]
        task = {}
        for k, v in fields.items():
            try:
                task[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                task[k] = v
        task["_stream_id"] = msg_id
        return task

    def ack(self, task_id: str) -> None:
        # task_id here is the Redis stream message ID stored in _stream_id
        self._conn().xack(self._name, self._group, task_id)


# ── RabbitMQ backend ───────────────────────────────────────────────────────────

class RabbitMQQueue(TaskQueue):
    """
    RabbitMQ backend via pika.
    Uses a durable queue with manual acknowledgement.

    pip install pika
    """

    def __init__(
        self,
        url: str = "amqp://guest:guest@localhost:5672/",
        name: str = "robin-renders",
    ):
        self._url = url
        self._name = name

    def _connect(self):
        try:
            import pika
        except ImportError:
            raise QueueError("pika is required: pip install pika")
        params = pika.URLParameters(self._url)
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        ch.queue_declare(queue=self._name, durable=True)
        return conn, ch

    def push(self, task: dict) -> str:
        try:
            import pika
        except ImportError:
            raise QueueError("pika is required: pip install pika")
        task = dict(task)
        if "task_id" not in task:
            task["task_id"] = str(uuid.uuid4())
        conn, ch = self._connect()
        ch.basic_publish(
            exchange="",
            routing_key=self._name,
            body=json.dumps(task).encode(),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
        )
        conn.close()
        return task["task_id"]

    def pop(self, timeout: int = 30) -> Optional[dict]:
        conn, ch = self._connect()
        deadline = time.time() + timeout
        while time.time() < deadline:
            method_frame, _, body = ch.basic_get(queue=self._name, auto_ack=False)
            if method_frame:
                task = json.loads(body.decode())
                task["_delivery_tag"] = method_frame.delivery_tag
                task["_channel"] = ch
                task["_connection"] = conn
                return task
            time.sleep(0.5)
        conn.close()
        return None

    def ack(self, task_id: str) -> None:
        # For RabbitMQ, the task dict itself carries _channel and _delivery_tag.
        # task_id here is unused; callers should call ack on the returned task dict.
        pass

    def ack_task(self, task: dict) -> None:
        """Acknowledge using fields injected into the task by pop()."""
        ch = task.get("_channel")
        tag = task.get("_delivery_tag")
        conn = task.get("_connection")
        if ch and tag:
            ch.basic_ack(delivery_tag=tag)
        if conn:
            conn.close()


# ── Celery backend ─────────────────────────────────────────────────────────────

class CeleryQueue(TaskQueue):
    """
    Celery backend — submits tasks to a Celery app.
    Requires a running Celery worker that imports `robin_worker` task.

    pip install celery[redis]   or   celery[rabbitmq]
    """

    TASK_NAME = "robin_worker.render_task"

    def __init__(self, url: str = "redis://localhost:6379/0", name: str = "robin-renders"):
        self._url = url
        self._name = name
        self._app = None

    def _get_app(self):
        if self._app is None:
            try:
                from celery import Celery
            except ImportError:
                raise QueueError("celery is required: pip install celery")
            self._app = Celery(broker=self._url, backend=self._url)
        return self._app

    def push(self, task: dict) -> str:
        task = dict(task)
        if "task_id" not in task:
            task["task_id"] = str(uuid.uuid4())
        app = self._get_app()
        app.send_task(self.TASK_NAME, args=[task], queue=self._name)
        return task["task_id"]

    def pop(self, timeout: int = 30) -> Optional[dict]:
        raise QueueError(
            "CeleryQueue does not support pop() — workers consume tasks directly. "
            "Use @app.task decorator in your worker instead."
        )
