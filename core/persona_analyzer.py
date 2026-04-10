"""
画像分析器 - 调用 AI 分析消息生成人格画像
"""
import json
import re
from astrbot import logger
from astrbot.api.star import Context


class PersonaAnalyzer:
    """画像分析器 - 调用 LLM 分析消息生成人格画像"""

    def __init__(self, context: Context):
        self.context = context

    async def analyze(self, messages: list, provider_id: str = None) -> dict:
        """分析消息生成画像

        Args:
            messages: 消息列表，每条包含 time 和 content
            provider_id: LLM 提供商 ID，为 None 时使用默认提供商

        Returns:
            人格画像字典
        """
        if not messages:
            logger.warning("[人格分析] 无有效消息")
            return self._get_default_persona()

        prompt = self._build_analysis_prompt(messages)

        try:
            # 调用 LLM 分析
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )

            response_text = llm_resp.completion_text
            logger.info(f"[人格分析] LLM响应长度: {len(response_text)}")

            return self._parse_response(response_text, len(messages))

        except Exception as e:
            logger.error(f"[人格分析] LLM调用失败: {e}")
            return self._get_default_persona()

    def _build_analysis_prompt(self, messages: list) -> str:
        """构造分析 prompt

        Args:
            messages: 消息列表

        Returns:
            分析用的 prompt 字符串
        """
        # 按时间排序，取代表性消息
        sorted_messages = sorted(messages, key=lambda x: x.get('time', 0))
        sample_count = min(100, len(sorted_messages))

        # 构建样本文本
        sample_texts = "\n".join([
            f"- {msg['content']}"
            for msg in sorted_messages[-sample_count:]
        ])

        return f"""请分析以下聊天消息，提取说话者的性格和语言风格特征。

消息样本（共{sample_count}条）：
{sample_texts}

请输出 JSON 格式的画像，包含以下字段：
- personality: 性格特征描述（简短概括，如"开朗活泼"、"内向稳重"）
- speaking_style: 说话风格（如幽默、严肃、可爱、直率等）
- catchphrases: 口头禅列表（找出常用的词语或表情）
- interests: 兴趣爱好关键词（从消息内容推断）
- emoji_usage: 表情符号使用习惯描述

请只输出 JSON，不要有其他内容。"""

    def _parse_response(self, response_text: str, message_count: int) -> dict:
        """解析 LLM 响应

        Args:
            response_text: LLM 返回的文本
            message_count: 分析的消息数量

        Returns:
            人格画像字典
        """
        # 尝试提取 JSON
        try:
            # 尝试直接解析
            persona = json.loads(response_text)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    persona = json.loads(json_match.group())
                except json.JSONDecodeError:
                    persona = self._get_default_persona()
            else:
                persona = self._get_default_persona()

        # 验证必要字段
        required_fields = ['personality', 'speaking_style', 'catchphrases', 'interests', 'emoji_usage']
        for field in required_fields:
            if field not in persona:
                persona[field] = self._get_default_persona().get(field)

        # 确保 catchphrases 和 interests 是列表
        if not isinstance(persona.get('catchphrases'), list):
            persona['catchphrases'] = []
        if not isinstance(persona.get('interests'), list):
            persona['interests'] = []

        # 添加元数据
        persona['message_count'] = message_count
        persona['created_at'] = None  # 由 storage 填充

        logger.info(f"[人格分析] 画像生成完成: {persona.get('personality', '未知')}")

        return persona

    def _get_default_persona(self) -> dict:
        """获取默认画像

        Returns:
            默认的人格画像字典
        """
        return {
            'personality': '普通',
            'speaking_style': '正常',
            'catchphrases': [],
            'interests': [],
            'emoji_usage': '无明显习惯',
            'message_count': 0,
            'created_at': None,
        }