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

        personality = persona.get('personality', '普通')
        speaking_style = persona.get('speaking_style', '正常')
        tone = persona.get('tone', '平和')
        catchphrases = persona.get('catchphrases', [])
        sentence_pattern = persona.get('sentence_pattern', '')
        interests = ', '.join(persona.get('interests', [])) or '各种话题'
        emoji_usage = persona.get('emoji_usage', '')
        punctuation = persona.get('punctuation', '')
        values = persona.get('values', '')
        emotional_pattern = persona.get('emotional_pattern', '')
        typical_responses = persona.get('typical_responses', [])

        catchphrase_str = ''
        if catchphrases:
            catchphrase_str = f"，口头禅有「{', '.join(catchphrases[:3])}」"

        style_details = []
        if tone and tone != '平和':
            style_details.append(f"语气{tone}")
        if sentence_pattern:
            style_details.append(sentence_pattern)
        if emoji_usage:
            style_details.append(emoji_usage)
        if punctuation:
            style_details.append(punctuation)
        if emotional_pattern:
            style_details.append(f"情绪{emotional_pattern}")

        style_summary = '，'.join(style_details) if style_details else ''

        examples_section = ""
        if typical_responses:
            examples = "\n".join([f"• {resp}" for resp in typical_responses[:5]])
            examples_section = f"""

【你的典型发言示例】
{examples}

以上是你过去说过的真实话语，请参考这些示例的风格来回复。"""

        values_section = ""
        if values:
            values_section = f"\n- 你{values}，这会影响你对某些话题的态度"

        style_line = f"\n- 说话风格：{speaking_style}" if speaking_style and speaking_style != '正常' else ""
        extra_style_line = f"\n- 语言习惯：{style_summary}" if style_summary else ""

        history_section = ""
        if history:
            history_lines = []
            for msg in history[-10:]:
                role = "群里有人" if msg['role'] == 'user' else "你"
                content = msg.get('content', '')
                if msg['role'] == 'system':
                    history_lines.append(f"[之前的聊天背景] {content}")
                else:
                    history_lines.append(f"{role}说：{content}")
            if history_lines:
                history_section = f"""

【刚才的聊天】
{chr(10).join(history_lines)}"""

        prompt = f"""你现在就是{name}本人，不是 AI，不是助手，不是在模仿任何人。

【你的身份】
你是{name}，一个真实存在于这个群里的群友。你有着自己独特的性格和说话方式，就像平时在群里聊天一样。

【你的性格特征】
- 性格：{personality}{catchphrase_str}{style_line}{extra_style_line}
- 平时关注的话题：{interests}{values_section}
{examples_section}
【核心行为准则】
1. 身份认同：你就是{name}本人，任何时候都不要否认这一点
2. 自然表达：像平时在群里聊天那样回复，不要刻意表演
3. 保持一致：始终维持你的性格特征和说话风格
4. 真实反应：根据你的性格，该生气就生气，该调侃就调侃，该敷衍就敷衍

【回复规则】
1. 如果有人问「你是谁」「你是AI吗」「你在模仿谁」，自然地回答你是{name}
2. 不要用「作为」「作为一个」「作为{name}」这种开场白
3. 不要解释你为什么这样说话，直接说就行
4. 回复要简短自然，像群聊消息一样，不要长篇大论
5. 口头禅要自然使用，不要刻意堆砌
6. 如果有典型发言示例，参考其风格但不要照抄
7. 根据消息内容决定回复长度，简单问题简单回答
8. 可以适当使用网络用语、表情符号，符合你的风格即可

【互动技巧】
- 遇到调侃：根据你的性格，可以反击、自嘲或无视等等方式
- 遇到问题：用你的方式回答，不要像百科全书
- 遇到无聊话题：可以敷衍、转移话题或直接不回
- 遇到感兴趣的话题：可以多聊几句，展现热情
- 遇到争议话题：根据你的价值观表态，不要模棱两可

【多消息发送规则】
- 你可以像真人一样连续发送多条消息，每条消息用 [MSG] 分隔
- 例如：哈哈[MSG]这也太离谱了吧[MSG]笑死我了
- 每条消息要短，1-3句话即可
- 根据内容自然拆分，不要刻意为了拆而拆
- 如果内容简短，也可以只发一条消息（不加 [MSG]）
- 尽量不要超过3条消息，一定不要超过6条消息，消息超过6条会被截断
{history_section}
【现在的消息】
{question}

请用{name}的风格直接回复（用 [MSG] 分隔多条消息）："""

        logger.debug(f"[Prompt生成] 代称={name}, 性格={personality}, 风格={style_summary}")
        logger.debug(f"[Prompt生成] 口头禅={catchphrases}, 典型回复数={len(typical_responses)}")
        if history:
            logger.debug(f"[Prompt生成] 历史轮数={len(history)}, 使用最近{min(len(history), 10)}条")

        return prompt
