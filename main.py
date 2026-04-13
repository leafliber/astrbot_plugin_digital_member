"""
数字群友插件 - AstrBot 插件主入口
功能：分析群友历史消息，生成说话风格和个人画像，支持模仿群友进行交流
"""
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
    """数字群友插件主类"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 从配置读取参数
        self.default_time_range = config.get("default_time_range", "30天")
        self.analyze_provider_id = config.get("analyze_provider_id", "")

        # 查询配置
        query_cfg = config.get("query", {})
        self.query_max_count = query_cfg.get("max_count", 0)
        self.fetch_context = query_cfg.get("fetch_context", False)
        self.context_before = query_cfg.get("context_before", 3)
        self.context_after = query_cfg.get("context_after", 3)

        # 分析配置
        analysis_cfg = config.get("analysis", {})
        self.batch_size = analysis_cfg.get("batch_size", 100)
        self.analysis_mode = analysis_cfg.get("mode", "batch_summarize")
        self.batch_delay_ms = analysis_cfg.get("batch_delay_ms", 1000)

        # 对话配置
        conv_cfg = config.get("conversation", {})
        self.max_history_turns = conv_cfg.get("max_history_turns", 20)
        self.compress_threshold = conv_cfg.get("compress_threshold", 15)
        self.session_timeout = conv_cfg.get("session_timeout_minutes", 5)

        # 初始化组件
        self.storage = PersonaStorage(self)
        self.message_collector = MessageCollector(
            query_max_count=self.query_max_count,
            fetch_context=self.fetch_context,
            context_before=self.context_before,
            context_after=self.context_after,
        )
        self.persona_analyzer = PersonaAnalyzer(context)
        self.session_manager = SessionManager(self.session_timeout)
        self.prompt_generator = PromptGenerator()
        self.conversation_manager = PersonaConversationManager(
            self.storage,
            context=context,
            max_turns=self.max_history_turns,
            compress_threshold=self.compress_threshold,
        )

        logger.info("[数字群友] 插件已加载")

    # ===== 指令组注册 =====

    @filter.command_group("mb", alias={"群友"})
    def mb(self):
        """群友人格克隆指令组"""
        pass

    @filter.command_group("mbb")
    def mbb(self):
        """直接和默认群友对话"""
        pass

    @mbb.command()
    async def mbb_chat(self, event: AstrMessageEvent):
        """直接和默认群友对话

        用法: /mbb 问题内容
        """
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        default = await self.storage.get_default_persona(group_id)
        if not default:
            yield event.plain_result("本群尚未设置默认数字群友\n使用 /mb 默认 @群友 设置")
            return

        target_qq = default.get("qq")
        alias = default.get("alias", target_qq)

        question = event.message_str.replace("/mbb", "").strip()
        if not question:
            yield event.plain_result(f"请输入要询问 {alias} 的问题")
            return

        persona = await self.storage.load_persona(target_qq)
        if not persona:
            yield event.plain_result(f"未找到 {alias} 的画像，请重新克隆")
            return

        history = await self.conversation_manager.get_history(target_qq)

        logger.debug(f"[数字群友] mbb询问目标: {alias} (QQ:{target_qq})")
        logger.debug(f"[数字群友] 问题: {question}")

        prompt = self.prompt_generator.generate(persona, question, history, alias)

        try:
            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)

            await self.conversation_manager.add_message(target_qq, 'user', question, provider_id=prov_id)

            llm_resp = await self.context.llm_generate(
                chat_provider_id=prov_id,
                prompt=prompt,
            )

            response = llm_resp.completion_text

            await self.conversation_manager.add_message(target_qq, 'assistant', response, provider_id=prov_id)

            yield event.plain_result(response)

        except Exception as e:
            logger.error(f"[数字群友] mbb AI调用失败: {e}")
            yield event.plain_result(f"回答生成失败: {e}")

    # ===== 分析指令（一键克隆） =====

    @mb.command("分析", alias={"analyze"})
    async def analyze(self, event: AstrMessageEvent):
        """一键克隆群友人格

        用法: /mb 分析 @群友 代称 [时间范围]
        """
        from datetime import datetime

        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        # 获取发送者 QQ 号
        sender_qq = event.message_obj.sender.user_id
        sender_qq = str(sender_qq) if sender_qq else None

        # 解析用户标识和代称
        message_chain = event.message_obj.message
        target_qq = None
        alias = None
        time_range_str = self.default_time_range

        # 从消息链解析参数
        for i, component in enumerate(message_chain):
            if isinstance(component, Comp.At):
                target_qq = str(component.qq)
                # 从后续 Plain 组件提取代称和时间范围
                if i + 1 < len(message_chain):
                    next_comp = message_chain[i + 1]
                    if isinstance(next_comp, Comp.Plain):
                        text = next_comp.text.strip()
                        parts = text.split(maxsplit=2)
                        if parts:
                            alias = parts[0]
                        if len(parts) > 1:
                            time_range_str = parts[1]
                break

        # 如果没有 @，尝试从纯文本解析 QQ 号
        if not target_qq:
            for component in message_chain:
                if isinstance(component, Comp.Plain):
                    text = component.text.strip()
                    # 跳过指令本身
                    text = text.replace("/mb 分析", "").replace("/群友 分析", "").strip()
                    parts = text.split(maxsplit=2)
                    if parts and parts[0].isdigit():
                        target_qq = parts[0]
                        if len(parts) > 1:
                            alias = parts[1]
                        if len(parts) > 2:
                            time_range_str = parts[2]
                    break

        if not target_qq:
            yield event.plain_result("请指定要克隆的群友（@群友 或 QQ号）")
            return

        if not alias:
            alias = target_qq  # 默认使用 QQ 号作为代称

        # 合规检查：克隆他人需要对方确认
        if sender_qq and target_qq != sender_qq:
            # 保存待确认请求
            await self.storage.save_pending_request(group_id, target_qq, {
                "requester_qq": sender_qq,
                "alias": alias,
                "time_range": time_range_str,
                "created_at": datetime.now().isoformat(),
            })

            yield event.plain_result(
                f"⚠️ 合规提示\n"
                f"━━━━━━━━━━━━━━━\n"
                f"克隆他人人格需要对方确认\n"
                f"请让 {alias} 发送以下指令确认：\n"
                f"/mb 确认\n"
                f"━━━━━━━━━━━━━━━\n"
                f"提示：克隆自己无需确认"
            )
            return

        # 克隆自己，直接执行
        async for result in self._execute_clone(event, target_qq, alias, time_range_str):
            yield result

    # ===== 确认指令 =====

    @mb.command("确认", alias={"confirm"})
    async def confirm(self, event: AstrMessageEvent):
        """确认被克隆请求"""
        from datetime import datetime, timedelta

        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        # 获取发送者 QQ 号
        sender_qq = event.message_obj.sender.user_id
        sender_qq = str(sender_qq) if sender_qq else None

        if not sender_qq:
            yield event.plain_result("无法获取用户信息")
            return

        # 检查是否有待确认的请求
        pending = await self.storage.get_pending_request(group_id, sender_qq)

        if not pending:
            yield event.plain_result("没有等待你确认的克隆请求")
            return

        # 检查请求是否过期（默认1小时）
        created_at = pending.get("created_at")
        if created_at:
            request_time = datetime.fromisoformat(created_at)
            if datetime.now() - request_time > timedelta(minutes=60):
                await self.storage.delete_pending_request(group_id, sender_qq)
                yield event.plain_result("克隆请求已过期（超过1小时），请重新发起")
                return

        alias = pending.get("alias", sender_qq)
        time_range_str = pending.get("time_range", self.default_time_range)
        requester_qq = pending.get("requester_qq", "未知")

        await self.storage.delete_pending_request(group_id, sender_qq)

        async for result in self._execute_clone(event, sender_qq, alias, time_range_str, requester_qq):
            yield result

    async def _execute_clone(self, event: AstrMessageEvent, target_qq: str, alias: str, time_range_str: str, requester_qq: str = None):
        """执行克隆操作（内部方法）

        Args:
            event: 消息事件
            target_qq: 被克隆者 QQ 号
            alias: 代称
            time_range_str: 时间范围
            requester_qq: 发起者 QQ 号（克隆自己时为 None 或与 target_qq 相同）
        """
        # 解析时间范围
        days = self.message_collector.parse_time_range(time_range_str)
        time_desc = "全部历史" if days is None else f"最近{days}天"

        # 获取群 ID
        group_id = event.message_obj.group_id

        yield event.plain_result(f"正在克隆 {alias} 的人格...\n时间范围: {time_desc}")

        # 使用 message_recorder 收集消息（支持上下文）
        messages = await self.message_collector.collect_messages_with_context(
            context=self.context,
            sender_id=target_qq,
            group_id=group_id,
            time_range=days,
        )

        if not messages:
            yield event.plain_result(f"未找到 {alias} 在 {time_desc} 的有效消息")
            return

        # 获取 LLM 提供商 ID
        provider_id = self.analyze_provider_id
        if not provider_id:
            # 未配置时，使用当前会话的默认提供商
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            logger.debug(f"[人格克隆] 使用默认提供商: {provider_id}")
        else:
            logger.debug(f"[人格克隆] 使用配置的提供商: {provider_id}")

        # 分析生成画像（支持分批次）
        persona = await self.persona_analyzer.analyze(
            messages,
            provider_id=provider_id,
            batch_size=self.batch_size,
            mode=self.analysis_mode,
            batch_delay_ms=self.batch_delay_ms
        )
        persona['alias'] = alias
        if requester_qq:
            persona['requester_qq'] = requester_qq
        else:
            persona['requester_qq'] = target_qq

        await self.storage.save_persona(target_qq, persona)
        await self.storage.save_alias(alias, target_qq, group_id)

        is_first = not await self.storage.has_default_persona(group_id)
        if is_first:
            await self.storage.set_default_persona(group_id, target_qq, alias)

        default_hint = f"\n✨ 已自动设为默认数字群友" if is_first else ""

        yield event.plain_result(
            f"✅ 人格克隆完成！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"代称: {alias}\n"
            f"样本: {len(messages)} 条消息\n"
            f"性格: {persona.get('personality', '未知')}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"/mb 询问 {alias} 问题 - 模仿对话\n"
            f"/mb 唤醒 {alias} - 持续对话{default_hint}"
        )

    # ===== 询问指令 =====

    @mb.command("询问", alias={"ask"})
    async def ask(self, event: AstrMessageEvent):
        """模仿群友回答问题

        用法: /mb 询问 @群友/QQ号/代称 问题内容
        """
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        # 解析用户标识和问题
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
                # 跳过指令本身
                text = text.replace("/mb 询问", "").replace("/群友 询问", "").strip()

                if not found_identifier and text:
                    parts = text.split(maxsplit=1)
                    identifier = parts[0]

                    # 尝试通过代称查找
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
            yield event.plain_result("请指定要模仿的群友（@群友、QQ号 或 代称）")
            return

        question = " ".join(question_parts)
        if not question:
            yield event.plain_result("请输入要询问的问题")
            return

        # 加载画像
        persona = await self.storage.load_persona(target_qq)
        if not persona:
            alias = await self.storage.get_alias_by_qq(target_qq, group_id) or target_qq
            yield event.plain_result(f"未找到 {alias} 的画像，请先使用 /mb 分析")
            return

        # 获取代称
        alias = persona.get('alias', target_qq)

        # 获取人格独立的对话历史
        history = await self.conversation_manager.get_history(target_qq)

        logger.debug(f"[数字群友] 询问目标: {alias} (QQ:{target_qq})")
        logger.debug(f"[数字群友] 问题: {question}")
        logger.debug(f"[数字群友] 历史轮数: {len(history)}")

        # 生成带历史的 prompt
        prompt = self.prompt_generator.generate(persona, question, history, alias)
        logger.debug(f"[数字群友] Prompt长度: {len(prompt)}")

        # 直接调用 AI，注入人格上下文
        try:
            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)
            logger.debug(f"[数字群友] 使用LLM提供商: {prov_id}")

            # 记录用户消息（传入 provider_id 用于后续压缩）
            await self.conversation_manager.add_message(target_qq, 'user', question, provider_id=prov_id)

            llm_resp = await self.context.llm_generate(
                chat_provider_id=prov_id,
                prompt=prompt,
            )

            response = llm_resp.completion_text
            logger.debug(f"[数字群友] LLM响应长度: {len(response)}")
            logger.debug(f"[数字群友] LLM响应预览: {response[:100]}...")

            # 记录回复
            await self.conversation_manager.add_message(target_qq, 'assistant', response, provider_id=prov_id)

            yield event.plain_result(response)

        except Exception as e:
            logger.error(f"[数字群友] AI调用失败: {e}")
            yield event.plain_result(f"回答生成失败: {e}")

    # ===== 唤醒指令 =====

    @mb.command("唤醒", alias={"awake", "wakeup"})
    async def awake(self, event: AstrMessageEvent):
        """进入持续唤醒模式

        用法: /mb 唤醒 @群友/QQ号/代称
        """
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        # 解析目标群友
        message_chain = event.message_obj.message
        target_qq = None
        alias = None

        for component in message_chain:
            if isinstance(component, Comp.At):
                target_qq = str(component.qq)
            elif isinstance(component, Comp.Plain):
                text = component.text.strip()
                text = text.replace("/mb 唤醒", "").replace("/群友 唤醒", "").strip()
                if text:
                    # 尝试通过代称查找
                    qq = await self.storage.get_qq_by_alias(text, group_id)
                    if qq:
                        target_qq = qq
                        alias = text
                    elif text.isdigit():
                        target_qq = text

        if not target_qq:
            yield event.plain_result("请指定要唤醒的群友")
            return

        # 检查画像是否存在
        persona = await self.storage.load_persona(target_qq)
        if not persona:
            if not alias:
                alias = await self.storage.get_alias_by_qq(target_qq, group_id) or target_qq
            yield event.plain_result(f"未找到 {alias} 的画像，请先使用 /mb 分析")
            return

        if not alias:
            alias = await self.storage.get_alias_by_qq(target_qq, group_id) or persona.get('alias', target_qq)

        await self.session_manager.activate(group_id, target_qq, alias)

        yield event.plain_result(
            f"✅ 已唤醒 {alias}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• @{alias} 或消息包含\"{alias}\"才会回复\n"
            f"• 超时 {self.session_timeout} 分钟自动休眠\n"
            f"• 使用 /mb 休眠 手动结束"
        )

    # ===== 休眠指令 =====

    @mb.command("休眠", alias={"sleep"})
    async def sleep(self, event: AstrMessageEvent):
        """退出持续唤醒模式"""
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        result = await self.session_manager.deactivate(group_id)

        if result:
            qq, alias = result
            yield event.plain_result(f"{alias} 已休眠，不再自动回复")
        else:
            yield event.plain_result("当前没有活跃的唤醒状态")

    # ===== 画像指令 =====

    @mb.command("画像", alias={"profile"})
    async def profile(self, event: AstrMessageEvent):
        """查看群友画像详情"""
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        # 解析目标群友
        target_qq = await self._parse_target(event, group_id)

        if not target_qq:
            yield event.plain_result("请指定要查看的群友")
            return

        persona = await self.storage.load_persona(target_qq)
        if not persona:
            alias = await self.storage.get_alias_by_qq(target_qq, group_id) or target_qq
            yield event.plain_result(f"未找到 {alias} 的画像")
            return

        alias = persona.get('alias', target_qq)

        # 格式化画像信息
        info = f"""【{alias} 的画像】
━━━━━━━━━━━━━━━
性格: {persona.get('personality', '未知')}
风格: {persona.get('speaking_style', '普通')}
口头禅: {', '.join(persona.get('catchphrases', [])) or '无'}
兴趣: {', '.join(persona.get('interests', [])) or '无'}
表情习惯: {persona.get('emoji_usage', '无')}
━━━━━━━━━━━━━━━
样本消息: {persona.get('message_count', 0)} 条
创建时间: {persona.get('created_at', '未知')}"""

        # 添加对话历史信息
        history_info = await self.conversation_manager.get_history_summary(target_qq)
        info += f"\n对话历史: {history_info}"

        yield event.plain_result(info)

    # ===== 列表指令 =====

    @mb.command("列表", alias={"list"})
    async def list_personas(self, event: AstrMessageEvent):
        """已克隆的群友列表"""
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        personas = await self.storage.list_personas_by_group(group_id)

        if not personas:
            yield event.plain_result("本群还没有克隆任何群友\n使用 /mb 分析 @群友 代称 开始克隆")
            return

        lines = ["【本群已克隆的群友】", "━━━━━━━━━━━━━━━"]
        for p in personas:
            lines.append(f"{p['alias']} ({p['qq']})")
            lines.append(f"  性格: {p['personality']}, 样本: {p['message_count']}条")

        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"共 {len(personas)} 个")

        yield event.plain_result("\n".join(lines))

    @mb.command("默认", alias={"default"})
    async def set_default(self, event: AstrMessageEvent):
        """设置本群的默认数字群友

        用法: /mb 默认 @群友/QQ号/代称
        不带参数时显示当前默认群友
        """
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        target_qq = await self._parse_target(event, group_id)

        if not target_qq:
            default = await self.storage.get_default_persona(group_id)
            if default:
                qq = default.get("qq")
                alias = default.get("alias", qq)
                yield event.plain_result(f"当前默认数字群友: {alias} ({qq})")
            else:
                yield event.plain_result("本群尚未设置默认数字群友\n使用 /mb 默认 @群友 设置")
            return

        persona = await self.storage.load_persona(target_qq)
        if not persona:
            alias = await self.storage.get_alias_by_qq(target_qq, group_id) or target_qq
            yield event.plain_result(f"未找到 {alias} 的画像，请先使用 /mb 分析")
            return

        alias = persona.get('alias', target_qq)
        await self.storage.set_default_persona(group_id, target_qq, alias)

        yield event.plain_result(f"✅ 已设置 {alias} 为本群的默认数字群友\n使用 /mbb 可直接与其对话")

    # ===== 删除指令 =====

    @mb.command("删除", alias={"delete", "del"})
    async def delete(self, event: AstrMessageEvent):
        """删除群友画像

        权限要求：
        - Bot 管理员
        - 被克隆本人
        - 发起该克隆的人
        """
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        # 获取发送者 QQ 号
        sender_qq = event.message_obj.sender.user_id
        sender_qq = str(sender_qq) if sender_qq else None

        target_qq = await self._parse_target(event, group_id)

        if not target_qq:
            yield event.plain_result("请指定要删除的群友")
            return

        # 检查画像是否存在
        persona = await self.storage.load_persona(target_qq)
        if not persona:
            alias = await self.storage.get_alias_by_qq(target_qq, group_id) or target_qq
            yield event.plain_result(f"未找到 {alias} 的画像")
            return

        alias = persona.get('alias', target_qq)

        # 权限检查
        is_authorized = False

        # 1. 检查是否是被克隆本人（优先检查，最直接）
        if sender_qq and sender_qq == target_qq:
            is_authorized = True

        # 2. 检查是否是发起克隆的人
        requester_qq = persona.get('requester_qq')
        if requester_qq and sender_qq == str(requester_qq):
            is_authorized = True

        # 3. 检查是否是 Bot 管理员
        # 注意：管理员检查放在最后，因为前两个条件已足够时无需额外检查
        if not is_authorized:
            try:
                # 尝试多种方式获取管理员列表（AstrBot 使用 admins_id 字段）
                admin_ids = []

                # 方式1: 通过 context.astrbot_config 获取
                if hasattr(self.context, 'astrbot_config'):
                    cfg = self.context.astrbot_config
                    admins = cfg.get("admins_id", [])
                    if isinstance(admins, list):
                        admin_ids.extend(admins)

                # 方式2: 通过 context._config 获取
                if not admin_ids and hasattr(self.context, '_config'):
                    cfg = self.context._config
                    admins = cfg.get("admins_id", [])
                    if isinstance(admins, list):
                        admin_ids.extend(admins)

                # 检查发送者是否在管理员列表中
                if sender_qq in [str(a) for a in admin_ids]:
                    is_authorized = True
                    logger.info(f"[数字群友] 用户 {sender_qq} 是管理员，允许删除")

            except Exception as e:
                logger.warning(f"[数字群友] 获取管理员列表失败: {e}，跳过管理员权限检查")

        if not is_authorized:
            yield event.plain_result(
                f"⚠️ 权限不足\n"
                f"━━━━━━━━━━━━━━━\n"
                f"只有以下人员可以删除 {alias} 的画像：\n"
                f"• Bot 管理员\n"
                f"• {alias} 本人\n"
                f"• 发起克隆的人"
            )
            return

        await self.storage.delete_persona(target_qq)
        await self.storage.delete_alias(alias, group_id)

        default = await self.storage.get_default_persona(group_id)
        if default and default.get("qq") == target_qq:
            await self.storage.clear_default_persona(group_id)

        if self.session_manager.is_active(group_id):
            active_qq, _ = self.session_manager.get_active(group_id)
            if active_qq == target_qq:
                await self.session_manager.deactivate(group_id)

        yield event.plain_result(f"已删除 {alias} 的画像和代称")

    # ===== 清空指令 =====

    @mb.command("清空", alias={"clear"})
    async def clear_history(self, event: AstrMessageEvent):
        """清空对话历史"""
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result("此功能仅在群聊中可用")
            return

        target_qq = await self._parse_target(event, group_id)

        if not target_qq:
            yield event.plain_result("请指定要清空历史的群友")
            return

        persona = await self.storage.load_persona(target_qq)
        if not persona:
            alias = await self.storage.get_alias_by_qq(target_qq, group_id) or target_qq
            yield event.plain_result(f"未找到 {alias} 的画像")
            return

        alias = persona.get('alias', target_qq)
        await self.conversation_manager.clear_history(target_qq)

        yield event.plain_result(f"已清空 {alias} 的对话历史")

    # ===== 群消息监听（持续唤醒） =====

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理群消息，支持持续唤醒模式"""
        group_id = event.message_obj.group_id

        session = self.session_manager.get_active(group_id)
        if not session:
            return

        message_text = event.message_str
        if message_text.startswith("/mb") or message_text.startswith("/群友") or message_text.startswith("/mbb"):
            return

        qq, alias = session

        self.session_manager.update_activity(group_id)

        persona = await self.storage.load_persona(qq)
        if not persona:
            return

        alias = persona.get('alias', alias)

        message_chain = event.message_obj.message
        should_respond = False
        is_at_target = False

        for component in message_chain:
            if isinstance(component, Comp.At):
                if str(component.qq) == qq:
                    should_respond = True
                    is_at_target = True
                    break

        if not should_respond:
            if alias in message_text:
                should_respond = True

        if not should_respond:
            return

        history = await self.conversation_manager.get_history(qq)

        logger.debug(f"[数字群友] 唤醒模式响应: {alias} (QQ:{qq})")
        logger.debug(f"[数字群友] 收到消息: {event.message_str}")

        prompt = self.prompt_generator.generate(persona, event.message_str, history, alias)
        logger.debug(f"[数字群友] Prompt长度: {len(prompt)}")

        try:
            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)
            logger.debug(f"[数字群友] 唤醒模式使用LLM提供商: {prov_id}")

            await self.conversation_manager.add_message(qq, 'user', event.message_str, provider_id=prov_id)

            llm_resp = await self.context.llm_generate(
                chat_provider_id=prov_id,
                prompt=prompt,
            )

            response = llm_resp.completion_text
            logger.debug(f"[数字群友] 唤醒模式响应长度: {len(response)}")
            logger.debug(f"[数字群友] 唤醒模式响应预览: {response[:100]}...")

            await self.conversation_manager.add_message(qq, 'assistant', response, provider_id=prov_id)

            yield event.plain_result(response)

        except Exception as e:
            logger.error(f"[数字群友] 持续唤醒回复失败: {e}")

    # ===== 辅助方法 =====

    async def _parse_target(self, event: AstrMessageEvent, group_id: str) -> str | None:
        """解析消息链中的目标用户标识

        Args:
            event: 消息事件
            group_id: 群号

        Returns:
            QQ号，如果无法解析则返回 None
        """
        message_chain = event.message_obj.message

        for component in message_chain:
            if isinstance(component, Comp.At):
                return str(component.qq)
            elif isinstance(component, Comp.Plain):
                text = component.text.strip()
                # 获取指令后的第一个参数
                parts = text.split()
                for part in parts:
                    if part in ["分析", "询问", "唤醒", "休眠", "画像", "删除", "清空", "列表", "确认", "默认", "analyze", "ask", "awake", "sleep", "profile", "delete", "clear", "list", "confirm", "default"]:
                        continue
                    qq = await self.storage.get_qq_by_alias(part, group_id)
                    if qq:
                        return qq
                    if part.isdigit():
                        return part

        return None

    async def terminate(self):
        """插件卸载时清理"""
        # 取消所有活跃会话
        for group_id in self.session_manager.get_active_groups():
            await self.session_manager.deactivate(group_id)

        logger.info("[数字群友] 插件已卸载")