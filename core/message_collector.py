"""
消息收集器 - 全自动分批获取群历史消息
"""
from datetime import datetime, timedelta
import asyncio
from astrbot import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

# 时间范围解析映射
TIME_RANGE_MAP = {
    "7d": 7, "7天": 7,
    "30d": 30, "30天": 30,
    "90d": 90, "90天": 90,
    "all": None, "全部": None, "所有": None,
}


class MessageCollector:
    """消息收集器 - 自动分批获取群历史消息"""

    def __init__(
        self,
        batch_size: int = 100,
        batch_delay_ms: int = 100,
        max_analyze_count: int = 500,
    ):
        self.BATCH_SIZE = batch_size
        self.BATCH_DELAY = batch_delay_ms / 1000.0  # 转换为秒
        self.MAX_ANALYZE_COUNT = max_analyze_count
        self.MAX_RAW_MESSAGES = 10000  # 单次获取的最大原始消息数

    def parse_time_range(self, time_str: str) -> int | None:
        """解析时间范围参数

        Args:
            time_str: 时间范围字符串，如 "7天"、"30天"、"all"

        Returns:
            天数（int）或 None（表示全部）
        """
        if not time_str:
            return 30  # 默认30天
        time_str = time_str.strip().lower()
        return TIME_RANGE_MAP.get(time_str, 30)

    async def collect_messages(
        self,
        event: AstrMessageEvent,
        user_id: str,
        time_range: int | None = 30
    ) -> list:
        """
        全自动分批获取群历史消息并筛选指定用户

        Args:
            event: AstrBot 消息事件
            user_id: 目标用户 QQ 号
            time_range: 时间范围（天数），None 表示全部

        Returns:
            筛选后的用户消息列表
        """
        # 检查平台类型
        if event.get_platform_name() != "aiocqhttp":
            logger.warning("[人格克隆] 仅支持 aiocqhttp 平台")
            return []

        if not isinstance(event, AiocqhttpMessageEvent):
            logger.warning("[人格克隆] 事件类型不匹配")
            return []

        client = event.bot
        group_id = event.message_obj.group_id

        if not group_id:
            logger.warning("[人格克隆] 非群聊消息")
            return []

        # 计算时间截止点
        cutoff_timestamp = None
        if time_range is not None:
            cutoff_timestamp = int((datetime.now() - timedelta(days=time_range)).timestamp())

        time_desc = "全部历史" if time_range is None else f"最近{time_range}天"
        logger.info(f"[人格克隆] 开始收集: 群={group_id}, 用户={user_id}, 时间范围={time_desc}")

        all_messages = []
        user_messages = []
        message_seq = 0

        # 自动循环获取
        while len(all_messages) < self.MAX_RAW_MESSAGES:
            try:
                result = await client.api.call_action(
                    'get_group_msg_history',
                    group_id=int(group_id),
                    message_seq=message_seq,
                    count=self.BATCH_SIZE
                )
                messages = result.get("data", {}).get("messages", [])

                if not messages:
                    logger.info("[人格克隆] 无更多消息，停止收集")
                    break

                # 处理消息
                for msg in messages:
                    msg_time = msg.get('time', 0)
                    msg_user = str(msg.get('sender', {}).get('user_id', ''))

                    # 时间检查
                    if cutoff_timestamp and msg_time < cutoff_timestamp:
                        logger.info(f"[人格克隆] 时间范围达标，停止收集")
                        return self._finalize_messages(user_messages)

                    all_messages.append(msg)

                    # 筛选目标用户
                    if msg_user == user_id:
                        raw_msg = msg.get('raw_message', '')
                        if raw_msg and raw_msg.strip():
                            user_messages.append({
                                'time': msg_time,
                                'content': raw_msg.strip(),
                            })

                # 获取下一批起点
                next_seq = messages[-1].get('message_seq', 0)
                if next_seq == message_seq or next_seq == 0:
                    logger.info("[人格克隆] 已到达最早消息")
                    break
                message_seq = next_seq

                # 批次延迟，避免API限速
                await asyncio.sleep(self.BATCH_DELAY)

            except Exception as e:
                logger.error(f"[人格克隆] API错误: {e}")
                break

        logger.info(f"[人格克隆] 收集完成: 原始={len(all_messages)}, 用户={len(user_messages)}")
        return self._finalize_messages(user_messages)

    def _finalize_messages(self, messages: list) -> list:
        """最终处理：限制数量，保留最新

        Args:
            messages: 消息列表

        Returns:
            处理后的消息列表（最多 MAX_ANALYZE_COUNT 条）
        """
        if len(messages) > self.MAX_ANALYZE_COUNT:
            logger.info(f"[人格克隆] 消息数量超限，保留最近 {self.MAX_ANALYZE_COUNT} 条")
            return messages[-self.MAX_ANALYZE_COUNT:]
        return messages