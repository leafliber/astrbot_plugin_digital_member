# AstrBot 数字群友插件构建计划

## 项目概述

**插件名称**: `astrbot_plugin_digital_member`

**功能描述**: 分析群友历史消息，生成说话风格和个人画像，支持模仿群友进行交流

**适配协议**: OneBot v11 (aiocqhttp)

---

## 一、项目结构

```
astrbot_plugin_digital_member/
├── main.py                 # 插件主入口（必须命名为 main.py）
├── metadata.yaml           # 插件元数据（必需）
├── _conf_schema.json       # 配置模式定义
├── requirements.txt        # 依赖包
├── logo.png                # 插件Logo（可选，256x256）
├── core/
│   ├── __init__.py
│   ├── message_collector.py    # 消息收集器
│   ├── persona_analyzer.py     # 画像分析器
│   ├── prompt_generator.py     # Prompt生成器
│   ├── conversation_manager.py # 对话历史管理器
│   └── session_manager.py      # 持续唤醒管理器
├── utils/
│   ├── __init__.py
│   └── storage.py          # 存储工具（KV+文件）
└── data/                   # 运行时自动创建
    └── personas/           # 画像JSON文件
```

---

## 二、插件元数据 (metadata.yaml)

```yaml
# 插件展示名（市场显示）
display_name: "数字群友"

# 支持的平台适配器
support_platforms:
  - aiocqhttp    # OneBot 协议

# AstrBot 版本约束（PEP 440 格式）
astrbot_version: ">=4.16,<5"
```

**字段说明**：

| 字段 | 必需 | 说明 |
|------|------|------|
| `display_name` | 可选 | 插件市场显示名称 |
| `support_platforms` | 可选 | 支持的平台列表 |
| `astrbot_version` | 可选 | 版本约束 |

**支持的平台值**：
- `aiocqhttp` - OneBot 协议
- `qq_official` - QQ 官方
- `telegram` - Telegram
- `discord` - Discord
- 其他：`wecom`, `lark`, `dingtalk`, `slack`, `kook`, `vocechat`, `weixin_official_account`, `satori`, `misskey`, `line`

---

## 三、核心功能模块

### 3.1 指令设计

| 指令 | 别名 | 参数 | 功能 |
|------|------|------|------|
| `/mb 分析` | `/群友 分析` | `@群友/QQ号 代称 [时间范围]` | 一键克隆群友人格 |
| `/mb 画像` | `/群友 画像` | `@群友/QQ号/代称` | 查看群友画像 |
| `/mb 询问` | `/群友 询问` | `@群友/QQ号/代称 问题内容` | 模仿群友回答 |
| `/mb 唤醒` | `/群友 唤醒` | `@群友/QQ号/代称` | 持续唤醒模式 |
| `/mb 休眠` | `/群友 休眠` | - | 结束持续唤醒 |
| `/mb 清空` | `/群友 清空` | `@群友/QQ号/代称` | 清空对话历史 |
| `/mb 列表` | `/群友 列表` | - | 查看已克隆的群友 |
| `/mb 删除` | `/群友 删除` | `@群友/QQ号/代称` | 删除群友画像 |

**时间范围参数说明**（可选，默认30天）：
- `7d` / `7天` - 最近7天
- `30d` / `30天` - 最近30天
- `90d` / `90天` - 最近90天
- `all` / `全部` - 所有历史

### 3.2 指令格式详解

#### 分析指令（一键克隆）
```
/mb 分析 @张三 小张           # 默认30天，全自动完成
/mb 分析 @张三 小张 7天       # 最近7天，更快完成
/mb 分析 12345678 老王 all    # 全部历史
/群友 分析 @李四 阿四         # 默认30天
```

**全自动流程**：
1. 用户发送指令
2. 系统自动分批获取历史消息
3. 系统自动筛选目标用户消息
4. 系统自动调用LLM分析生成画像
5. 系统自动保存画像和代称映射
6. 返回完成结果

**全程无需用户干预，一步到位完成人格克隆**。

#### 询问指令
```
/mb 询问 小张 今天天气怎么样
/mb 询问 @张三 你觉得呢
/mb 询问 12345678 在干嘛
/群友 询问 老王 吃了吗
```
- 第一个参数：用户标识（@群友、QQ号 或 代称）
- 后续内容：问题

#### 唤醒/休眠指令
```
/mb 唤醒 小张
/mb 唤醒 @张三
/mb 休眠
```
- 唤醒时指定要模仿的群友
- 休眠无需参数，结束当前群的唤醒状态

### 3.3 用户标识解析

插件支持三种用户标识方式：

1. **@群友（At 消息段）**：从消息链中解析 `At` 组件获取 QQ 号
2. **QQ号**：直接使用数字 QQ 号
3. **代称**：使用分析时设定的代称，通过映射表查找 QQ 号

```python
# 消息链示例
[
    Comp.Plain("/mb 分析 "),
    Comp.At(qq=12345678),  # @群友
    Comp.Plain(" 小张 200")
]
```

### 3.4 核心模块功能

#### 消息收集器 (message_collector.py)
- **全自动分批获取群历史消息**
  - 静默执行，无需用户干预
  - 使用 `get_group_msg_history` API 分批次获取
  - 每批次默认获取 100 条消息
  - 通过 `message_seq` 参数实现翻页获取更早消息
  - 自动时间范围过滤（7天/30天/90天/全部）
  - 批次间短暂延迟（100ms），避免API限速
  - 自动筛选目标用户消息
- 消息预处理（过滤系统消息、空消息等）
- 数据规模自动控制（上限保护）

**自动分批获取策略**：
1. 从最新消息开始（message_seq=0）
2. 每批获取100条，自动翻页
3. 自动检查消息时间戳，超出范围则停止
4. 自动筛选目标用户的有效消息
5. 达到上限或无更多消息时自动停止
6. 最终取最多500条代表性消息供分析

#### 对话历史管理器 (conversation_manager.py)
- 维护每个人格独立的对话历史
- 自动压缩机制：
  - 达到15轮对话触发压缩
  - AI生成旧对话摘要
  - 保留最近5轮完整对话
- 对话历史存储在 persona.json 中
- 支持清空历史

#### 会话管理器 (session_manager.py)
- 管理持续唤醒状态
- 实现自动超时机制（默认 5 分钟）
- 支持多群独立会话

---

## 四、技术实现细节

### 4.1 指令注册（遵循 AstrBot 官方规范）

```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig

class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # ... 初始化组件

    # 指令组注册 - alias 支持中文别名
    @filter.command_group("mb", alias={"群友"})
    def mb(self):
        """群友人格克隆指令组"""
        pass

    @mb.command("分析", alias={"analyze"})
    async def analyze(self, event: AstrMessageEvent):
        """一键克隆群友人格

        用法: /mb 分析 @群友 代称 [时间范围]
        """
        # 实现见 3.3
        pass

    @mb.command("询问", alias={"ask"})
    async def ask(self, event: AstrMessageEvent):
        """模仿群友回答

        用法: /mb 询问 @群友/QQ号/代称 问题内容
        """
        # 实现见 3.4
        pass

    @mb.command("唤醒", alias={"awake", "wakeup"})
    async def awake(self, event: AstrMessageEvent):
        """进入持续唤醒模式

        用法: /mb 唤醒 代称
        """
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        # 解析目标群友...
        pass

    @mb.command("休眠", alias={"sleep"})
    async def sleep(self, event: AstrMessageEvent):
        """退出持续唤醒模式"""
        pass

    @mb.command("画像", alias={"profile"})
    async def profile(self, event: AstrMessageEvent):
        """查看群友画像"""
        pass

    @mb.command("列表", alias={"list"})
    async def list_personas(self, event: AstrMessageEvent):
        """已克隆的群友列表"""
        pass

    @mb.command("删除", alias={"delete", "del"})
    async def delete(self, event: AstrMessageEvent):
        """删除群友画像"""
        pass

    @mb.command("清空", alias={"clear"})
    async def clear_history(self, event: AstrMessageEvent):
        """清空对话历史"""
        pass

    # 消息事件监听 - 仅群聊 + aiocqhttp 平台
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理群消息，支持持续唤醒模式"""
        group_id = event.message_obj.group_id

        # 检查是否有活跃会话
        session = self.session_manager.get_active(group_id)
        if not session:
            return  # 无活跃会话，不处理

        qq, alias = session
        self.session_manager.update_activity(group_id)

        # 获取人格对话历史并生成回复
        persona = await self.storage.load_persona(qq)
        if persona:
            history = await self.conversation_manager.get_history(qq)
            prompt = self.prompt_generator.generate(persona, event.message_str, history)

            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)
            llm_resp = await self.context.llm_generate(
                chat_provider_id=prov_id,
                prompt=prompt,
            )

            response = llm_resp.completion_text
            await self.conversation_manager.add_message(qq, 'assistant', response)
            yield event.plain_result(response)
```

**指令注册要点**：

| 特性 | 用法 | 说明 |
|------|------|------|
| 指令组 | `@filter.command_group("mb", alias={"群友"})` | 支持中文别名 |
| 子指令 | `@mb.command("分析", alias={"analyze"})` | 自动解析参数 |
| 权限控制 | `@filter.permission_type(filter.PermissionType.ADMIN)` | 仅管理员可用 |
| 平台过滤 | `@filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)` | 仅指定平台 |
| 事件类型 | `@filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)` | 仅群聊 |
| 停止传播 | `event.stop_event()` | 阻止后续处理 |

### 4.2 自动分批获取群历史消息

```python
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from datetime import datetime, timedelta
import asyncio
from astrbot import logger

# 时间范围解析
TIME_RANGE_MAP = {
    "7d": 7, "7天": 7,
    "30d": 30, "30天": 30,
    "90d": 90, "90天": 90,
    "all": None, "全部": None, "所有": None,
}

class MessageCollector:
    # 分批配置（从插件配置读取）
    def __init__(self, batch_size: int = 100):
        self.BATCH_SIZE = batch_size
        self.BATCH_DELAY = 0.1         # 批次间延迟（秒）
        self.MAX_ANALYZE_COUNT = 500   # 最终分析的最大消息数
        self.MAX_RAW_MESSAGES = 10000  # 单次获取的最大原始消息数

    def parse_time_range(self, time_str: str) -> int | None:
        """解析时间范围参数"""
        if not time_str:
            return 30  # 默认30天
        time_str = time_str.strip().lower()
        return TIME_RANGE_MAP.get(time_str, 30)

    async def collect_messages(
        self,
        event: AstrMessageEvent,
        user_id: str,
        time_range: int | None = 30
    ) -> list:
        """
        全自动分批获取群历史消息并筛选指定用户
        """
        if event.get_platform_name() != "aiocqhttp":
            return []

        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)

        client = event.bot
        group_id = event.message_obj.group_id

        # 计算时间截止点
        cutoff_timestamp = None
        if time_range is not None:
            cutoff_timestamp = int((datetime.now() - timedelta(days=time_range)).timestamp())

        logger.info(f"[人格克隆] 开始收集: 群={group_id}, 用户={user_id}, 时间范围={time_range or '全部'}天")

        all_messages = []
        user_messages = []
        message_seq = 0

        # 自动循环获取
        while len(all_messages) < self.MAX_RAW_MESSAGES:
            try:
                result = await client.api.call_action(
                    'get_group_msg_history',
                    group_id=int(group_id),
                    message_seq=message_seq,
                    count=self.BATCH_SIZE
                )
                messages = result.get("data", {}).get("messages", [])

                if not messages:
                    break

                # 处理消息
                for msg in messages:
                    msg_time = msg.get('time', 0)
                    msg_user = str(msg.get('sender', {}).get('user_id', ''))

                    # 时间检查
                    if cutoff_timestamp and msg_time < cutoff_timestamp:
                        logger.info(f"[人格克隆] 时间范围达标，停止收集")
                        return self._finalize_messages(user_messages)

                    all_messages.append(msg)

                    # 筛选目标用户
                    if msg_user == user_id:
                        raw_msg = msg.get('raw_message', '')
                        if raw_msg:
                            user_messages.append({
                                'time': msg_time,
                                'content': raw_msg,
                            })

                # 获取下一批起点
                next_seq = messages[-1].get('message_seq', 0)
                if next_seq == message_seq or next_seq == 0:
                    break
                message_seq = next_seq

                # 批次延迟
                await asyncio.sleep(self.BATCH_DELAY)

            except Exception as e:
                logger.error(f"[人格克隆] API错误: {e}")
                break

        logger.info(f"[人格克隆] 收集完成: 原始={len(all_messages)}, 用户={len(user_messages)}")
        return self._finalize_messages(user_messages)

    def _finalize_messages(self, messages: list) -> list:
        """最终处理：限制数量，保留最新"""
        if len(messages) > self.MAX_ANALYZE_COUNT:
            return messages[-self.MAX_ANALYZE_COUNT:]
        return messages
```

### 4.3 分析指令实现（全自动一键克隆）

```python
@mb.command("分析", alias={"analyze"})
async def analyze(self, event: AstrMessageEvent, time_range: str = "30天"):
    """一键克隆群友人格 - 全自动完成

    用法: /mb 分析 @群友 代称 [时间范围]
    """
    group_id = event.message_obj.group_id
    if not group_id:
        yield event.plain_result("此功能仅在群聊中可用")
        return

    # 解析用户标识和代称
    message_chain = event.message_obj.message
    target_qq = None
    alias = None

    for i, component in enumerate(message_chain):
        if isinstance(component, Comp.At):
            target_qq = str(component.qq)
            if i + 1 < len(message_chain):
                next_comp = message_chain[i + 1]
                if isinstance(next_comp, Comp.Plain):
                    text = next_comp.text.strip()
                    parts = text.split(maxsplit=1)
                    alias = parts[0]
                    if len(parts) > 1:
                        time_range = parts[1]
            break

    if not target_qq:
        yield event.plain_result("请 @ 要克隆的群友")
        return

    if not alias:
        alias = target_qq

    days = self.message_collector.parse_time_range(time_range)
    time_desc = "全部历史" if days is None else f"最近{days}天"

    yield event.plain_result(f"正在克隆 {alias} 的人格...\n时间范围: {time_desc}")

    # 自动分批收集消息
    messages = await self.message_collector.collect_messages(
        event=event,
        user_id=target_qq,
        time_range=days
    )

    if not messages:
        yield event.plain_result(f"未找到 {alias} 在 {time_desc} 的有效消息")
        return

    # 自动分析生成画像
    persona = await self.persona_analyzer.analyze(messages)

    # 自动保存
    await self.storage.save_persona(target_qq, persona)
    await self.storage.save_alias(alias, target_qq, group_id)

    yield event.plain_result(
        f"✅ 人格克隆完成！\n"
        f"━━━━━━━━━━━━━━━\n"
        f"代称: {alias}\n"
        f"样本: {len(messages)} 条消息\n"
        f"━━━━━━━━━━━━━━━\n"
        f"/mb 询问 {alias} 问题 - 模仿对话\n"
        f"/mb 唤醒 {alias} - 持续对话"
    )
```

### 4.4 询问指令实现

```python
@mb.command("询问", alias={"ask"})
async def ask(self, event: AstrMessageEvent):
    """模仿群友回答问题

    用法: /mb 询问 @群友/QQ号/代称 问题内容
    """
    group_id = event.message_obj.group_id
    if not group_id:
        yield event.plain_result("此功能仅在群聊中可用")
        return

    # 解析消息链
    message_chain = event.message_obj.message
    target_qq = None
    question_parts = []
    found_identifier = False

    for component in message_chain:
        if isinstance(component, Comp.At):
            target_qq = str(component.qq)
            found_identifier = True
        elif isinstance(component, Comp.Plain):
            text = component.text.strip()
            if not found_identifier and text:
                parts = text.split(maxsplit=1)
                identifier = parts[0]

                qq = await self.storage.get_qq_by_alias(identifier, group_id)
                if qq:
                    target_qq = qq
                    found_identifier = True
                elif identifier.isdigit():
                    target_qq = identifier
                    found_identifier = True

                if len(parts) > 1:
                    question_parts.append(parts[1])
            elif found_identifier and text:
                question_parts.append(text)

    if not target_qq:
        yield event.plain_result("请指定要模仿的群友")
        return

    question = " ".join(question_parts)
    if not question:
        yield event.plain_result("请输入要询问的问题")
        return

    # 加载画像
    persona = await self.storage.load_persona(target_qq)
    if not persona:
        yield event.plain_result(f"未找到该群友的画像，请先使用 /mb 分析")
        return

    # 获取人格独立的对话历史
    history = await self.conversation_manager.get_history(target_qq)

    # 记录用户消息
    await self.conversation_manager.add_message(target_qq, 'user', question)

    # 生成带历史的 prompt
    prompt = self.prompt_generator.generate(persona, question, history)

    # 直接调用 AI，注入人格上下文
    umo = event.unified_msg_origin
    prov_id = await self.context.get_current_chat_provider_id(umo=umo)

    llm_resp = await self.context.llm_generate(
        chat_provider_id=prov_id,
        prompt=prompt,
    )

    response = llm_resp.completion_text

    # 记录回复
    await self.conversation_manager.add_message(target_qq, 'assistant', response)

    yield event.plain_result(response)
```

### 4.5 AI 调用设计（遵循 AstrBot 官方规范）

```python
from astrbot.api.event import AstrMessageEvent
from astrbot.core.agent.tool import ToolSet
import json

class PersonaAnalyzer:
    """画像分析器 - 调用 AI 分析消息"""

    def __init__(self, context):
        self.context = context

    async def analyze(self, messages: list) -> dict:
        """分析消息生成画像"""
        prompt = self._build_analysis_prompt(messages)

        # 直接调用 AI（不使用工具）
        llm_resp = await self.context.llm_generate(
            chat_provider_id=None,
            prompt=prompt,
        )

        return self._parse_response(llm_resp.completion_text)

    def _build_analysis_prompt(self, messages: list) -> str:
        """构造分析 prompt"""
        sample_texts = "\n".join([f"- {msg['content']}" for msg in messages[:100]])
        return f"""请分析以下聊天消息，提取说话者的性格和语言风格特征。

消息样本：
{sample_texts}

请输出 JSON 格式的画像，包含以下字段：
- personality: 性格特征描述
- speaking_style: 说话风格（如幽默、严肃、可爱等）
- catchphrases: 口头禅列表
- interests: 兴趣爱好关键词
- emoji_usage: 表情符号使用习惯
"""


class PromptGenerator:
    """Prompt 生成器 - 注入人格上下文"""

    def __init__(self, custom_template: str = ""):
        self.custom_template = custom_template

    def generate(self, persona: dict, question: str, history: list = None) -> str:
        """生成带人格上下文和历史记录的 prompt"""
        # 人格特征部分
        persona_section = f"""【人格特征】
性格：{persona.get('personality', '未知')}
说话风格：{persona.get('speaking_style', '普通')}
口头禅：{', '.join(persona.get('catchphrases', []))}
兴趣：{', '.join(persona.get('interests', []))}
表情习惯：{persona.get('emoji_usage', '无')}
"""

        # 对话历史部分
        history_section = ""
        if history:
            history_lines = []
            for msg in history[-10:]:
                role = "用户" if msg['role'] == 'user' else "你"
                history_lines.append(f"{role}: {msg['content']}")
            history_section = f"""
【对话历史】
{chr(10).join(history_lines)}
"""

        # 自定义模板支持
        if self.custom_template:
            return self.custom_template.format(
                personality=persona.get('personality', '未知'),
                speaking_style=persona.get('speaking_style', '普通'),
                catchphrases=', '.join(persona.get('catchphrases', [])),
                interests=', '.join(persona.get('interests', [])),
                question=question
            )

        return f"""{persona_section}
{history_section}
【当前问题】
{question}

请用上述人格特征的语气和风格来回答，保持自然真实。不要暴露你是在模仿。"""


class PersonaConversationManager:
    """
    人格对话管理器 - 维护每个人格独立的对话历史
    实现自动压缩机制
    """

    def __init__(
        self,
        storage,
        max_turns: int = 20,
        compress_threshold: int = 15,
        summary_turns: int = 5
    ):
        self.storage = storage
        self.MAX_HISTORY_TURNS = max_turns        # 最大保留对话轮数
        self.COMPRESS_THRESHOLD = compress_threshold  # 触发压缩的阈值
        self.SUMMARY_TURNS = summary_turns        # 压缩时保留的最近轮数

    async def get_history(self, qq: str) -> list:
        """获取人格的对话历史"""
        persona = await self.storage.load_persona(qq)
        if persona and 'conversation_history' in persona:
            return persona['conversation_history']
        return []

    async def add_message(self, qq: str, role: str, content: str):
        """添加消息到对话历史"""
        persona = await self.storage.load_persona(qq)
        if not persona:
            return

        if 'conversation_history' not in persona:
            persona['conversation_history'] = []

        persona['conversation_history'].append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })

        # 检查是否需要压缩
        if len(persona['conversation_history']) >= self.COMPRESS_THRESHOLD * 2:
            await self._compress_history(qq, persona)

        await self.storage.save_persona(qq, persona)

    async def _compress_history(self, qq: str, persona: dict):
        """
        自动压缩对话历史
        将旧对话压缩为摘要，保留最近的对话
        """
        history = persona.get('conversation_history', [])
        if len(history) < self.COMPRESS_THRESHOLD * 2:
            return

        # 分离旧对话和最近对话
        old_messages = history[:-self.SUMMARY_TURNS * 2]
        recent_messages = history[-self.SUMMARY_TURNS * 2:]

        if not old_messages:
            return

        # 生成旧对话摘要
        summary = await self._generate_summary(old_messages)

        # 更新历史：摘要 + 最近对话
        persona['conversation_history'] = [
            {'role': 'system', 'content': f'[历史摘要] {summary}'}
        ] + recent_messages

        persona['last_compressed'] = datetime.now().isoformat()
        logger.info(f"[人格对话] 已压缩 {qq} 的对话历史")

    async def _generate_summary(self, messages: list) -> str:
        """使用 AI 生成对话摘要"""
        # 构造对话文本
        conversation_text = "\n".join([
            f"{'用户' if m['role'] == 'user' else '回复'}: {m['content']}"
            for m in messages
        ])

        summary_prompt = f"""请将以下对话压缩为简短的摘要（100字以内），保留关键信息和情感基调：

{conversation_text}

摘要："""

        llm_resp = await self.storage.star.context.llm_generate(
            chat_provider_id=None,
            prompt=summary_prompt,
        )

        return llm_resp.completion_text.strip()

    async def clear_history(self, qq: str):
        """清空对话历史"""
        persona = await self.storage.load_persona(qq)
        if persona:
            persona['conversation_history'] = []
            await self.storage.save_persona(qq, persona)
```

**对话历史存储结构**：

```python
# 存储在 persona.json 中
{
    "personality": "开朗活泼",
    "speaking_style": "幽默",
    "catchphrases": ["哈哈哈", "确实"],
    "interests": ["游戏", "动漫"],
    "emoji_usage": "喜欢用 😂 和 👍",
    "conversation_history": [
        {"role": "system", "content": "[历史摘要] 用户询问了游戏和动漫相关话题，聊得很开心..."},
        {"role": "user", "content": "今天天气怎么样"},
        {"role": "assistant", "content": "哈哈今天天气超好的，适合打游戏！"},
        ...
    ],
    "last_compressed": "2026-04-09T10:30:00"
}
```

**自动压缩机制**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `MAX_HISTORY_TURNS` | 20 | 最大保留对话轮数 |
| `COMPRESS_THRESHOLD` | 15 | 达到此轮数触发压缩 |
| `SUMMARY_TURNS` | 5 | 压缩时保留的最近轮数 |

**压缩流程**：
```
对话历史达到 30 条消息（15轮）
    ↓
分离：旧对话(20条) + 最近对话(10条)
    ↓
AI 生成旧对话摘要
    ↓
新历史 = [摘要] + 最近对话
```

### 4.6 存储设计（遵循 AstrBot 官方规范）

```python
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
import json
from astrbot.api.star import Star

class PersonaStorage:
    """画像存储管理器"""

    def __init__(self, star_instance: Star):
        # 使用插件实例获取存储能力
        self.star = star_instance
        # 大文件存储路径
        self.data_path = get_astrbot_data_path() / "plugin_data" / star_instance.name / "personas"
        self.data_path.mkdir(parents=True, exist_ok=True)

    # ===== KV 存储：代称映射（轻量数据） =====

    async def save_alias(self, alias: str, qq: str, group_id: str):
        """保存代称映射 - 使用 KV 存储"""
        # 按 group_id 分组存储映射表
        key = f"alias_{group_id}"
        aliases = await self.star.get_kv_data(key, {})
        aliases[alias] = qq
        await self.star.put_kv_data(key, aliases)

    async def get_qq_by_alias(self, alias: str, group_id: str) -> str | None:
        """通过代称查找 QQ 号 - 使用 KV 存储"""
        key = f"alias_{group_id}"
        aliases = await self.star.get_kv_data(key, {})
        return aliases.get(alias)

    async def list_aliases(self, group_id: str) -> dict:
        """获取群内所有代称映射"""
        key = f"alias_{group_id}"
        return await self.star.get_kv_data(key, {})

    # ===== 文件存储：人物画像（大数据） =====

    async def save_persona(self, qq: str, data: dict):
        """保存人物画像 - 使用文件存储"""
        file_path = self.data_path / f"{qq}.json"
        data['updated_at'] = datetime.now().isoformat()
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def load_persona(self, qq: str) -> dict | None:
        """加载人物画像"""
        file_path = self.data_path / f"{qq}.json"
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    async def delete_persona(self, qq: str):
        """删除人物画像"""
        file_path = self.data_path / f"{qq}.json"
        if file_path.exists():
            file_path.unlink()

    async def list_personas(self) -> list:
        """列出所有画像"""
        personas = []
        for file in self.data_path.glob("*.json"):
            qq = file.stem
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                personas.append({
                    "qq": qq,
                    "alias": data.get("alias", qq),
                    "created_at": data.get("created_at", ""),
                    "message_count": data.get("message_count", 0)
                })
        return personas
```

**存储策略说明**：

| 数据类型 | 存储方式 | 原因 |
|---------|---------|------|
| 代称映射 | KV 存储 (`put_kv_data`) | 轻量 key-value，按群分组 |
| 人物画像 | 文件存储 (`plugin_data/`) | 数据量大，包含详细分析结果 |

**KV 存储 Key 格式**：
- `alias_{group_id}` - 存储该群的代称映射表
- 例如：`alias_12345678` 对应群 12345678 的所有代称

**文件存储路径**：
- `data/plugin_data/{plugin_name}/personas/{qq}.json`
- 例如：`data/plugin_data/astrbot_plugin_digital_member/personas/12345.json`

### 4.7 持续唤醒机制

```python
import asyncio
from datetime import datetime, timedelta

class SessionManager:
    """会话管理器 - 持续唤醒状态管理"""

    def __init__(self, timeout_minutes: int = 5):
        self.active_sessions = {}
        self.timeout = timedelta(minutes=timeout_minutes)

    async def activate(self, group_id: str, qq: str, alias: str):
        """激活持续唤醒"""
        if group_id in self.active_sessions:
            old_session = self.active_sessions[group_id]
            if old_session.get("task"):
                old_session["task"].cancel()

        self.active_sessions[group_id] = {
            "qq": qq,
            "alias": alias,
            "last_active": datetime.now(),
            "task": asyncio.create_task(self._timeout_check(group_id))
        }

    async def deactivate(self, group_id: str):
        """结束持续唤醒"""
        if group_id in self.active_sessions:
            session = self.active_sessions[group_id]
            if session.get("task"):
                session["task"].cancel()
            del self.active_sessions[group_id]

    def get_active(self, group_id: str) -> tuple[str, str] | None:
        """获取当前激活的群友 (qq, alias)"""
        session = self.active_sessions.get(group_id)
        if session:
            return session["qq"], session["alias"]
        return None

    def update_activity(self, group_id: str):
        """更新活跃时间"""
        if group_id in self.active_sessions:
            self.active_sessions[group_id]["last_active"] = datetime.now()

    async def _timeout_check(self, group_id: str):
        """超时自动休眠"""
        try:
            while True:
                await asyncio.sleep(60)
                session = self.active_sessions.get(group_id)
                if session:
                    if datetime.now() - session["last_active"] > self.timeout:
                        await self.deactivate(group_id)
                        break
                else:
                    break
        except asyncio.CancelledError:
            pass
```

---

## 五、配置模式 (_conf_schema.json)

遵循 AstrBot 插件配置规范：https://docs.astrbot.app/dev/star/guides/plugin-config.html

```json
{
  "default_time_range": {
    "description": "一键克隆时的默认时间范围",
    "type": "string",
    "default": "30天",
    "options": ["7天", "30天", "90天", "全部"]
  },
  "batch_size": {
    "description": "调用API时每批次获取的消息数量",
    "type": "int",
    "default": 100,
    "hint": "建议50-200，过大可能导致API超时"
  },
  "batch_delay_ms": {
    "description": "批次间延迟（毫秒）",
    "type": "int",
    "default": 100,
    "hint": "避免API限速"
  },
  "max_analyze_count": {
    "description": "最终送给LLM分析的最大消息数",
    "type": "int",
    "default": 500,
    "hint": "限制LLM输入长度"
  },
  "max_history_turns": {
    "description": "每个人格保留的最大对话轮数",
    "type": "int",
    "default": 20
  },
  "compress_threshold": {
    "description": "达到此轮数触发自动压缩",
    "type": "int",
    "default": 15,
    "hint": "对话历史超过此值时自动压缩旧对话"
  },
  "session_timeout_minutes": {
    "description": "持续唤醒模式无活动自动休眠时间（分钟）",
    "type": "int",
    "default": 5
  },
  "custom_prompt_template": {
    "description": "自定义模仿Prompt模板",
    "type": "text",
    "default": "",
    "hint": "留空使用默认模板，可用变量：{personality}, {speaking_style}, {catchphrases}, {interests}, {question}"
  }
}
```

**在插件中读取配置**：

```python
from astrbot.api import AstrBotConfig

class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config  # AstrBotConfig 继承自 Dict

        # 读取配置项
        self.default_time_range = config.get("default_time_range", "30天")
        self.batch_size = config.get("batch_size", 100)
        self.max_history_turns = config.get("max_history_turns", 20)
```

---

## 六、依赖包 (requirements.txt)

```
# 无额外依赖，使用 AstrBot 内置功能
# 如需添加第三方库，在此文件中列出
# 例如：
# requests>=2.28.0
# aiohttp>=3.8.0
```

**说明**：
- 插件目录下创建 `requirements.txt`
- 写入第三方依赖库，防止用户安装时 "Module Not Found"
- 格式遵循 [pip 官方规范](https://pip.pypa.io/en/stable/reference/requirements-file-format/)

---

## 七、开发阶段规划

### 阶段一：基础框架
- 创建插件基础结构
- 实现指令注册和解析
- 实现用户标识解析器

### 阶段二：消息收集（核心）
- 实现 OneBot11 API 调用封装
- 实现全自动分批获取机制
- 实现时间范围过滤
- 实现消息筛选和预处理

### 阶段三：画像分析
- 设计 Prompt 模板
- 实现 LLM 分析生成画像
- 实现存储机制

### 阶段四：模仿对话
- 实现基于画像的回复生成
- 实现持续唤醒机制
- 实现自动超时

### 阶段五：完善测试
- 错误处理优化
- 全流程测试

---

## 八、注意事项

1. **全自动流程**：
   - 用户只需发送一条指令，系统自动完成全部步骤
   - 无需手动查询进度或等待确认
   - 结果返回后可直接使用

2. **分批获取策略**：
   - 每批100条，批次间延迟100ms
   - 自动翻页获取更早消息
   - 时间戳自动过滤超出范围的消息
   - 原始消息上限10000条防意外

3. **数据规模**：
   - 30天活跃群可能数万条原始消息
   - 筛选单人后减少到数百条
   - 最终分析最多500条
   - 建议先用7天范围快速测试

4. **存储设计**（AstrBot规范）：
   - 代称映射：KV存储 (`put_kv_data/get_kv_data`)
   - 人物画像+对话历史：文件存储 (`plugin_data/personas/`)
   - 需 AstrBot >= 4.9.2 以使用 KV 存储

5. **AI 调用**（AstrBot规范）：
   - 使用 `llm_generate()` 直接调用
   - 排除系统 conversation_history
   - 维护人格独立的对话历史
   - 自动压缩机制：达到15轮触发压缩
   - 需 AstrBot >= 4.5.7

6. **对话历史管理**：
   - 每个人格独立存储对话历史
   - 最大保留20轮对话
   - 超过15轮自动压缩为摘要
   - 压缩保留最近5轮完整对话

7. **OneBot11 API 调用**：
   - 通过 `event.bot` 获取 client
   - 使用 `await client.api.call_action()` 调用协议端 API
   ```python
   from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

   if isinstance(event, AiocqhttpMessageEvent):
       client = event.bot
       result = await client.api.call_action(
           'get_group_msg_history',
           group_id=int(group_id),
           count=100
       )
   ```

8. **获取平台实例**：
   ```python
   # 获取所有平台实例
   platforms = self.context.platform_manager.get_insts()

   # 获取特定平台
   platform = self.context.get_platform("aiocqhttp")
   ```

9. **隐私**：
   - 只存储画像结果，不存原始消息
   - 提供删除功能清除数据

---

## 九、关键代码示例

### main.py 骨架

```python
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig
from astrbot import logger
import astrbot.api.message_components as Comp

from .core.message_collector import MessageCollector
from .core.persona_analyzer import PersonaAnalyzer
from .core.session_manager import SessionManager
from .core.prompt_generator import PromptGenerator
from .core.conversation_manager import PersonaConversationManager
from .utils.storage import PersonaStorage

class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 从配置读取参数
        self.default_time_range = config.get("default_time_range", "30天")
        self.batch_size = config.get("batch_size", 100)
        self.max_history_turns = config.get("max_history_turns", 20)
        self.compress_threshold = config.get("compress_threshold", 15)
        self.session_timeout = config.get("session_timeout_minutes", 5)

        # 初始化组件
        self.storage = PersonaStorage(self)
        self.message_collector = MessageCollector(self.batch_size)
        self.persona_analyzer = PersonaAnalyzer(context)
        self.session_manager = SessionManager(self.session_timeout)
        self.prompt_generator = PromptGenerator(config.get("custom_prompt_template", ""))
        self.conversation_manager = PersonaConversationManager(
            self.storage,
            max_turns=self.max_history_turns,
            compress_threshold=self.compress_threshold
        )

    @filter.command_group("mb", alias={"群友"})
    def mb(self):
        """群友人格克隆指令组"""
        pass

    @mb.command("分析", alias={"analyze"})
    async def analyze(self, event: AstrMessageEvent, time_range: str = "30天"):
        """一键克隆群友人格"""
        # 见上文 3.3
        pass

    @mb.command("询问", alias={"ask"})
    async def ask(self, event: AstrMessageEvent):
        """模仿群友回答"""
        # 见上文 3.4
        pass

    @mb.command("唤醒", alias={"awake"})
    async def awake(self, event: AstrMessageEvent):
        """持续唤醒模式"""
        pass

    @mb.command("休眠", alias={"sleep"})
    async def sleep(self, event: AstrMessageEvent):
        """退出唤醒模式"""
        pass

    @mb.command("画像", alias={"profile"})
    async def profile(self, event: AstrMessageEvent):
        """查看画像详情"""
        pass

    @mb.command("列表", alias={"list"})
    async def list_personas(self, event: AstrMessageEvent):
        """已克隆的群友列表"""
        pass

    @mb.command("删除", alias={"delete"})
    async def delete(self, event: AstrMessageEvent):
        """删除画像"""
        pass

    @mb.command("清空", alias={"clear"})
    async def clear_history(self, event: AstrMessageEvent):
        """清空对话历史"""
        pass

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理群消息，支持持续唤醒"""
        pass

    async def terminate(self):
        """插件卸载时清理"""
        pass
```

---

## 十、预期效果

**一键克隆流程**：
```
用户发送: /mb 分析 @张三 小张
系统自动: 分批获取 → 筛选 → 分析 → 保存
系统返回: ✅ 人格克隆完成！样本: 320条消息
```

**后续使用**：
- `/mb 询问 小张 今天天气怎么样` → 模仿回答（带历史记忆）
- `/mb 唤醒 小张` → 持续对话模式
- `/mb 画像 小张` → 查看画像详情
- `/mb 清空 小张` → 清空对话历史
- `/mb 列表` → 查看已克隆的所有群友

**对话历史管理**：
- 每次对话自动记录用户消息和回复
- 超过15轮自动压缩旧对话为摘要
- 保留最近5轮完整对话上下文

**时间范围影响**：
- 7天：约20秒完成，适合快速测试
- 30天：约1-2分钟，默认推荐
- 90天：约3-5分钟，更全面
- 全部：约5-10分钟，最完整

---

**文档版本**: v4.7
**更新内容**:
- 修正章节编号一致性
- 确保所有文件结构完整（metadata.yaml, _conf_schema.json, requirements.txt）
- 整合技术实现细节

**参考文档**:
- 新建插件: https://docs.astrbot.app/dev/star/plugin-new.html
- 简单示例: https://docs.astrbot.app/dev/star/guides/simple.html
- 指令注册: https://docs.astrbot.app/dev/star/guides/listen-message-event.html
- 配置: https://docs.astrbot.app/dev/star/guides/plugin-config.html
- 存储: https://docs.astrbot.app/dev/star/guides/storage.html
- AI调用: https://docs.astrbot.app/dev/star/guides/ai.html
- 其他: https://docs.astrbot.app/dev/star/guides/other.html

**日期**: 2026-04-10