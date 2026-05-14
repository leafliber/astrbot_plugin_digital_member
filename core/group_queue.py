import asyncio
from astrbot import logger


class GroupQueueManager:
    """Per-group queue manager with separate analysis and send queues

    - Analysis queue: ensures only one LLM analysis runs per group at a time
    - Send queue: ensures only one message send runs per group at a time
    - Configurable intervals between tasks for rate limiting
    """

    def __init__(self, analyze_interval: float = 1.0, send_interval: float = 2.0):
        self._analyze_queues: dict[str, asyncio.Queue] = {}
        self._analyze_workers: dict[str, asyncio.Task] = {}
        self._send_queues: dict[str, asyncio.Queue] = {}
        self._send_workers: dict[str, asyncio.Task] = {}
        self._analyze_interval = analyze_interval
        self._send_interval = send_interval

    def _ensure_analyze_worker(self, group_id: str):
        if group_id not in self._analyze_queues:
            self._analyze_queues[group_id] = asyncio.Queue()
            self._analyze_workers[group_id] = asyncio.create_task(
                self._analyze_worker(group_id)
            )

    def _ensure_send_worker(self, group_id: str):
        if group_id not in self._send_queues:
            self._send_queues[group_id] = asyncio.Queue()
            self._send_workers[group_id] = asyncio.create_task(
                self._send_worker(group_id)
            )

    async def submit_analysis(self, group_id: str, analyze_factory):
        self._ensure_analyze_worker(group_id)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._analyze_queues[group_id].put((analyze_factory, future))
        queue_size = self._analyze_queues[group_id].qsize()
        if queue_size > 1:
            logger.info(f"[队列] 群 {group_id} 分析任务排队中，前方还有 {queue_size - 1} 个任务")
        return await future

    async def _analyze_worker(self, group_id: str):
        queue = self._analyze_queues[group_id]
        while True:
            try:
                analyze_factory, future = await queue.get()
                try:
                    result = await analyze_factory()
                    if not future.done():
                        future.set_result(result)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
                    logger.error(f"[队列] 群 {group_id} 分析任务执行失败: {e}")
                finally:
                    queue.task_done()
                await asyncio.sleep(self._analyze_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[队列] 群 {group_id} 分析工作器异常: {e}")

    async def submit_send(self, group_id: str, send_factory):
        self._ensure_send_worker(group_id)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._send_queues[group_id].put((send_factory, future))
        queue_size = self._send_queues[group_id].qsize()
        if queue_size > 1:
            logger.debug(f"[队列] 群 {group_id} 发送任务排队中，前方还有 {queue_size - 1} 个任务")
        return await future

    async def _send_worker(self, group_id: str):
        queue = self._send_queues[group_id]
        while True:
            try:
                send_factory, future = await queue.get()
                try:
                    result = await send_factory()
                    if not future.done():
                        future.set_result(result)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
                    logger.error(f"[队列] 群 {group_id} 发送任务执行失败: {e}")
                finally:
                    queue.task_done()
                await asyncio.sleep(self._send_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[队列] 群 {group_id} 发送工作器异常: {e}")

    def get_analyze_queue_size(self, group_id: str) -> int:
        queue = self._analyze_queues.get(group_id)
        return queue.qsize() if queue else 0

    def get_send_queue_size(self, group_id: str) -> int:
        queue = self._send_queues.get(group_id)
        return queue.qsize() if queue else 0

    async def shutdown(self):
        for group_id, task in self._analyze_workers.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for group_id, task in self._send_workers.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._analyze_workers.clear()
        self._send_workers.clear()
        self._analyze_queues.clear()
        self._send_queues.clear()
        logger.info("[队列] 所有工作器已停止")
