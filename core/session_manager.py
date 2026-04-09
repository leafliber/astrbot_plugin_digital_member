"""
会话管理器 - 持续唤醒状态管理
"""
import asyncio
from datetime import datetime, timedelta
from astrbot import logger


class SessionManager:
    """会话管理器 - 持续唤醒状态管理"""

    def __init__(self, timeout_minutes: int = 5):
        self.active_sessions = {}
        self.timeout = timedelta(minutes=timeout_minutes)

    async def activate(self, group_id: str, qq: str, alias: str):
        """激活持续唤醒

        Args:
            group_id: 群号
            qq: 用户 QQ 号
            alias: 用户代称
        """
        # 如果已有活跃会话，先取消旧的
        if group_id in self.active_sessions:
            old_session = self.active_sessions[group_id]
            if old_session.get("task"):
                old_session["task"].cancel()

        # 创建新的会话
        self.active_sessions[group_id] = {
            "qq": qq,
            "alias": alias,
            "last_active": datetime.now(),
            "task": asyncio.create_task(self._timeout_check(group_id))
        }

        logger.info(f"[会话管理] 群 {group_id} 已激活 {alias}({qq}) 的持续唤醒模式")

    async def deactivate(self, group_id: str) -> tuple[str, str] | None:
        """结束持续唤醒

        Args:
            group_id: 群号

        Returns:
            之前的会话信息 (qq, alias)，如果存在
        """
        if group_id in self.active_sessions:
            session = self.active_sessions[group_id]
            qq = session.get("qq")
            alias = session.get("alias")

            if session.get("task"):
                session["task"].cancel()

            del self.active_sessions[group_id]
            logger.info(f"[会话管理] 群 {group_id} 已结束 {alias}({qq}) 的持续唤醒模式")

            return qq, alias

        return None

    def get_active(self, group_id: str) -> tuple[str, str] | None:
        """获取当前激活的群友

        Args:
            group_id: 群号

        Returns:
            (qq, alias) 如果有活跃会话，否则 None
        """
        session = self.active_sessions.get(group_id)
        if session:
            return session["qq"], session["alias"]
        return None

    def is_active(self, group_id: str) -> bool:
        """检查是否有活跃会话

        Args:
            group_id: 群号

        Returns:
            是否有活跃会话
        """
        return group_id in self.active_sessions

    def update_activity(self, group_id: str):
        """更新活跃时间

        Args:
            group_id: 群号
        """
        if group_id in self.active_sessions:
            self.active_sessions[group_id]["last_active"] = datetime.now()

    def get_active_groups(self) -> list:
        """获取所有活跃的群号列表

        Returns:
            活跃群号列表
        """
        return list(self.active_sessions.keys())

    async def _timeout_check(self, group_id: str):
        """超时自动休眠

        Args:
            group_id: 群号
        """
        try:
            while True:
                await asyncio.sleep(60)  # 每分钟检查一次
                session = self.active_sessions.get(group_id)
                if session:
                    elapsed = datetime.now() - session["last_active"]
                    if elapsed > self.timeout:
                        logger.info(f"[会话管理] 群 {group_id} 超时自动休眠")
                        await self.deactivate(group_id)
                        break
                else:
                    break
        except asyncio.CancelledError:
            # 正常取消，不需要处理
            pass
        except Exception as e:
            logger.error(f"[会话管理] 超时检查异常: {e}")