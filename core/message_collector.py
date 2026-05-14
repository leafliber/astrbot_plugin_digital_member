"""
消息收集器 - 使用 message_recorder 插件 API 获取历史消息
支持智能采样：去重、质量评分、时间分层采样
"""
import re
import hashlib
from typing import Optional
from astrbot import logger
from astrbot.api.star import Context


class MessageCollector:
    """消息收集器 - 使用 astrbot_plugin_message_recorder API"""

    DEFAULT_SAMPLE_MAX = 1000
    DEFAULT_QUALITY_MIN_LENGTH = 2

    def __init__(
        self,
        query_max_count: int = 0,
        fetch_context: bool = False,
        context_before: int = 3,
        context_after: int = 3,
        sample_max: int = 0,
        smart_sampling: bool = False,
    ):
        self.query_max_count = query_max_count
        self.fetch_context = fetch_context
        self.context_before = context_before
        self.context_after = context_after
        self.sample_max = sample_max if sample_max > 0 else self.DEFAULT_SAMPLE_MAX
        self.smart_sampling = smart_sampling
        self._recorder_api = None

    async def get_recorder_api(self, context: Context) -> Optional[object]:
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
        TIME_RANGE_MAP = {
            "7d": 7, "7天": 7,
            "30d": 30, "30天": 30,
            "90d": 90, "90天": 90,
            "all": None, "全部": None, "所有": None,
        }
        if not time_str:
            return 30
        time_str = time_str.strip().lower()
        return TIME_RANGE_MAP.get(time_str, 30)

    async def collect_messages_with_context(
        self,
        context: Context,
        sender_id: str,
        group_id: str,
        time_range: int | None = 30,
        smart_sampling: bool | None = None,
    ) -> list:
        """收集消息，根据配置决定是否进行智能采样"""
        use_sampling = smart_sampling if smart_sampling is not None else self.smart_sampling
        api = await self.get_recorder_api(context)
        if not api:
            logger.error("[消息收集] 未找到 message_recorder 插件，无法获取历史消息")
            logger.info("[消息收集] 请确保已安装 astrbot_plugin_message_recorder 插件")
            return []

        time_param = self._convert_time_range(time_range)
        time_desc = "全部历史" if time_range is None else f"最近{time_range}天"

        logger.info(f"[消息收集] 开始查询: 用户={sender_id}, 群={group_id}, 时间={time_desc}")

        try:
            if self.query_max_count > 0:
                records = await self._query_with_limit(
                    api, sender_id, group_id, time_param, self.query_max_count
                )
            else:
                records = await self._query_all_messages(
                    api, sender_id, group_id, time_param
                )

            logger.info(f"[消息收集] API 返回 {len(records)} 条记录")

            if not records:
                return []

            if not self.fetch_context:
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
                if use_sampling:
                    messages = self.smart_sample(messages)
                else:
                    logger.info(f"[消息收集] 智能采样已关闭，保留全部 {len(messages)} 条原始消息")
                return messages

            all_segments = []
            processed_ids = set()

            logger.info(f"[消息收集] 开始获取上下文: 前{self.context_before}条, 后{self.context_after}条")

            for record in records:
                if record.message_id in processed_ids:
                    continue

                content = record.message_str
                if not content or not content.strip():
                    continue

                try:
                    ctx = await api.get_context(
                        record.message_id,
                        self.context_before,
                        self.context_after
                    )
                except Exception as e:
                    logger.warning(f"[消息收集] 获取上下文失败: {e}")
                    ctx = {'before': [], 'after': []}

                segment = self._merge_context_to_segment(
                    ctx, record, sender_id, processed_ids
                )
                all_segments.append(segment)

            logger.info(f"[消息收集] 生成 {len(all_segments)} 个对话片段")

            if len(all_segments) < 50:
                logger.warning(f"[消息收集] 消息数量较少({len(all_segments)}个片段)")
                logger.warning("[消息收集] 可能原因: 1. 用户发言较少; 2. message_recorder 记录时间较短")

            if use_sampling:
                all_segments = self.smart_sample(all_segments)
            else:
                logger.info(f"[消息收集] 智能采样已关闭，保留全部 {len(all_segments)} 个原始对话片段")
            return all_segments

        except Exception as e:
            logger.error(f"[消息收集] 查询失败: {e}")
            logger.debug(f"[消息收集] 错误类型: {type(e).__name__}")
            return []

    def smart_sample(self, messages: list) -> list:
        """智能采样：去重 → 质量过滤 → 时间分层采样

        将大量消息压缩为高质量样本，保留信息密度最高的消息，
        同时确保时间分布均匀以捕捉风格变化。

        Args:
            messages: 原始消息列表

        Returns:
            采样后的消息列表
        """
        original_count = len(messages)
        if original_count <= self.sample_max:
            logger.info(f"[智能采样] 消息数 {original_count} ≤ 上限 {self.sample_max}，无需采样")
            return messages

        logger.info(f"[智能采样] 开始处理 {original_count} 条消息，目标上限 {self.sample_max}")

        deduplicated = self._deduplicate(messages)
        dedup_count = len(deduplicated)
        logger.info(f"[智能采样] 去重后: {dedup_count} 条 (去除 {original_count - dedup_count} 条重复)")

        filtered = self._filter_low_quality(deduplicated)
        filter_count = len(filtered)
        logger.info(f"[智能采样] 质量过滤后: {filter_count} 条 (去除 {dedup_count - filter_count} 条低质量)")

        if filter_count <= self.sample_max:
            logger.info(f"[智能采样] 过滤后 {filter_count} 条 ≤ 上限 {self.sample_max}，无需进一步采样")
            return filtered

        sampled = self._stratified_sample(filtered, self.sample_max)
        logger.info(f"[智能采样] 分层采样后: {len(sampled)} 条 (从 {filter_count} 条中采样)")
        logger.info(f"[智能采样] 总计: {original_count} → {len(sampled)} 条 (压缩率 {(1 - len(sampled)/original_count)*100:.1f}%)")

        return sampled

    def _deduplicate(self, messages: list) -> list:
        """去除完全相同和高度相似的消息

        策略：
        1. 完全相同内容只保留一条（保留最早的）
        2. 短消息（≤5字）相同内容最多保留3条（保留时间分布最广的3条）

        Args:
            messages: 消息列表

        Returns:
            去重后的消息列表
        """
        content_groups = {}
        for msg in messages:
            content = self._get_content(msg)
            normalized = content.strip().lower()
            if not normalized:
                continue

            key = normalized
            if key not in content_groups:
                content_groups[key] = []
            content_groups[key].append(msg)

        result = []
        for key, group in content_groups.items():
            if len(group) == 1:
                result.append(group[0])
            elif len(key) <= 5:
                group_sorted = sorted(group, key=lambda m: self._get_time(m))
                step = max(1, len(group_sorted) // 3)
                for i in range(0, len(group_sorted), step):
                    if len([m for m in result if self._get_content(m).strip().lower() == key]) < 3:
                        result.append(group_sorted[i])
            else:
                result.append(group[0])

        result.sort(key=lambda m: self._get_time(m))
        return result

    def _filter_low_quality(self, messages: list) -> list:
        """过滤低信息量消息

        过滤规则：
        1. 纯表情/emoji（无文字）
        2. 极短无意义回复（单字如"嗯""哦""哈"等）
        3. 纯数字/纯标点

        Args:
            messages: 消息列表

        Returns:
            过滤后的消息列表
        """
        low_info_patterns = re.compile(
            r'^[嗯哦哈啊噢唔额呃诶唉哎哇耶哟嗷噗喂嘿嗨溜6]{1,3}$'
            r'|^[\.。,，!！?？~～\s]+$'
            r'|^\d+$'
            r'|^[👍👎👌🙏😂🤣😊😎🤔😅😁😉😋😆🤗😏🙄😴😇🤩🥳😢😭😤😡🤯😱🥺😈👻💀💩🤮🤧🥴😵🤪🤫🤭🥰😘😗😙😚🤤😴😷🤒🤕🤑🤠😈👿👹👺🤡💩👻💀☠️👽👾🤖🎃😺😸😹😻😼😽🙀😿😾]{1,5}$'
        )

        result = []
        low_count = 0
        for msg in messages:
            content = self._get_content(msg).strip()
            if len(content) < self.DEFAULT_QUALITY_MIN_LENGTH:
                low_count += 1
                continue
            if low_info_patterns.match(content):
                low_count += 1
                continue
            result.append(msg)

        if low_count > 0:
            logger.debug(f"[智能采样] 过滤低质量消息 {low_count} 条")

        return result

    def _stratified_sample(self, messages: list, max_count: int) -> list:
        """时间分层采样：将消息按时间分成N个区间，每个区间按质量评分采样

        确保采样结果在时间维度上均匀分布，同时优先保留高质量消息。

        Args:
            messages: 已去重和过滤的消息列表（需按时间排序）
            max_count: 最大采样数量

        Returns:
            采样后的消息列表
        """
        if len(messages) <= max_count:
            return messages

        sorted_msgs = sorted(messages, key=lambda m: self._get_time(m))

        num_bins = min(10, max(1, max_count // 30))
        bin_size = len(sorted_msgs) // num_bins
        per_bin = max_count // num_bins
        remainder = max_count % num_bins

        scored = [(msg, self._score_quality(msg)) for msg in sorted_msgs]

        result = []
        for i in range(num_bins):
            start = i * bin_size
            end = start + bin_size if i < num_bins - 1 else len(sorted_msgs)
            bin_msgs = scored[start:end]

            bin_quota = per_bin + (1 if i < remainder else 0)

            bin_msgs.sort(key=lambda x: x[1], reverse=True)
            selected = [msg for msg, score in bin_msgs[:bin_quota]]
            result.extend(selected)

        result.sort(key=lambda m: self._get_time(m))
        return result

    def _score_quality(self, msg: dict) -> float:
        """评估消息的信息质量分数

        评分维度：
        1. 长度分：适中长度(10-100字)得分最高，过短或过长递减
        2. 多样性分：包含标点/emoji/特殊字符的多样性
        3. 内容丰富度：包含对话性内容（问号、感叹号、代词等）

        Args:
            msg: 消息字典

        Returns:
            质量分数 (0.0 ~ 1.0)
        """
        content = self._get_content(msg).strip()
        if not content:
            return 0.0

        length = len(content)

        if length <= 3:
            length_score = 0.1
        elif length <= 8:
            length_score = 0.3
        elif length <= 20:
            length_score = 0.6
        elif length <= 50:
            length_score = 0.9
        elif length <= 100:
            length_score = 1.0
        elif length <= 200:
            length_score = 0.8
        else:
            length_score = 0.5

        diversity_score = 0.0
        unique_chars = len(set(content))
        diversity_ratio = unique_chars / max(length, 1)
        if diversity_ratio > 0.7:
            diversity_score = 0.3
        elif diversity_ratio > 0.5:
            diversity_score = 0.2
        else:
            diversity_score = 0.1

        richness_score = 0.0
        if any(c in content for c in '？！?！'):
            richness_score += 0.1
        if any(c in content for c in '。，,.\n'):
            richness_score += 0.1
        if any(p in content for p in ['你', '我', '他', '她', '什么', '怎么', '为什么', '觉得', '认为', '知道']):
            richness_score += 0.2

        total = min(length_score * 0.5 + diversity_score + richness_score, 1.0)
        return total

    def _get_content(self, msg) -> str:
        if isinstance(msg, dict):
            return msg.get('formatted', msg.get('content', ''))
        return str(msg)

    def _get_time(self, msg) -> int:
        if isinstance(msg, dict):
            return msg.get('time', 0)
        return 0

    def estimate_tokens(self, messages: list) -> int:
        """估算消息列表的 token 数量

        使用简单的字符/token比率估算：
        - 中文约 1.5 字符/token
        - 英文约 4 字符/token
        - 混合内容取折中约 2 字符/token

        Args:
            messages: 消息列表

        Returns:
            估算的 token 数量
        """
        total_chars = 0
        for msg in messages:
            content = self._get_content(msg)
            total_chars += len(content)

        return int(total_chars / 2)

    def _merge_context_to_segment(
        self,
        ctx: dict,
        center_record,
        target_sender: str,
        processed_ids: set
    ) -> dict:
        before_msgs = ctx.get('before', [])
        after_msgs = ctx.get('after', [])

        sequence = []

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

        processed_ids.add(center_record.message_id)
        sequence.append({
            'time': center_record.timestamp // 1000 if center_record.timestamp else 0,
            'content': center_record.message_str or "",
            'is_target': True,
            'sender_name': center_record.sender_name or target_sender
        })

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

        formatted_text = self._format_segment_for_analysis(sequence)

        return {
            'time': center_record.timestamp // 1000 if center_record.timestamp else 0,
            'sequence': sequence,
            'formatted': formatted_text
        }

    def _format_segment_for_analysis(self, sequence: list) -> str:
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
        if days is None:
            return "all"
        return f"last{days}d"

    async def _query_with_limit(
        self,
        api,
        sender_id: str,
        group_id: str,
        time_param: str,
        limit: int
    ) -> list:
        sender_id_str = str(sender_id) if sender_id else None
        group_id_str = str(group_id) if group_id else None

        return await api.query(
            sender_id=sender_id_str,
            group_id=group_id_str,
            time=time_param,
            limit=limit,
            order="asc"
        )

    async def _query_all_messages(
        self,
        api,
        sender_id: str,
        group_id: str,
        time_param: str,
        page_size: int = 500
    ) -> list:
        sender_id_str = str(sender_id) if sender_id else None
        group_id_str = str(group_id) if group_id else None

        all_records = []
        offset = 0
        max_records = 50000

        while True:
            records = await api.query(
                sender_id=sender_id_str,
                group_id=group_id_str,
                time=time_param,
                limit=page_size,
                offset=offset,
                order="asc"
            )

            if not records:
                break

            all_records.extend(records)

            if len(records) < page_size:
                break

            offset += page_size

            if len(all_records) >= max_records:
                logger.warning(f"[消息收集] 已达到安全上限 {max_records} 条，停止查询")
                break

        return all_records

    async def collect_messages(
        self,
        context: Context,
        sender_id: str,
        group_id: str,
        time_range: int | None = 30,
        smart_sampling: bool | None = None,
    ) -> list:
        return await self.collect_messages_with_context(
            context=context,
            sender_id=sender_id,
            group_id=group_id,
            time_range=time_range,
            smart_sampling=smart_sampling,
        )
