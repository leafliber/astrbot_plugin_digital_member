"""
对话历史管理器 - 维护每个人格独立的对话历史，实现自动压缩
"""
from datetime import datetime
from astrbot import logger


class PersonaConversationManager:
    """
    人格对话管理器 - 维护每个人格独立的对话历史
    实现自动压缩机制
    """

    def __init__(
        self,
        storage,
        context=None,
        max_turns: int = 20,
        compress_threshold: int = 15,
        summary_turns: int = 5
    ):
        self.storage = storage
        self.context = context
        self.MAX_HISTORY_TURNS = max_turns        # 最大保留对话轮数
        self.COMPRESS_THRESHOLD = compress_threshold  # 触发压缩的阈值
        self.SUMMARY_TURNS = summary_turns        # 压缩时保留的最近轮数
        self._current_provider_id = None          # 当前使用的提供商 ID

    async def get_history(self, qq: str) -> list:
        """获取人格的对话历史

        Args:
            qq: 用户 QQ 号

        Returns:
            对话历史列表
        """
        persona = await self.storage.load_persona(qq)
        if persona and 'conversation_history' in persona:
            return persona['conversation_history']
        return []

    async def add_message(self, qq: str, role: str, content: str, provider_id: str = None):
        """添加消息到对话历史

        Args:
            qq: 用户 QQ 号
            role: 角色（user/assistant/system）
            content: 消息内容
            provider_id: 当前使用的 LLM 提供商 ID（用于后续压缩摘要）
        """
        persona = await self.storage.load_persona(qq)
        if not persona:
            logger.warning(f"[人格对话] 未找到用户 {qq} 的画像")
            return

        # 保存当前的 provider_id 用于压缩摘要
        if provider_id:
            self._current_provider_id = provider_id

        if 'conversation_history' not in persona:
            persona['conversation_history'] = []

        persona['conversation_history'].append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })

        # 检查是否需要压缩
        if len(persona['conversation_history']) >= self.COMPRESS_THRESHOLD * 2:
            await self._compress_history(qq, persona)

        await self.storage.save_persona(qq, persona)

    async def _compress_history(self, qq: str, persona: dict):
        """
        自动压缩对话历史
        将旧对话压缩为摘要，保留最近的对话

        Args:
            qq: 用户 QQ 号
            persona: 人格画像字典
        """
        history = persona.get('conversation_history', [])
        if len(history) < self.COMPRESS_THRESHOLD * 2:
            return

        # 分离旧对话和最近对话
        old_messages = history[:-self.SUMMARY_TURNS * 2]
        recent_messages = history[-self.SUMMARY_TURNS * 2:]

        if not old_messages:
            return

        # 生成旧对话摘要
        summary = await self._generate_summary(old_messages)

        # 更新历史：摘要 + 最近对话
        persona['conversation_history'] = [
            {'role': 'system', 'content': f'[历史摘要] {summary}', 'timestamp': datetime.now().isoformat()}
        ] + recent_messages

        persona['last_compressed'] = datetime.now().isoformat()
        logger.info(f"[人格对话] 已压缩 {qq} 的对话历史，从 {len(history)} 条压缩到 {len(persona['conversation_history'])} 条")

    async def _generate_summary(self, messages: list) -> str:
        """使用 AI 生成对话摘要

        Args:
            messages: 需要压缩的消息列表

        Returns:
            摘要文本
        """
        # 构造对话文本
        conversation_text = "\n".join([
            f"{'用户' if m['role'] == 'user' else '回复'}: {m.get('content', '')}"
            for m in messages
            if m['role'] != 'system'
        ])

        if not conversation_text:
            return "无历史对话"

        summary_prompt = f"""请将以下对话压缩为简短的摘要（100字以内），保留关键信息和情感基调：

{conversation_text}

摘要："""

        try:
            if self.context:
                llm_resp = await self.context.llm_generate(
                    chat_provider_id=self._current_provider_id,
                    prompt=summary_prompt,
                )
                return llm_resp.completion_text.strip()
            else:
                # 无 context 时，简单截取关键信息
                return self._simple_summary(messages)
        except Exception as e:
            logger.error(f"[人格对话] 摘要生成失败: {e}")
            return self._simple_summary(messages)

    def _simple_summary(self, messages: list) -> str:
        """简单摘要生成（备用方案）

        Args:
            messages: 消息列表

        Returns:
            简单摘要
        """
        user_msgs = [m for m in messages if m['role'] == 'user']
        topic_count = len(user_msgs)
        return f"用户共发起{topic_count}次对话，涵盖日常交流话题"

    async def clear_history(self, qq: str):
        """清空对话历史

        Args:
            qq: 用户 QQ 号
        """
        persona = await self.storage.load_persona(qq)
        if persona:
            persona['conversation_history'] = []
            await self.storage.save_persona(qq, persona)
            logger.info(f"[人格对话] 已清空 {qq} 的对话历史")

    async def get_history_summary(self, qq: str) -> str:
        """获取对话历史的简要描述

        Args:
            qq: 用户 QQ 号

        Returns:
            历史简要描述
        """
        history = await self.get_history(qq)
        if not history:
            return "无对话历史"

        # 统计
        user_count = len([m for m in history if m['role'] == 'user'])
        assistant_count = len([m for m in history if m['role'] == 'assistant'])
        system_count = len([m for m in history if m['role'] == 'system'])

        return f"{user_count}轮对话，{assistant_count}条回复，{system_count}条摘要"