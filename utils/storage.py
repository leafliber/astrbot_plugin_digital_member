"""
存储工具 - KV存储 + 文件存储
遵循 AstrBot 官方规范：https://docs.astrbot.app/dev/star/guides/storage.html
"""
import json
from datetime import datetime
from pathlib import Path
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.api.star import Star
from astrbot import logger


class PersonaStorage:
    """画像存储管理器 - KV存储（代称映射）+ 文件存储（画像数据）"""

    def __init__(self, star_instance: Star):
        # 使用插件实例获取存储能力
        self.star = star_instance
        # 大文件存储路径
        self.data_path = Path(get_astrbot_data_path()) / "plugin_data" / star_instance.name / "personas"
        self.data_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[存储] 画像数据路径: {self.data_path}")

    # ===== KV 存储：代称映射（轻量数据） =====

    async def save_alias(self, alias: str, qq: str, group_id: str):
        """保存代称映射 - 使用 KV 存储

        Args:
            alias: 用户代称
            qq: 用户 QQ 号
            group_id: 群号
        """
        key = f"alias_{group_id}"
        aliases = await self.star.get_kv_data(key, {})
        aliases[alias] = qq
        await self.star.put_kv_data(key, aliases)
        logger.info(f"[存储] 已保存代称映射: {alias} -> {qq} (群 {group_id})")

    async def get_qq_by_alias(self, alias: str, group_id: str) -> str | None:
        """通过代称查找 QQ 号 - 使用 KV 存储

        Args:
            alias: 用户代称
            group_id: 群号

        Returns:
            QQ号，如果不存在则返回 None
        """
        key = f"alias_{group_id}"
        aliases = await self.star.get_kv_data(key, {})
        return aliases.get(alias)

    async def get_alias_by_qq(self, qq: str, group_id: str) -> str | None:
        """通过 QQ 号查找代称

        Args:
            qq: 用户 QQ 号
            group_id: 群号

        Returns:
            代称，如果不存在则返回 None
        """
        key = f"alias_{group_id}"
        aliases = await self.star.get_kv_data(key, {})
        for alias, saved_qq in aliases.items():
            if saved_qq == qq:
                return alias
        return None

    async def list_aliases(self, group_id: str) -> dict:
        """获取群内所有代称映射

        Args:
            group_id: 群号

        Returns:
            代称映射字典 {alias: qq}
        """
        key = f"alias_{group_id}"
        return await self.star.get_kv_data(key, {})

    async def delete_alias(self, alias: str, group_id: str):
        """删除代称映射

        Args:
            alias: 用户代称
            group_id: 群号
        """
        key = f"alias_{group_id}"
        aliases = await self.star.get_kv_data(key, {})
        if alias in aliases:
            del aliases[alias]
            await self.star.put_kv_data(key, aliases)
            logger.info(f"[存储] 已删除代称映射: {alias} (群 {group_id})")

    # ===== 文件存储：人物画像（大数据） =====

    async def save_persona(self, qq: str, group_id: str, data: dict):
        """保存人物画像 - 使用文件存储

        Args:
            qq: 用户 QQ 号
            group_id: 群号
            data: 人格画像数据
        """
        file_path = self.data_path / f"{group_id}_{qq}.json"
        data['qq'] = qq
        data['group_id'] = group_id
        data['updated_at'] = datetime.now().isoformat()
        if not data.get('created_at'):
            data['created_at'] = datetime.now().isoformat()

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"[存储] 已保存画像: 群{group_id} QQ{qq}")

    async def load_persona(self, qq: str, group_id: str) -> dict | None:
        """加载人物画像

        Args:
            qq: 用户 QQ 号
            group_id: 群号

        Returns:
            人格画像字典，如果不存在则返回 None
        """
        file_path = self.data_path / f"{group_id}_{qq}.json"
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"[存储] 画像文件解析失败: 群{group_id} QQ{qq}, {e}")
                return None
        return None

    async def delete_persona(self, qq: str, group_id: str):
        """删除人物画像

        Args:
            qq: 用户 QQ 号
            group_id: 群号
        """
        file_path = self.data_path / f"{group_id}_{qq}.json"
        if file_path.exists():
            file_path.unlink()
            logger.info(f"[存储] 已删除画像: 群{group_id} QQ{qq}")

    async def persona_exists(self, qq: str, group_id: str) -> bool:
        """检查画像是否存在

        Args:
            qq: 用户 QQ 号
            group_id: 群号

        Returns:
            是否存在
        """
        file_path = self.data_path / f"{group_id}_{qq}.json"
        return file_path.exists()

    async def list_personas(self, group_id: str = None) -> list:
        """列出画像

        Args:
            group_id: 群号，为 None 时列出所有画像

        Returns:
            画像列表，每项包含 qq、group_id、alias、created_at、message_count
        """
        personas = []
        for file in self.data_path.glob("*.json"):
            try:
                filename = file.stem
                parts = filename.split("_", 1)
                if len(parts) != 2:
                    continue
                file_group_id, qq = parts

                if group_id and file_group_id != group_id:
                    continue

                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    personas.append({
                        "qq": qq,
                        "group_id": file_group_id,
                        "alias": data.get("alias", qq),
                        "created_at": data.get("created_at", ""),
                        "message_count": data.get("message_count", 0),
                        "personality": data.get("personality", "未知"),
                    })
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"[存储] 跳过损坏的画像文件: {file.name}")

        personas.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return personas

    async def list_personas_by_group(self, group_id: str) -> list:
        """列出群内的所有画像

        Args:
            group_id: 群号

        Returns:
            画像列表
        """
        aliases = await self.list_aliases(group_id)
        personas = []

        for alias, qq in aliases.items():
            persona = await self.load_persona(qq, group_id)
            if persona:
                personas.append({
                    "qq": qq,
                    "alias": alias,
                    "personality": persona.get("personality", "未知"),
                    "message_count": persona.get("message_count", 0),
                })

        return personas

    # ===== KV 存储：待确认的克隆请求 =====

    async def save_pending_request(self, group_id: str, target_qq: str, request_data: dict):
        """保存待确认的克隆请求

        Args:
            group_id: 群号
            target_qq: 目标用户 QQ 号
            request_data: 请求数据 {requester_qq, alias, time_range, created_at}
        """
        key = f"pending_{group_id}_{target_qq}"
        await self.star.put_kv_data(key, request_data)
        logger.info(f"[存储] 已保存待确认请求: 群{group_id} 目标{target_qq}")

    async def get_pending_request(self, group_id: str, target_qq: str) -> dict | None:
        """获取待确认的克隆请求

        Args:
            group_id: 群号
            target_qq: 目标用户 QQ 号

        Returns:
            请求数据，如果不存在则返回 None
        """
        key = f"pending_{group_id}_{target_qq}"
        return await self.star.get_kv_data(key, None)

    async def delete_pending_request(self, group_id: str, target_qq: str):
        """删除待确认的克隆请求

        Args:
            group_id: 群号
            target_qq: 目标用户 QQ 号
        """
        key = f"pending_{group_id}_{target_qq}"
        await self.star.put_kv_data(key, None)
        logger.info(f"[存储] 已删除待确认请求: 群{group_id} 目标{target_qq}")

    async def set_default_persona(self, group_id: str, qq: str, alias: str):
        """设置群的默认数字群友

        Args:
            group_id: 群号
            qq: 用户 QQ 号
            alias: 用户代称
        """
        key = f"default_persona_{group_id}"
        await self.star.put_kv_data(key, {"qq": qq, "alias": alias})
        logger.info(f"[存储] 已设置群 {group_id} 的默认数字群友: {alias}({qq})")

    async def get_default_persona(self, group_id: str) -> dict | None:
        """获取群的默认数字群友

        Args:
            group_id: 群号

        Returns:
            默认群友信息 {"qq": str, "alias": str}，如果不存在则返回 None
        """
        key = f"default_persona_{group_id}"
        return await self.star.get_kv_data(key, None)

    async def has_default_persona(self, group_id: str) -> bool:
        """检查群是否已设置默认数字群友

        Args:
            group_id: 群号

        Returns:
            是否已设置
        """
        return await self.get_default_persona(group_id) is not None

    async def clear_default_persona(self, group_id: str):
        """清除群的默认数字群友

        Args:
            group_id: 群号
        """
        key = f"default_persona_{group_id}"
        await self.star.put_kv_data(key, None)
        logger.info(f"[存储] 已清除群 {group_id} 的默认数字群友")