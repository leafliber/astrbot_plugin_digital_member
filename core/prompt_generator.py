"""
Prompt 生成器 - 生成带人格上下文的 Prompt
核心原则：示例驱动 > 特征描述，避免 LLM 过度表演人格特征
"""
import re
from astrbot import logger


class PromptGenerator:
    """Prompt 生成器 - 注入人格上下文和历史记录"""

    MSG_SEPARATOR = "[MSG]"

    @staticmethod
    def split_messages(response: str) -> list[str]:
        if not response:
            return []

        messages = re.split(r'\[MSG\]', response)
        messages = [msg.strip() for msg in messages if msg.strip()]

        if len(messages) > 6:
            logger.debug(f"[消息分割] 消息数量超过6条，截断为6条")
            messages = messages[:6]

        return messages if messages else [response.strip()]

    def generate(self, persona: dict, question: str, history: list = None, alias: str = None) -> str:
        name = alias or persona.get('alias', '群友')

        personality = persona.get('personality', '')
        speaking_style = persona.get('speaking_style', '')
        tone = persona.get('tone', '')
        catchphrases = persona.get('catchphrases', [])
        interests = persona.get('interests', [])
        values = persona.get('values', '')
        typical_responses = persona.get('typical_responses', [])

        examples_section = ""
        if typical_responses:
            examples = "\n".join([f"· {resp}" for resp in typical_responses[:8]])
            examples_section = f"""
【{name}说过的话】（模仿这些话的语气和节奏，不是照抄内容）
{examples}"""

        brief_sketch = self._build_brief_sketch(personality, speaking_style, tone)

        catchphrase_hint = ""
        if catchphrases:
            shown = '、'.join([f'「{c}」' for c in catchphrases[:3]])
            catchphrase_hint = f"偶尔自然带出{shown}等口头禅，但绝大多数时候不说。"

        interest_hint = ""
        if interests:
            interest_hint = f"对{'、'.join(interests[:5])}比较熟悉。"

        values_hint = ""
        if values:
            values_hint = f"在意{values}。"

        background_hints = []
        if catchphrase_hint:
            background_hints.append(catchphrase_hint)
        if interest_hint:
            background_hints.append(interest_hint)
        if values_hint:
            background_hints.append(values_hint)

        background_section = ""
        if background_hints:
            background_section = "\n" + "".join(background_hints)

        history_section = ""
        if history:
            history_lines = []
            for msg in history[-10:]:
                role = "群里" if msg['role'] == 'user' else name
                content = msg.get('content', '')
                if msg['role'] == 'system':
                    history_lines.append(f"[背景] {content}")
                else:
                    history_lines.append(f"{role}：{content}")
            if history_lines:
                history_section = f"""

刚才的聊天：
{chr(10).join(history_lines)}"""

        prompt = f"""你正在以「{name}」的身份在群里聊天。{brief_sketch}{background_section}
{examples_section}
{history_section}
群里有人说：{question}

重要：像真人聊天一样自然回复，不要刻意展示性格特征，不要堆砌口头禅和表情，绝大多数时候就是普通说话。用[MSG]分隔多条消息，每条1-3句，总条数不超过3条。

{name}："""

        logger.debug(f"[Prompt生成] 代称={name}, 性格={personality}, 示例数={len(typical_responses)}")
        if history:
            logger.debug(f"[Prompt生成] 历史轮数={len(history)}, 使用最近{min(len(history), 10)}条")

        return prompt

    def _build_brief_sketch(self, personality: str, speaking_style: str, tone: str) -> str:
        """构建简短的角色素描，避免特征堆砌

        只保留最核心的 1-2 个特征描述，让 LLM 有基本方向感，
        但不至于逐条表演。具体风格由典型回复示例传达。
        """
        core_parts = []
        if personality:
            core_parts.append(personality)
        if speaking_style:
            core_parts.append(speaking_style)
        if tone and tone not in (personality or '') and tone not in (speaking_style or ''):
            core_parts.append(f"语气{tone}")

        if not core_parts:
            return "普通群友"

        sketch = '，'.join(core_parts[:2])
        return sketch
