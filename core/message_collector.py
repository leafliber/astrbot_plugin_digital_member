"""
消息收集器 - 使用 message_recorder 插件 API 获取历史消息
"""
from typing import Optional
from astrbot import logger
from astrbot.api.star import Context


class MessageCollector:
    """消息收集器 - 使用 astrbot_plugin_message_recorder API"""

    def __init__(self, max_analyze_count: int = 500):
        self.MAX_ANALYZE_COUNT = max_analyze_count
        self._recorder_api = None

    async def get_recorder_api(self, context: Context) -> Optional[object]:
        """获取 message_recorder 插件的 API 实例

        Args:
            context: AstrBot 插件上下文

        Returns:
            MessageRecorderAPI 实例，如果未找到则返回 None
        """
        if self._recorder_api is None:
            recorder = context.get_registered_star("astrbot_plugin_message_recorder")
            if recorder and hasattr(recorder, 'get_api'):
                self._recorder_api = recorder.get_api()
                if self._recorder_api:
                    logger.info("[消息收集] 已获取 message_recorder API")
                else:
                    logger.warning("[消息收集] message_recorder 插件未正确初始化")
            else:
                logger.warning("[消息收集] 未找到 message_recorder 插件")
        return self._recorder_api

    def parse_time_range(self, time_str: str) -> int | None:
        """解析时间范围参数

        Args:
            time_str: 时间范围字符串，如 "7天"、"30天"、"all"

        Returns:
            天数（int）或 None（表示全部）
        """
        TIME_RANGE_MAP = {
            "7d": 7, "7天": 7,
            "30d": 30, "30天": 30,
            "90d": 90, "90天": 90,
            "all": None, "全部": None, "所有": None,
        }
        if not time_str:
            return 30  # 默认30天
        time_str = time_str.strip().lower()
        return TIME_RANGE_MAP.get(time_str, 30)

    async def collect_messages(
        self,
        context: Context,
        sender_id: str,
        group_id: str,
        time_range: int | None = 30
    ) -> list:
        """收集用户历史消息

        Args:
            context: AstrBot 插件上下文
            sender_id: 目标用户 ID
            group_id: 群组 ID
            time_range: 时间范围（天数），None 表示全部

        Returns:
            消息列表，每条包含 time 和 content
        """
        api = await self.get_recorder_api(context)
        if not api:
            logger.error("[消息收集] 未找到 message_recorder 插件，无法获取历史消息")
            logger.info("[消息收集] 请确保已安装 astrbot_plugin_message_recorder 插件")
            return []

        # 时间参数转换
        time_param = self._convert_time_range(time_range)
        time_desc = "全部历史" if time_range is None else f"最近{time_range}天"

        logger.info(f"[消息收集] 开始查询: 用户={sender_id}, 群={group_id}, 时间={time_desc}")

        try:
            # 调用 message_recorder API
            records = await api.query(
                sender_id=sender_id,
                group_id=group_id,
                time=time_param,
                limit=self.MAX_ANALYZE_COUNT,
                order="asc"  # 按时间正序
            )

            logger.info(f"[消息收集] API 返回 {len(records)} 条记录")

            # 转换为分析器需要的格式
            messages = []
            for record in records:
                # message_str 是消息文本内容
                content = record.message_str
                if content and content.strip():
                    # timestamp 是毫秒，转换为秒
                    timestamp = record.timestamp // 1000 if record.timestamp else 0
                    messages.append({
                        'time': timestamp,
                        'content': content.strip()
                    })

            logger.info(f"[消息收集] 有效消息: {len(messages)} 条")

            # 如果消息太少，输出提示
            if len(messages) < 50:
                logger.warning(f"[消息收集] 消息数量较少({len(messages)}条)")
                logger.warning("[消息收集] 可能原因: 1. 用户发言较少; 2. message_recorder 记录时间较短")

            return messages

        except Exception as e:
            logger.error(f"[消息收集] 查询失败: {e}")
            logger.debug(f"[消息收集] 错误类型: {type(e).__name__}")
            return []

    def _convert_time_range(self, days: int | None) -> str:
        """将天数转换为 message_recorder 时间格式

        Args:
            days: 天数，None 表示全部

        Returns:
            message_recorder 支持的时间格式字符串
        """
        if days is None:
            return "all"  # 全部历史
        return f"last{days}d"  # 如 "last30d", "last7d"