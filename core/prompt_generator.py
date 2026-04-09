"""
Prompt 生成器 - 生成带人格上下文的 Prompt
"""


class PromptGenerator:
    """Prompt 生成器 - 注入人格上下文和历史记录"""

    def generate(self, persona: dict, question: str, history: list = None) -> str:
        """生成带人格上下文和历史记录的 prompt

        Args:
            persona: 人格画像字典
            question: 用户问题
            history: 对话历史列表（可选）

        Returns:
            生成的 prompt 字符串
        """
        # 人格特征部分
        personality = persona.get('personality', '未知')
        speaking_style = persona.get('speaking_style', '普通')
        catchphrases = ', '.join(persona.get('catchphrases', [])) or '无'
        interests = ', '.join(persona.get('interests', [])) or '无'
        emoji_usage = persona.get('emoji_usage', '无')

        persona_section = f"""【人格特征】
性格：{personality}
说话风格：{speaking_style}
口头禅：{catchphrases}
兴趣：{interests}
表情习惯：{emoji_usage}"""

        # 对话历史部分
        history_section = ""
        if history:
            history_lines = []
            for msg in history[-10:]:  # 只保留最近10条
                role = "用户" if msg['role'] == 'user' else "你"
                content = msg.get('content', '')
                # 跳过系统摘要消息
                if msg['role'] == 'system':
                    history_lines.append(f"[历史背景] {content}")
                else:
                    history_lines.append(f"{role}: {content}")
            if history_lines:
                history_section = f"""
【对话历史】
{chr(10).join(history_lines)}"""

        return f"""{persona_section}
{history_section}
【当前问题】
{question}

请用上述人格特征的语气和风格来回答，保持自然真实。不要暴露你是在模仿。如果口头禅不为空，适当使用口头禅。"""