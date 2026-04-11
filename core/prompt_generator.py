"""
Prompt 生成器 - 生成带人格上下文的 Prompt
"""
from astrbot import logger


class PromptGenerator:
    """Prompt 生成器 - 注入人格上下文和历史记录"""

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
        # 人格特征部分
        personality = persona.get('personality', '普通')
        speaking_style = persona.get('speaking_style', '正常')
        catchphrases = persona.get('catchphrases', [])
        interests = ', '.join(persona.get('interests', [])) or '各种话题'
        emoji_usage = persona.get('emoji_usage', '自然使用')

        # 格式化口头禅（用于示例）
        catchphrase_examples = ''
        if catchphrases:
            catchphrase_examples = f"，比如会用到「{', '.join(catchphrases[:3])}」等口头禅"
        else:
            catchphrase_examples = ''

        # 使用代称或默认称呼
        name = alias or persona.get('alias', '群友')

        # 对话历史部分
        history_section = ""
        if history:
            history_lines = []
            for msg in history[-10:]:  # 只保留最近10条
                role = "群里有人" if msg['role'] == 'user' else "你"
                content = msg.get('content', '')
                # 跳过系统摘要消息
                if msg['role'] == 'system':
                    history_lines.append(f"[之前的聊天背景] {content}")
                else:
                    history_lines.append(f"{role}说：{content}")
            if history_lines:
                history_section = f"""

【刚才的聊天】
{chr(10).join(history_lines)}"""

        # 核心提示词 - 强调角色扮演
        prompt = f"""你现在就是{name}本人，不是 AI，不是助手，不是在模仿任何人。

【你的身份】
你是{name}，一个真实存在于这个群里的群友。你有着自己独特的性格和说话方式。

【你的性格和说话习惯】
- 性格特点：{personality}
- 说话风格：{speaking_style}{catchphrase_examples}
- 平时关注的话题：{interests}
- 表情使用习惯：{emoji_usage}

【重要规则】
1. 你就是{name}本人，任何时候都不要否认这一点
2. 如果有人问你「你是谁」「你是AI吗」「你在模仿谁」之类的问题，你要自然地回答你是{name}
3. 保持你的性格和说话风格，像平时在群里聊天那样回复
4. 不要使用「作为」「作为一个」这种开场白
5. 不要解释你为什么这样说话
6. 回复要简短自然，像群聊消息一样，不要太长
7. 如果有口头禅，可以适当使用，但要自然，不要刻意堆砌
{history_section}
【现在的消息】
{question}

用{name}的风格直接回复："""

        # Debug 输出
        logger.debug(f"[Prompt生成] 代称={name}, 性格={personality}, 风格={speaking_style}")
        logger.debug(f"[Prompt生成] 口头禅={catchphrases}, 问题长度={len(question)}")
        if history:
            logger.debug(f"[Prompt生成] 历史轮数={len(history)}, 使用最近{min(len(history), 10)}条")

        return prompt