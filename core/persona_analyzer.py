"""
画像分析器 - 调用 AI 分析消息生成人格画像
支持 Token 感知分批 + 早停收敛检测
"""
import json
import asyncio
from astrbot import logger
from astrbot.api.star import Context


class PersonaAnalyzer:
    """画像分析器 - 调用 LLM 分析消息生成人格画像"""

    TOKEN_BUDGET_PER_BATCH = 3000
    PROMPT_OVERHEAD_TOKENS = 800
    CHARS_PER_TOKEN = 2
    CONVERGENCE_THRESHOLD = 0.7
    MIN_BATCHES_BEFORE_CONVERGENCE = 2

    def __init__(self, context: Context):
        self.context = context

    async def analyze(
        self,
        messages: list,
        provider_id: str = None,
        batch_size: int = 100,
        mode: str = "batch_summarize",
        batch_delay_ms: int = 1000,
        token_budget: int = 0,
        enable_early_stop: bool = True,
    ) -> dict:
        """分析消息生成画像

        Args:
            messages: 消息列表（已采样后的高质量样本）
            provider_id: LLM 提供商 ID
            batch_size: 每批次消息数（仅 mode=single 时使用）
            mode: 分析模式 ("single" 或 "batch_summarize")
            batch_delay_ms: 批次间延迟（毫秒）
            token_budget: 每批次 token 预算（0=使用默认值 3000）
            enable_early_stop: 是否启用早停收敛检测
        """
        if not messages:
            logger.warning("[人格分析] 无有效消息")
            return self._get_default_persona()

        logger.info(f"[人格分析] 开始分析 {len(messages)} 条消息，模式: {mode}")

        if mode == "single":
            sample = messages[-min(batch_size, len(messages)):]
            logger.info(f"[人格分析] 取样本 {len(sample)} 条进行一次性分析")
            result = await self._analyze_batch(sample, provider_id)
            logger.info(f"[人格分析] 画像生成完成: 性格={result.get('personality', '未知')}, 风格={result.get('speaking_style', '未知')}")
            logger.info(f"[人格分析] 口头禅={result.get('catchphrases', [])}, 兴趣={result.get('interests', [])}, 风格规则数={len(result.get('style_guide', []))}")
            return result

        budget = token_budget if token_budget > 0 else self.TOKEN_BUDGET_PER_BATCH
        batches = self._create_token_aware_batches(messages, budget)
        logger.info(f"[人格分析] Token感知分批: {len(messages)} 条消息 → {len(batches)} 个批次")
        for i, batch in enumerate(batches):
            est_tokens = self._estimate_batch_tokens(batch)
            logger.info(f"[人格分析] 批次 {i+1}: {len(batch)} 条消息, 估算 ~{est_tokens} tokens")

        return await self._analyze_with_early_stop(
            batches, provider_id, batch_delay_ms, enable_early_stop
        )

    def _create_token_aware_batches(self, messages: list, token_budget: int) -> list:
        """按 token 预算动态分批，而非固定条数

        每个批次填满 token 预算为止，避免固定条数导致的
        短消息批次浪费空间、长消息批次溢出上下文窗口的问题。

        Args:
            messages: 消息列表
            token_budget: 每批次 token 预算

        Returns:
            分批后的消息列表的列表
        """
        content_budget = token_budget - self.PROMPT_OVERHEAD_TOKENS
        if content_budget <= 0:
            content_budget = token_budget

        batches = []
        current_batch = []
        current_tokens = 0

        for msg in messages:
            msg_tokens = self._estimate_msg_tokens(msg)

            if current_batch and (current_tokens + msg_tokens > content_budget):
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0

            current_batch.append(msg)
            current_tokens += msg_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    def _estimate_msg_tokens(self, msg) -> int:
        """估算单条消息的 token 数"""
        if isinstance(msg, dict):
            content = msg.get('formatted', msg.get('content', ''))
        else:
            content = str(msg)
        return max(1, len(content) // self.CHARS_PER_TOKEN)

    def _estimate_batch_tokens(self, batch: list) -> int:
        """估算一个批次的 token 总数"""
        return sum(self._estimate_msg_tokens(msg) for msg in batch)

    async def _analyze_with_early_stop(
        self,
        batches: list,
        provider_id: str,
        batch_delay_ms: int,
        enable_early_stop: bool,
    ) -> dict:
        """带早停收敛检测的分批分析

        每完成一个批次后，与之前的结果比较相似度。
        如果连续多个批次结果高度相似（收敛），则提前终止，
        避免在已确定的人格特征上浪费 API 请求。

        Args:
            batches: 分批后的消息列表
            provider_id: LLM 提供商 ID
            batch_delay_ms: 批次间延迟
            enable_early_stop: 是否启用早停

        Returns:
            最终的人格画像
        """
        batch_results = []
        converged = False

        for i, batch in enumerate(batches):
            logger.info(f"[人格分析] 分析第 {i + 1}/{len(batches)} 批次，{len(batch)} 条消息")
            result = await self._analyze_batch(batch, provider_id)
            batch_results.append(result)

            if enable_early_stop and len(batch_results) >= self.MIN_BATCHES_BEFORE_CONVERGENCE:
                similarity = self._compute_convergence(batch_results)
                logger.info(f"[人格分析] 收敛检测: 前 {len(batch_results)} 批次相似度 = {similarity:.2f}")

                if similarity >= self.CONVERGENCE_THRESHOLD:
                    logger.info(f"[人格分析] ✅ 收敛检测通过 (相似度 {similarity:.2f} ≥ {self.CONVERGENCE_THRESHOLD})，提前终止")
                    logger.info(f"[人格分析] 节省了 {len(batches) - len(batch_results)} 个批次的 API 请求")
                    converged = True
                    break

            if i < len(batches) - 1 and batch_delay_ms > 0:
                await asyncio.sleep(batch_delay_ms / 1000)

        if not converged and len(batches) > len(batch_results):
            logger.info(f"[人格分析] 未触发早停，已分析全部 {len(batch_results)}/{len(batches)} 批次")

        if len(batch_results) == 1:
            final_persona = batch_results[0]
        else:
            logger.info(f"[人格分析] 开始汇总 {len(batch_results)} 个批次结果")
            final_persona = await self._summarize_results(batch_results, provider_id)

        total_msg_count = sum(r.get('message_count', 0) for r in batch_results)
        final_persona['message_count'] = total_msg_count
        final_persona['batch_count'] = len(batch_results)
        final_persona['total_batches_planned'] = len(batches)
        final_persona['early_stopped'] = converged

        logger.info(f"[人格分析] 画像生成完成: 性格={final_persona.get('personality', '未知')}, 风格={final_persona.get('speaking_style', '未知')}")
        logger.info(f"[人格分析] 口头禅={final_persona.get('catchphrases', [])}, 兴趣={final_persona.get('interests', [])}, 风格规则数={len(final_persona.get('style_guide', []))}")
        logger.info(f"[人格分析] 统计: 消息={total_msg_count}, 批次={len(batch_results)}/{len(batches)}, 早停={'是' if converged else '否'}")

        return final_persona

    def _compute_convergence(self, results: list) -> float:
        """计算批次结果的收敛程度

        比较最新批次与之前所有批次的平均相似度。
        相似度基于核心人格字段的重叠程度计算。

        Args:
            results: 批次结果列表

        Returns:
            收敛分数 (0.0 ~ 1.0)，越高表示越收敛
        """
        if len(results) < 2:
            return 0.0

        latest = results[-1]
        previous = results[:-1]

        scores = []
        for prev in previous:
            score = self._persona_similarity(latest, prev)
            scores.append(score)

        return sum(scores) / len(scores)

    def _persona_similarity(self, a: dict, b: dict) -> float:
        """计算两个人格画像的相似度

        比较维度：
        1. personality 完全匹配 (+0.3)
        2. catchphrases 重叠率 (+0.25)
        3. tone 相似度 (+0.15)
        4. interests 重叠率 (+0.15)
        5. speaking_style 关键词重叠 (+0.15)

        Args:
            a: 人格画像 A
            b: 人格画像 B

        Returns:
            相似度 (0.0 ~ 1.0)
        """
        score = 0.0

        p_a = a.get('personality', '')
        p_b = b.get('personality', '')
        if p_a and p_b and p_a == p_b:
            score += 0.3
        elif p_a and p_b:
            common = set(p_a) & set(p_b)
            if common:
                score += 0.15 * len(common) / max(len(set(p_a)), len(set(p_b)), 1)

        cp_a = set(a.get('catchphrases', []))
        cp_b = set(b.get('catchphrases', []))
        if cp_a or cp_b:
            overlap = len(cp_a & cp_b) / max(len(cp_a | cp_b), 1)
            score += 0.25 * overlap

        t_a = a.get('tone', '')
        t_b = b.get('tone', '')
        if t_a and t_b and t_a == t_b:
            score += 0.15
        elif t_a and t_b:
            common = set(t_a) & set(t_b)
            if common:
                score += 0.075 * len(common) / max(len(set(t_a)), len(set(t_b)), 1)

        i_a = set(a.get('interests', []))
        i_b = set(b.get('interests', []))
        if i_a or i_b:
            overlap = len(i_a & i_b) / max(len(i_a | i_b), 1)
            score += 0.15 * overlap

        ss_a = a.get('speaking_style', '')
        ss_b = b.get('speaking_style', '')
        if ss_a and ss_b:
            words_a = set(ss_a)
            words_b = set(ss_b)
            if words_a or words_b:
                overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
                score += 0.15 * overlap

        return min(score, 1.0)

    async def _analyze_batch(self, batch: list, provider_id: str) -> dict:
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

            result = self._parse_response(response_text, len(batch))
            logger.info(f"[人格分析] 批次分析完成: 性格={result.get('personality', '未知')}, 口头禅数={len(result.get('catchphrases', []))}, 风格规则数={len(result.get('style_guide', []))}")
            return result

        except Exception as e:
            logger.error(f"[人格分析] 批次 LLM调用失败: {e}")
            return self._get_default_persona()

    def _build_batch_prompt(self, batch: list) -> str:
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

        return f"""分析以下聊天消息，提取说话者的人格画像。

消息样本（共{len(batch)}条）：
{sample_texts}

{extra_note}

输出 JSON，字段如下：

- personality: 核心性格（2-4字，如「开朗活泼」「内向稳重」「幽默风趣」）
- speaking_style: 说话风格一句话概括（如「说话随意，爱开玩笑」，不要超过15字）
- tone: 语气（如「亲切温和」「冷淡疏离」，2-4字）
- catchphrases: 口头禅列表（真正反复出现的词或句式，没有则空数组，最多5个）
- sentence_pattern: 常用句式（一句话，如「句子偏短，爱用反问」）
- emoji_usage: 表情习惯（一句话，如「偶尔用可爱表情」）
- punctuation: 标点习惯（一句话，如「爱用波浪号~」）
- interests: 兴趣关键词（3-5个，从消息推断）
- values: 价值观倾向（可选，如「重视友情」）
- emotional_pattern: 情绪特点（2-4字，如「外露」「内敛」）
- typical_responses: 选5-8条最能代表其说话风格的原消息原文，保持原样不修改
- style_guide: 最重要！从原消息中抽象出4-6条可执行的说话规则，每条规则描述「在什么场景下用什么方式说话」，格式如「觉得好笑时夸张表达，如先哈哈哈再简短评价」「用叠词表达强烈情绪，如绝了绝了」「回复偏短，通常3-8个字」「句末偶尔加~，不用句号」。规则要具体可操作，不要写「说话自然」这种空话

关键要求：
1. style_guide 是最重要的字段，务必从原消息中提炼出具体、可执行的说话规则
2. typical_responses 保留原文供交叉验证，style_guide 从中抽象规则
3. speaking_style/tone/emotional_pattern 要简短，不要写长描述
4. catchphrases 必须是真实出现过的，不要编造
5. 不明显的特征留空或写"无明显特征"

只输出 JSON。"""

    async def _summarize_results(self, results: list, provider_id: str) -> dict:
        prompt = f"""综合以下多批次的人格画像片段，得出统一的最终画像。

批次分析结果：
{json.dumps(results, ensure_ascii=False, indent=2)}

汇总规则：
1. personality：取最核心的性格描述（2-4字）
2. speaking_style：一句话概括（不超过15字），合并共同特征
3. tone：最主流的语气（2-4字）
4. catchphrases：高频口头禅去重合并
5. sentence_pattern：一句话概括
6. emoji_usage：一句话概括
7. punctuation：一句话概括
8. interests：合并去重
9. values：如有则保留
10. emotional_pattern：2-4字
11. typical_responses：从各批次的典型回复中选出最具代表性的5-8条，必须保留原文不修改
12. style_guide：最重要！从各批次的 style_guide 中合并去重，再结合 typical_responses 补充遗漏的规则，最终保留4-6条最核心的说话规则。规则要具体可操作，描述「在什么场景下用什么方式说话」

关键：style_guide 是最重要的字段，规则必须具体可执行，不要写空话。typical_responses 保留原文供交叉验证。

只输出 JSON。"""

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
            if results:
                logger.warning("[人格分析] 使用第一个批次结果作为 fallback")
                return results[0]
            return self._get_default_persona()

    def _parse_response(self, response_text: str, message_count: int) -> dict:
        parse_failed = False
        try:
            persona = json.loads(response_text)
        except json.JSONDecodeError:
            json_str = self._extract_json(response_text)
            if json_str:
                try:
                    persona = json.loads(json_str)
                except json.JSONDecodeError:
                    parse_failed = True
                    persona = self._get_default_persona()
            else:
                parse_failed = True
                persona = self._get_default_persona()

        if parse_failed:
            logger.warning("[人格分析] LLM响应JSON解析失败，使用默认画像")
            logger.debug(f"[人格分析] 原始响应前500字符: {response_text[:500]}")

        required_fields = [
            'personality', 'speaking_style', 'catchphrases', 'interests', 'emoji_usage',
            'tone', 'sentence_pattern', 'punctuation', 'values', 'emotional_pattern', 'typical_responses', 'style_guide'
        ]
        missing_fields = []
        for field in required_fields:
            if field not in persona:
                missing_fields.append(field)
                persona[field] = self._get_default_persona().get(field)

        if missing_fields:
            logger.debug(f"[人格分析] 缺失字段已补默认值: {missing_fields}")

        if not isinstance(persona.get('catchphrases'), list):
            persona['catchphrases'] = []
        if not isinstance(persona.get('interests'), list):
            persona['interests'] = []
        if not isinstance(persona.get('typical_responses'), list):
            persona['typical_responses'] = []
        if not isinstance(persona.get('style_guide'), list):
            persona['style_guide'] = []

        persona['message_count'] = message_count
        persona['created_at'] = None

        logger.debug(f"[人格分析] 批次解析结果: 性格={persona.get('personality')}, 风格={persona.get('speaking_style')}, 口头禅={persona.get('catchphrases')}, 兴趣={persona.get('interests')}, 风格规则数={len(persona.get('style_guide', []))}")

        return persona

    def _get_default_persona(self) -> dict:
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
            'style_guide': [],
            'message_count': 0,
            'created_at': None,
        }

    def _extract_json(self, text: str) -> str | None:
        start = text.find('{')
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for i, char in enumerate(text[start:], start):
            if escape:
                escape = False
                continue

            if char == '\\':
                escape = True
                continue

            if char == '"' and not escape:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]

        return None
