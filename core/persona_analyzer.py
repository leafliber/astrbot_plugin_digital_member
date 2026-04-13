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
        # 检查是否有 formatted 字段（带上下文的对话片段）
        has_formatted = any('formatted' in msg for msg in batch)

        if has_formatted:
            # 带上下文的分析格式
            sample_texts = "\n\n---\n\n".join([
                msg.get('formatted', f"【目标用户】: {msg.get('content', '')}")
                for msg in batch
            ])
            extra_note = "注意：每个片段展示了对话场景，【目标用户】是分析对象，[] 是对话背景"
        else:
            # 简单消息格式
            sample_texts = "\n".join([
                f"- {msg['content']}"
                for msg in batch
                if msg.get('content')
            ])
            extra_note = ""

        return f"""请分析以下聊天消息，提取说话者的性格和语言风格特征。

消息样本（共{len(batch)}条）：
{sample_texts}

{extra_note}

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

    async def _summarize_results(self, results: list, provider_id: str) -> dict:
        """汇总多个批次的分析结果

        Args:
            results: 各批次的分析结果列表
            provider_id: LLM 提供商 ID

        Returns:
            最终汇总的人格画像
        """
        # 构建汇总 prompt
        prompt = f"""以下是分批次分析得出的多个人格画像片段，请综合得出统一的最终画像：

批次分析结果：
{json.dumps(results, ensure_ascii=False, indent=2)}

要求：
1. 综合所有批次的 personality，取最典型、最准确的描述
2. 合并 speaking_style，保留共同特征，去除重复描述
3. catchphrases 取所有批次中出现频率最高或最有代表性的
4. interests 合并去重，保留最相关的关键词
5. emoji_usage 综合描述，如果有冲突则取主流特征

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