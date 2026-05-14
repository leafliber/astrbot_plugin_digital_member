"""
Prompt 生成器 - 生成带人格上下文的 Prompt
核心原则：示例驱动 > 特征描述，避免 LLM 过度表演人格特征
"""
import re
from astrbot import logger


class PromptGenerator:
    """Prompt 生成器 - 注入人格上下文和历史记录"""

    MSG_SEPARATOR = "[MSG]"

    CORE_INSTRUCTION = "像真人聊天一样自然回复，不要刻意展示性格特征，不要堆砌口头禅和表情，大部分就是将性格融入普通说话，偶尔会带带口头禅"

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

    def _parse_persona(self, persona: dict) -> dict:
        """从人格画像中提取各字段"""
        return {
            'personality': persona.get('personality', ''),
            'speaking_style': persona.get('speaking_style', ''),
            'tone': persona.get('tone', ''),
            'catchphrases': persona.get('catchphrases', []),
            'interests': persona.get('interests', []),
            'values': persona.get('values', ''),
            'typical_responses': persona.get('typical_responses', []),
        }

    def _build_examples_section(self, name: str, typical_responses: list) -> str:
        """构建示例段落"""
        if not typical_responses:
            return ""
        examples = "\n".join([f"· {resp}" for resp in typical_responses[:8]])
        return f"""
【{name}说过的话】（模仿这些话的语气和节奏，不是照抄内容）
{examples}"""

    def _build_background_section(self, catchphrases: list, interests: list, values: str) -> str:
        """构建背景提示段落"""
        parts = []
        if catchphrases:
            shown = '、'.join([f'「{c}」' for c in catchphrases[:3]])
            parts.append(f"偶尔自然带出{shown}等口头禅，但绝大多数时候不说。")
        if interests:
            parts.append(f"对{'、'.join(interests[:5])}比较熟悉。")
        if values:
            parts.append(f"在意{values}。")
        return "\n" + "".join(parts) if parts else ""

    def _build_history_section(self, name: str, history: list) -> str:
        """构建历史对话段落"""
        if not history:
            return ""
        history_lines = []
        for msg in history[-10:]:
            role = "群里" if msg['role'] == 'user' else name
            content = msg.get('content', '')
            if msg['role'] == 'system':
                history_lines.append(f"[背景] {content}")
            else:
                history_lines.append(f"{role}：{content}")
        if not history_lines:
            return ""
        return f"""

刚才的聊天：
{chr(10).join(history_lines)}"""

    def _build_iris_tool_guidance(self) -> str:
        """构建 iris_chat_memory 工具使用指引"""
        return """

【记忆工具使用指引】
你拥有以下记忆工具，可以在回复前主动调用它们来获取更多上下文信息，让你的回复更贴合真实情况：

- search_memory: 从长期记忆库检索相关记忆，用于回忆用户偏好、历史事件、关键信息等。当你需要回忆之前聊过的内容、用户的喜好或重要事件时使用。
- search_knowledge_graph: 搜索知识图谱中的实体和关系，用于查找人物关系、事件关联、概念联系等结构化知识。当你需要了解某个实体的详细信息或实体之间的关系时使用。
- get_profile: 获取用户或群聊的画像信息。用户画像包含性格、兴趣、禁忌话题等；群聊画像包含群聊兴趣、氛围标签、禁忌话题等。当你想了解聊天对象或群聊氛围时使用。

使用建议：
1. 收到消息后，先判断是否需要调用工具获取额外信息（大多数普通聊天不需要调用工具）
2. 只有当话题涉及用户偏好、历史事件、人物关系等需要回忆的内容时，才调用相关工具
3. 不要为了调用工具而调用，普通闲聊直接回复即可
4. 调用工具后，将获取的信息自然融入回复，不要生硬地引用工具结果"""

    def generate(self, persona: dict, question: str, history: list = None, alias: str = None) -> str:
        """生成普通模式的 prompt（单次 llm_generate 调用）"""
        name = alias or persona.get('alias', '群友')
        p = self._parse_persona(persona)

        brief_sketch = self._build_brief_sketch(p['personality'], p['speaking_style'], p['tone'])
        examples_section = self._build_examples_section(name, p['typical_responses'])
        background_section = self._build_background_section(p['catchphrases'], p['interests'], p['values'])
        history_section = self._build_history_section(name, history)

        prompt = f"""你正在以「{name}」的身份在群里聊天。{brief_sketch}{background_section}
{examples_section}
{history_section}
群里有人说：{question}

重要：{self.CORE_INSTRUCTION}。用[MSG]分隔多条消息，每条1-3句，总条数不超过3条。

{name}："""

        logger.debug(f"[Prompt生成] 代称={name}, 性格={p['personality']}, 示例数={len(p['typical_responses'])}")
        if history:
            logger.debug(f"[Prompt生成] 历史轮数={len(history)}, 使用最近{min(len(history), 10)}条")

        return prompt

    def generate_agent_system_prompt(self, persona: dict, history: list = None, alias: str = None, enable_iris_tools: bool = False) -> str:
        """生成 Agent 模式的 system prompt（tool_loop_agent 调用）

        Args:
            persona: 人格画像字典
            history: 对话历史
            alias: 代称
            enable_iris_tools: 是否启用了 iris_chat_memory 工具

        Returns:
            Agent 模式的 system prompt
        """
        name = alias or persona.get('alias', '群友')
        p = self._parse_persona(persona)

        brief_sketch = self._build_brief_sketch(p['personality'], p['speaking_style'], p['tone'])
        examples_section = self._build_examples_section(name, p['typical_responses'])
        background_section = self._build_background_section(p['catchphrases'], p['interests'], p['values'])
        history_section = self._build_history_section(name, history)
        iris_guidance = self._build_iris_tool_guidance() if enable_iris_tools else ""

        system_prompt = f"""你正在以「{name}」的身份在群里聊天。{brief_sketch}{background_section}
{examples_section}
{history_section}{iris_guidance}

重要规则：
1. {self.CORE_INSTRUCTION}
2. 用[MSG]分隔多条消息，每条1-3句，总条数不超过3条
3. 回复时以 [{name}] 开头"""

        logger.debug(f"[Prompt生成-Agent] 代称={name}, 性格={p['personality']}, 示例数={len(p['typical_responses'])}, iris_tools={enable_iris_tools}")

        return system_prompt

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
