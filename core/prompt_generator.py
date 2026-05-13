"""
Prompt 生成器 - 生成带人格上下文的 Prompt
"""
import re
from astrbot import logger


class PromptGenerator:
    """Prompt 生成器 - 注入人格上下文和历史记录"""

    MSG_SEPARATOR = "[MSG]"

    @staticmethod
    def split_messages(response: str) -> list[str]:
        """将 LLM 响应分割为多条消息

        Args:
            response: LLM 返回的响应文本

        Returns:
            分割后的消息列表（最多6条）
        """
        if not response:
            return []

        messages = re.split(r'\[MSG\]', response)
        messages = [msg.strip() for msg in messages if msg.strip()]

        if len(messages) > 6:
            logger.debug(f"[消息分割] 消息数量超过6条，截断为6条")
            messages = messages[:6]

        return messages if messages else [response.strip()]

    def generate(self, persona: dict, question: str, history: list = None, alias: str = None) -> str:
        """生成带人格上下文和历史记录的 prompt

        Args:
            persona: 人格画像字典
            question: 用户问题
            history: 对话历史列表（可选）
            alias: 代称（可选）

        Returns:
            生成的 prompt 字符串
        """
        name = alias or persona.get('alias', '群友')

        personality = persona.get('personality', '')
        speaking_style = persona.get('speaking_style', '')
        tone = persona.get('tone', '')
        catchphrases = persona.get('catchphrases', [])
        sentence_pattern = persona.get('sentence_pattern', '')
        interests = persona.get('interests', [])
        emoji_usage = persona.get('emoji_usage', '')
        punctuation = persona.get('punctuation', '')
        values = persona.get('values', '')
        emotional_pattern = persona.get('emotional_pattern', '')
        typical_responses = persona.get('typical_responses', [])

        character_sketch_parts = []
        if personality:
            character_sketch_parts.append(f"性格{personality}")
        if speaking_style:
            character_sketch_parts.append(speaking_style)
        if tone:
            character_sketch_parts.append(f"语气{tone}")
        if emotional_pattern:
            character_sketch_parts.append(f"情绪表达{emotional_pattern}")
        if sentence_pattern:
            character_sketch_parts.append(sentence_pattern)
        if emoji_usage:
            character_sketch_parts.append(emoji_usage)
        if punctuation:
            character_sketch_parts.append(punctuation)

        character_sketch = '，'.join(character_sketch_parts) if character_sketch_parts else '普通群友'

        interest_str = '、'.join(interests) if interests else ''

        values_note = ""
        if values:
            values_note = f"\n你在意的事情：{values}"

        interest_note = ""
        if interest_str:
            interest_note = f"\n你平时关注：{interest_str}"

        examples_section = ""
        if typical_responses:
            examples = "\n".join([f"- {resp}" for resp in typical_responses[:5]])
            examples_section = f"""

以下是{name}过去在群里说过的话，你的回复必须和这些话的风格一模一样：
{examples}"""

        catchphrase_note = ""
        if catchphrases:
            shown = '、'.join([f'「{c}」' for c in catchphrases[:3]])
            catchphrase_note = f"\n你有时会说{shown}之类的话，但只在合适的时候自然地说，不要每句都加"

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

        prompt = f"""你{name}，正在群里聊天。{character_sketch}。{values_note}{interest_note}{catchphrase_note}{examples_section}
{history_section}
群里有人说：{question}

{name}的回复（用[MSG]分隔多条消息，每条1-3句，总条数不超过3条）："""

        logger.debug(f"[Prompt生成] 代称={name}, 性格={personality}, 风格={character_sketch}")
        logger.debug(f"[Prompt生成] 口头禅={catchphrases}, 典型回复数={len(typical_responses)}")
        if history:
            logger.debug(f"[Prompt生成] 历史轮数={len(history)}, 使用最近{min(len(history), 10)}条")

        return prompt
