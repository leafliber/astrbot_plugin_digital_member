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
            logger.debug(f"[人格分析] 开始分析 {len(messages)} 条消息，提供商: {provider_id}")

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )

            response_text = llm_resp.completion_text
            logger.debug(f"[人格分析] LLM响应长度: {len(response_text)}")
            logger.debug(f"[人格分析] LLM响应预览: {response_text[:200]}...")
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
- personality: 性格特征描述（2-4个字的概括，如「开朗活泼」「内向稳重」「幽默风趣」「直率坦诚」等）
- speaking_style: 说话风格（详细描述，如「说话幽默爱开玩笑」「语气轻松随意」「比较严肃认真」「喜欢用表情包」等）
- catchphrases: 口头禅列表（找出3-5个最常用的词语、表情或句式，必须是真正反复出现的）
- interests: 兴趣爱好关键词（从消息内容推断，3-5个关键词）
- emoji_usage: 表情符号使用习惯描述（如「经常使用可爱表情」「喜欢用emoji表达情绪」「表情使用较少」等）

注意事项：
1. personality 只需2-4个字，简洁概括
2. catchphrases 必须是真实出现过的词语或表情，不要猜测
3. 如果找不到明显口头禅，catchphrases 留空数组
4. speaking_style 要具体，描述说话方式的特点

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
        logger.debug(f"[人格分析] 画像详情: 性格={persona.get('personality')}, 风格={persona.get('speaking_style')}")
        logger.debug(f"[人格分析] 口头禅={persona.get('catchphrases')}, 兴趣={persona.get('interests')}")

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