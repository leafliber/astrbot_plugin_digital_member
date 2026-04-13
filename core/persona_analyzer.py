"""
画像分析器 - 调用 AI 分析消息生成人格画像
"""
import json
import re
import asyncio
from astrbot import logger
from astrbot.api.star import Context


class PersonaAnalyzer:
    """画像分析器 - 调用 LLM 分析消息生成人格画像"""

    def __init__(self, context: Context):
        self.context = context

    async def analyze(
        self,
        messages: list,
        provider_id: str = None,
        batch_size: int = 100,
        mode: str = "batch_summarize",
        batch_delay_ms: int = 1000
    ) -> dict:
        """分析消息生成画像（支持分批次）

        Args:
            messages: 消息列表，每条包含 time、content 或 formatted
            provider_id: LLM 提供商 ID，为 None 时使用默认提供商
            batch_size: 每批次分析的消息数
            mode: 分析模式 ("single" 或 "batch_summarize")
            batch_delay_ms: 批次间延迟（毫秒）

        Returns:
            人格画像字典
        """
        if not messages:
            logger.warning("[人格分析] 无有效消息")
            return self._get_default_persona()

        logger.info(f"[人格分析] 开始分析 {len(messages)} 条消息，模式: {mode}")

        if mode == "single":
            # 取样本一次性分析（原有逻辑）
            sample = messages[-min(batch_size, len(messages)):]
            logger.info(f"[人格分析] 取样本 {len(sample)} 条进行一次性分析")
            return await self._analyze_batch(sample, provider_id)
        else:
            # 分批次分析后汇总
            return await self._analyze_batch_summarize(
                messages, batch_size, provider_id, batch_delay_ms
            )

    async def _analyze_batch_summarize(
        self,
        messages: list,
        batch_size: int,
        provider_id: str,
        batch_delay_ms: int
    ) -> dict:
        """分批次分析后汇总

        Args:
            messages: 消息列表
            batch_size: 每批次消息数
            provider_id: LLM 提供商 ID
            batch_delay_ms: 批次间延迟（毫秒）

        Returns:
            最终的人格画像
        """
        batches = [
            messages[i:i + batch_size]
            for i in range(0, len(messages), batch_size)
        ]
        logger.info(f"[人格分析] 分 {len(batches)} 批次分析")

        batch_results = []
        for i, batch in enumerate(batches):
            logger.debug(f"[人格分析] 分析第 {i + 1} 批次，{len(batch)} 条消息")
            result = await self._analyze_batch(batch, provider_id)
            batch_results.append(result)

            # 批次间延迟（避免 API 限速）
            if i < len(batches) - 1 and batch_delay_ms > 0:
                await asyncio.sleep(batch_delay_ms / 1000)

        # 汇总所有批次结果
        logger.info(f"[人格分析] 开始汇总 {len(batch_results)} 个批次结果")
        final_persona = await self._summarize_results(batch_results, provider_id)

        # 记录总消息数和批次数
        total_msg_count = sum(r.get('message_count', 0) for r in batch_results)
        final_persona['message_count'] = total_msg_count
        final_persona['batch_count'] = len(batch_results)

        return final_persona

    async def _analyze_batch(self, batch: list, provider_id: str) -> dict:
        """分析单个批次

        Args:
            batch: 消息批次
            provider_id: LLM 提供商 ID

        Returns:
            该批次的人格画像分析结果
        """
        prompt = self._build_batch_prompt(batch)

        try:
            logger.debug(f"[人格分析] 批次 Prompt 长度: {len(prompt)}")

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )

            response_text = llm_resp.completion_text
            logger.debug(f"[人格分析] 批次 LLM响应长度: {len(response_text)}")
            logger.debug(f"[人格分析] 批次 LLM响应预览: {response_text[:200]}...")

            return self._parse_response(response_text, len(batch))

        except Exception as e:
            logger.error(f"[人格分析] 批次 LLM调用失败: {e}")
            return self._get_default_persona()

    def _build_batch_prompt(self, batch: list) -> str:
        """构建批次分析 prompt

        Args:
            batch: 消息批次

        Returns:
            分析用的 prompt 字符串
        """
        has_formatted = any('formatted' in msg for msg in batch)

        if has_formatted:
            sample_texts = "\n\n---\n\n".join([
                msg.get('formatted', f"【目标用户】: {msg.get('content', '')}")
                for msg in batch
            ])
            extra_note = "注意：每个片段展示了对话场景，【目标用户】是分析对象，[] 是对话背景"
        else:
            sample_texts = "\n".join([
                f"- {msg['content']}"
                for msg in batch
                if msg.get('content')
            ])
            extra_note = ""

        return f"""你是一位专业的语言风格分析师。请仔细分析以下聊天消息样本，深入提取说话者的性格特征和语言习惯。

消息样本（共{len(batch)}条）：
{sample_texts}

{extra_note}

请输出 JSON 格式的画像，包含以下字段：

【基础特征】
- personality: 性格特征概括（2-4个字，如「开朗活泼」「内向稳重」「幽默风趣」「直率坦诚」「温柔细腻」等）
- speaking_style: 说话风格详细描述（具体描述说话方式，如「说话幽默爱开玩笑，语气轻松随意」等）
- tone: 说话语气（如「亲切温和」「冷淡疏离」「热情洋溢」「调侃戏谑」等）

【语言习惯】
- catchphrases: 口头禅列表（3-5个真正反复出现的词语、表情或句式，没有则留空数组）
- sentence_pattern: 常用句式（如「喜欢用反问句」「经常用感叹号」「句子偏短」等）
- emoji_usage: 表情符号使用习惯（如「经常使用可爱表情」「喜欢用emoji表达情绪」等）
- punctuation: 标点符号习惯（如「喜欢用波浪号~」「句末常加省略号」「感叹号多」等）

【兴趣态度】
- interests: 兴趣爱好关键词（3-5个，从消息内容推断）
- values: 价值观倾向（如「重视友情」「追求自由」「注重效率」等，可选）
- emotional_pattern: 情绪表达特点（如「情绪外露」「内敛含蓄」「容易激动」等）

【典型对话】
- typical_responses: 典型回复示例（3-5条最能代表其说话风格的真实消息原文，保持原样）

分析要点：
1. personality 要简洁准确，抓住最核心的性格特点
2. catchphrases 必须是真实出现过的，不要猜测或编造
3. typical_responses 要选择最能体现其风格的原消息
4. 各字段描述要具体，避免空泛的形容词
5. 如果某些特征不明显，对应字段可以留空或写"无明显特征"

请只输出 JSON，不要有其他内容。"""

    async def _summarize_results(self, results: list, provider_id: str) -> dict:
        """汇总多个批次的分析结果

        Args:
            results: 各批次的分析结果列表
            provider_id: LLM 提供商 ID

        Returns:
            最终汇总的人格画像
        """
        prompt = f"""你是一位专业的语言风格分析师。以下是分批次分析得出的多个人格画像片段，请综合得出统一的最终画像。

批次分析结果：
{json.dumps(results, ensure_ascii=False, indent=2)}

汇总要求：
1. personality：综合所有批次，取最典型、最准确的核心性格描述（2-4字）
2. speaking_style：合并描述，保留共同特征，去除重复，形成完整风格画像
3. tone：取最主流的语气特征
4. catchphrases：取所有批次中出现频率最高或有代表性的口头禅（去重）
5. sentence_pattern：综合各批次的句式特点
6. emoji_usage：综合描述表情使用习惯
7. punctuation：综合标点使用特点
8. interests：合并去重，保留最相关的关键词
9. values：如有明显价值观倾向则保留
10. emotional_pattern：综合情绪表达特点
11. typical_responses：从各批次的典型回复中选出最具代表性的3-5条

请只输出 JSON 格式的最终画像，字段与输入相同。"""

        try:
            logger.debug(f"[人格分析] 汇总 Prompt 长度: {len(prompt)}")

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )

            response_text = llm_resp.completion_text
            logger.info(f"[人格分析] 汇总响应长度: {len(response_text)}")
            logger.debug(f"[人格分析] 汇总响应预览: {response_text[:200]}...")

            return self._parse_response(response_text, 0)

        except Exception as e:
            logger.error(f"[人格分析] 汇总 LLM调用失败: {e}")
            # 如果汇总失败，返回第一个批次的结果作为 fallback
            if results:
                logger.warning("[人格分析] 使用第一个批次结果作为 fallback")
                return results[0]
            return self._get_default_persona()

    def _parse_response(self, response_text: str, message_count: int) -> dict:
        """解析 LLM 响应

        Args:
            response_text: LLM 返回的文本
            message_count: 分析的消息数量

        Returns:
            人格画像字典
        """
        try:
            persona = json.loads(response_text)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    persona = json.loads(json_match.group())
                except json.JSONDecodeError:
                    persona = self._get_default_persona()
            else:
                persona = self._get_default_persona()

        required_fields = [
            'personality', 'speaking_style', 'catchphrases', 'interests', 'emoji_usage',
            'tone', 'sentence_pattern', 'punctuation', 'values', 'emotional_pattern', 'typical_responses'
        ]
        for field in required_fields:
            if field not in persona:
                persona[field] = self._get_default_persona().get(field)

        if not isinstance(persona.get('catchphrases'), list):
            persona['catchphrases'] = []
        if not isinstance(persona.get('interests'), list):
            persona['interests'] = []
        if not isinstance(persona.get('typical_responses'), list):
            persona['typical_responses'] = []

        persona['message_count'] = message_count
        persona['created_at'] = None

        logger.info(f"[人格分析] 画像生成完成: {persona.get('personality', '未知')}")
        logger.debug(f"[人格分析] 画像详情: 性格={persona.get('personality')}, 风格={persona.get('speaking_style')}")
        logger.debug(f"[人格分析] 口头禅={persona.get('catchphrases')}, 兴趣={persona.get('interests')}")
        logger.debug(f"[人格分析] 典型回复数={len(persona.get('typical_responses', []))}")

        return persona

    def _get_default_persona(self) -> dict:
        """获取默认画像

        Returns:
            默认的人格画像字典
        """
        return {
            'personality': '普通',
            'speaking_style': '正常',
            'tone': '平和',
            'catchphrases': [],
            'sentence_pattern': '无明显特点',
            'interests': [],
            'emoji_usage': '无明显习惯',
            'punctuation': '正常使用',
            'values': '',
            'emotional_pattern': '稳定',
            'typical_responses': [],
            'message_count': 0,
            'created_at': None,
        }