"""
消息收集器 - 使用 message_recorder 插件 API 获取历史消息
"""
from typing import Optional
from astrbot import logger
from astrbot.api.star import Context


class MessageCollector:
    """消息收集器 - 使用 astrbot_plugin_message_recorder API"""

    def __init__(
        self,
        query_max_count: int = 0,
        fetch_context: bool = False,
        context_before: int = 3,
        context_after: int = 3,
    ):
        self.query_max_count = query_max_count
        self.fetch_context = fetch_context
        self.context_before = context_before
        self.context_after = context_after
        self._recorder_api = None

    async def get_recorder_api(self, context: Context) -> Optional[object]:
        """获取 message_recorder 插件的 API 实例

        Args:
            context: AstrBot 插件上下文

        Returns:
            MessageRecorderAPI 实例，如果未找到则返回 None
        """
        if self._recorder_api is None:
            try:
                star_meta = context.get_registered_star("astrbot_plugin_message_recorder")
                logger.debug(f"[消息收集] get_registered_star 返回: {star_meta}, 类型: {type(star_meta)}")
                
                if star_meta is None:
                    logger.warning("[消息收集] 未找到 message_recorder 插件")
                    return None
                
                plugin_instance = getattr(star_meta, "star_cls", None)
                logger.debug(f"[消息收集] star_cls: {plugin_instance}, 类型: {type(plugin_instance)}")
                
                if plugin_instance is None:
                    logger.warning("[消息收集] message_recorder 插件实例为 None，可能未激活")
                    return None
                
                if hasattr(plugin_instance, "get_api"):
                    self._recorder_api = plugin_instance.get_api()
                    if self._recorder_api:
                        logger.info("[消息收集] 已获取 message_recorder API")
                    else:
                        logger.warning("[消息收集] message_recorder 插件未正确初始化")
                else:
                    logger.warning("[消息收集] 插件实例没有 get_api 方法")
                    
            except Exception as e:
                logger.warning(f"[消息收集] 获取 message_recorder API 失败: {e}")
                import traceback
                logger.debug(f"[消息收集] 错误堆栈:\n{traceback.format_exc()}")
                
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

    async def collect_messages_with_context(
        self,
        context: Context,
        sender_id: str,
        group_id: str,
        time_range: int | None = 30
    ) -> list:
        """收集消息并获取上下文，合并目标用户连续消息

        Args:
            context: AstrBot 插件上下文
            sender_id: 目标用户 ID
            group_id: 群组 ID
            time_range: 时间范围（天数），None 表示全部

        Returns:
            消息列表，如果 fetch_context=True 则包含合并后的对话片段
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
            # 查询上限：0 表示不限制
            limit_param = self.query_max_count if self.query_max_count > 0 else None

            # 转换 ID 为整数类型（message_recorder 数据库要求）
            try:
                sender_id_int = int(sender_id) if sender_id else None
                group_id_int = int(group_id) if group_id else None
            except (ValueError, TypeError) as e:
                logger.error(f"[消息收集] ID 转换失败: sender_id={sender_id}, group_id={group_id}, 错误={e}")
                return []

            # 调用 message_recorder API
            records = await api.query(
                sender_id=sender_id_int,
                group_id=group_id_int,
                time=time_param,
                limit=limit_param,
                order="asc"  # 按时间正序
            )

            logger.info(f"[消息收集] API 返回 {len(records)} 条记录")

            if not records:
                return []

            if not self.fetch_context:
                # 不需要上下文，直接返回格式化后的消息
                messages = []
                for record in records:
                    content = record.message_str
                    if content and content.strip():
                        timestamp = record.timestamp // 1000 if record.timestamp else 0
                        messages.append({
                            'time': timestamp,
                            'content': content.strip()
                        })
                logger.info(f"[消息收集] 有效消息: {len(messages)} 条")
                return messages

            # 获取每条消息的上下文，合并成连续对话片段
            all_segments = []
            processed_ids = set()

            logger.info(f"[消息收集] 开始获取上下文: 前{self.context_before}条, 后{self.context_after}条")

            for record in records:
                if record.message_id in processed_ids:
                    continue

                content = record.message_str
                if not content or not content.strip():
                    continue

                # 获取上下文
                try:
                    ctx = await api.get_context(
                        record.message_id,
                        self.context_before,
                        self.context_after
                    )
                except Exception as e:
                    logger.warning(f"[消息收集] 获取上下文失败: {e}")
                    ctx = {'before': [], 'after': []}

                # 合并前后消息中属于目标用户的连续片段
                segment = self._merge_context_to_segment(
                    ctx, record, sender_id, processed_ids
                )
                all_segments.append(segment)

            logger.info(f"[消息收集] 生成 {len(all_segments)} 个对话片段")

            # 如果消息太少，输出提示
            if len(all_segments) < 50:
                logger.warning(f"[消息收集] 消息数量较少({len(all_segments)}个片段)")
                logger.warning("[消息收集] 可能原因: 1. 用户发言较少; 2. message_recorder 记录时间较短")

            return all_segments

        except Exception as e:
            logger.error(f"[消息收集] 查询失败: {e}")
            logger.debug(f"[消息收集] 错误类型: {type(e).__name__}")
            return []

    def _merge_context_to_segment(
        self,
        ctx: dict,
        center_record,
        target_sender: str,
        processed_ids: set
    ) -> dict:
        """将上下文合并为连续对话片段

        Args:
            ctx: get_context 返回的上下文 {'before': [...], 'after': [...]}
            center_record: 中心消息记录
            target_sender: 目标用户 ID
            processed_ids: 已处理的消息 ID 集合

        Returns:
            包含 sequence 和 formatted 字段的对话片段
        """
        before_msgs = ctx.get('before', [])
        after_msgs = ctx.get('after', [])

        # 找出连续的目标用户消息序列
        sequence = []

        # 处理前面的消息（逆序找连续的目标用户消息）
        for m in reversed(before_msgs):
            sender_id = str(m.sender_id) if m.sender_id else ""
            is_target = sender_id == target_sender

            if is_target:
                processed_ids.add(m.message_id)

            sequence.insert(0, {
                'time': m.timestamp // 1000 if m.timestamp else 0,
                'content': m.message_str or "",
                'is_target': is_target,
                'sender_name': m.sender_name or "其他人"
            })

        # 中间消息（目标用户）
        processed_ids.add(center_record.message_id)
        sequence.append({
            'time': center_record.timestamp // 1000 if center_record.timestamp else 0,
            'content': center_record.message_str or "",
            'is_target': True,
            'sender_name': center_record.sender_name or target_sender
        })

        # 处理后面的消息
        for m in after_msgs:
            sender_id = str(m.sender_id) if m.sender_id else ""
            is_target = sender_id == target_sender

            if is_target:
                processed_ids.add(m.message_id)

            sequence.append({
                'time': m.timestamp // 1000 if m.timestamp else 0,
                'content': m.message_str or "",
                'is_target': is_target,
                'sender_name': m.sender_name or "其他人"
            })

        # 格式化为分析用的文本
        formatted_text = self._format_segment_for_analysis(sequence)

        return {
            'time': center_record.timestamp // 1000 if center_record.timestamp else 0,
            'sequence': sequence,
            'formatted': formatted_text
        }

    def _format_segment_for_analysis(self, sequence: list) -> str:
        """格式化对话片段为分析文本

        Args:
            sequence: 消息序列列表

        Returns:
            格式化后的文本
        """
        lines = []
        for item in sequence:
            content = item['content'].strip()
            if not content:
                continue

            if item['is_target']:
                lines.append(f"【目标用户】: {content}")
            else:
                sender = item.get('sender_name', '其他人')
                lines.append(f"[{sender}]: {content}")
        return "\n".join(lines)

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

    # 保留旧方法以兼容（如果有其他地方调用）
    async def collect_messages(
        self,
        context: Context,
        sender_id: str,
        group_id: str,
        time_range: int | None = 30
    ) -> list:
        """收集用户历史消息（旧方法，不带上下文）

        已弃用，请使用 collect_messages_with_context
        """
        return await self.collect_messages_with_context(
            context=context,
            sender_id=sender_id,
            group_id=group_id,
            time_range=time_range
        )