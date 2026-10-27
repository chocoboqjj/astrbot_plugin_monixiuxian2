# handlers/storage_ring_handler.py

from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import Plain
from ..data import DataBase
from ..core import StorageRingManager
from ..config_manager import ConfigManager
from ..models import Player
from .utils import (
    player_required, extract_target_id, looks_like_user_id, strip_target_from_text,
    parse_counted_args, parse_name_and_count,
)

CMD_STORAGE_RING = "储物戒"
CMD_STORE_ITEM = "存入"
CMD_RETRIEVE_ITEM = "取出"
CMD_UPGRADE_RING = "更换储物戒"
CMD_DISCARD_ITEM = "丢弃"
CMD_GIFT_ITEM = "赠予"
CMD_ACCEPT_GIFT = "接收"
CMD_REJECT_GIFT = "拒绝"
CMD_STORE_ALL = "存入所有"
CMD_RETRIEVE_ALL = "取出所有"
CMD_SEARCH_ITEM = "搜索物品"
CMD_VIEW_CATEGORY = "查看分类"
CMD_RECYCLE_ITEM = "回收"

# 回收折算比例：按物品售价折算为灵石（低于 1 按 1 计）
RECYCLE_RATE = 0.5

# 物品分类定义
ITEM_CATEGORIES = {
    "材料": ["灵草", "精铁", "星辰石", "灵石碎片", "灵兽毛皮", "灵兽内丹",
             "妖兽精血", "功法残页", "秘境精华", "天材地宝", "混沌精华", "神兽之骨",
             "远古秘籍", "仙器碎片", "紫金沙"],
    "装备": ["武器", "防具", "法器"],
    "功法": ["心法", "技能"],
    "其他": []
}

__all__ = ["StorageRingHandler"]


class StorageRingHandler:
    """储物戒系统处理器"""

    def __init__(self, db: DataBase, config_manager: ConfigManager):
        self.db = db
        self.config_manager = config_manager
        self.storage_ring_manager = StorageRingManager(db, config_manager)

    @player_required
    async def handle_storage_ring(self, player: Player, event: AstrMessageEvent):
        """显示储物戒信息"""
        display_name = event.get_sender_name()

        # 获取储物戒信息
        ring_info = self.storage_ring_manager.get_storage_ring_info(player)

        lines = [
            f"=== {display_name} 的储物戒 ===\n",
            f"【{ring_info['name']}】（{ring_info['rank']}）\n",
            f"{ring_info['description']}\n",
            f"\n容量：{ring_info['used']}/{ring_info['capacity']}格\n",
            f"━━━━━━━━━━━━━━━\n",
        ]

        # 按分类显示存储的物品
        items = ring_info['items']
        if items:
            categorized = self._categorize_items(items)
            for category, cat_items in categorized.items():
                if cat_items:
                    lines.append(f"【{category}】\n")
                    for item_name, count in cat_items:
                        if count > 1:
                            lines.append(f"  · {item_name}×{count}\n")
                        else:
                            lines.append(f"  · {item_name}\n")
        else:
            lines.append("【存储物品】空\n")

        # 空间警告
        warning = self.storage_ring_manager.get_space_warning(player)
        if warning:
            lines.append(f"\n{warning}\n")

        lines.append(f"\n{'=' * 28}\n")
        lines.append(f"存入：{CMD_STORE_ITEM} 物品名 [数量]\n")
        lines.append(f"取出：{CMD_RETRIEVE_ITEM} 物品名 [数量]\n")
        lines.append(f"搜索：{CMD_SEARCH_ITEM} 关键词\n")
        lines.append(f"升级：{CMD_UPGRADE_RING} 储物戒名")

        yield event.plain_result("".join(lines))

    @player_required
    async def handle_store_item(self, player: Player, event: AstrMessageEvent, args: str):
        """存入物品到储物戒 - 已禁用手动存入"""
        yield event.plain_result(
            "📦 储物戒说明：\n"
            "物品会在以下情况自动存入储物戒：\n"
            "  · 商店购买物品\n"
            "  · 历练/秘境获得物品\n"
            "  · Boss击杀掉落\n"
            "  · 悬赏任务奖励\n"
            "  · 卸下装备\n"
            "\n⚠️ 不支持手动存入物品"
        )

    @player_required
    async def handle_retrieve_item(self, player: Player, event: AstrMessageEvent, args: str):
        """从储物戒取出物品"""
        if not args or args.strip() == "":
            yield event.plain_result(
                f"请指定要取出的物品\n"
                f"用法：{CMD_RETRIEVE_ITEM} 物品名 [数量]\n"
                f"示例：{CMD_RETRIEVE_ITEM} 精铁 5"
            )
            return

        args = args.strip()
        parts = args.rsplit(" ", 1)

        # 解析物品名和数量
        if len(parts) == 2 and parts[1].isdigit():
            item_name = parts[0]
            count = int(parts[1])
        else:
            item_name = args
            count = 1

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 取出物品
        success, message = await self.storage_ring_manager.retrieve_item(player, item_name, count)

        if success:
            yield event.plain_result(f"✅ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    @player_required
    async def handle_discard_item(self, player: Player, event: AstrMessageEvent, args: str):
        """丢弃储物戒中的物品"""
        if not args or args.strip() == "":
            yield event.plain_result(
                f"请指定要丢弃的物品\n"
                f"用法：{CMD_DISCARD_ITEM} 物品名 [数量]\n"
                f"示例：{CMD_DISCARD_ITEM} 精铁 5\n"
                f"⚠️ 丢弃的物品将永久销毁！"
            )
            return

        args = args.strip()
        parts = args.rsplit(" ", 1)

        # 解析物品名和数量
        if len(parts) == 2 and parts[1].isdigit():
            item_name = parts[0]
            count = int(parts[1])
        else:
            item_name = args
            count = 1

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 丢弃物品
        success, message = await self.storage_ring_manager.discard_item(player, item_name, count)

        if success:
            yield event.plain_result(f"🗑️ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    # ===== 赠予：丹药与普通物品走不同的背包 =====
    # 丹药存「丹药背包」(pills_inventory)，且储物戒明确禁止存丹药
    # ⇒ 赠予丹药必须走丹药背包，否则必然失败（此前即为此问题）。

    def _is_pill(self, item_name: str) -> bool:
        """判断物品是否为丹药（统一走 ConfigManager.is_pill）"""
        try:
            return bool(self.config_manager.is_pill(item_name))
        except Exception:
            return False

    async def _take_for_gift(self, player: Player, item_name: str, count: int):
        """从赠予者身上取走物品（丹药走丹药背包，其他走储物戒）。

        Returns:
            (是否成功, 提示文案)
        """
        if self._is_pill(item_name):
            inventory = player.get_pills_inventory()
            current = inventory.get(item_name, 0)
            if current <= 0:
                return False, f"丹药背包中没有【{item_name}】"
            if current < count:
                return False, f"丹药背包中【{item_name}】数量不足（当前：{current}个）"
            inventory[item_name] -= count
            if inventory[item_name] <= 0:
                del inventory[item_name]
            player.set_pills_inventory(inventory)
            await self.db.update_player(player)
            return True, ""

        success, msg = await self.storage_ring_manager.retrieve_item(player, item_name, count)
        if not success:
            return False, msg
        return True, ""

    async def _give_to_player(self, player: Player, item_name: str, count: int):
        """把物品放入接收者身上（丹药走丹药背包，其他走储物戒）。

        Returns:
            (是否成功, 提示文案)
        """
        if self._is_pill(item_name):
            inventory = player.get_pills_inventory()
            inventory[item_name] = inventory.get(item_name, 0) + count
            player.set_pills_inventory(inventory)
            await self.db.update_player(player)
            return True, ""

        return await self.storage_ring_manager.store_item(player, item_name, count)

    @player_required
    async def handle_gift_item(self, player: Player, event: AstrMessageEvent, args: str):
        """赠予物品给其他玩家"""
        target_id = None
        item_name = None
        count = 1

        # 从消息链中提取 Plain 文本
        text_parts = []
        message_chain = event.message_obj.message if hasattr(event, 'message_obj') and event.message_obj else []
        
        for comp in message_chain:
            if isinstance(comp, Plain):
                text_parts.append(comp.text)

        # 合并文本内容并移除命令前缀
        text_content = "".join(text_parts).strip()
        for prefix in ["#赠予", "/赠予", "赠予"]:
            if text_content.startswith(prefix):
                text_content = text_content[len(prefix):].strip()
                break

        # 目标玩家：统一走 extract_target_id
        # （OneBot 用消息链 At 组件；QQ 官方机器人用纯文本里的 <@!member_openid> 标记，
        #  此时消息链里的 At 只代表"机器人自己"，不能作为目标）
        target_id = extract_target_id(event, "")

        # 没有 @ 标记时，兼容手填 ID / openid（取文本首个 token）
        if not target_id and text_content:
            head, _, rest = text_content.partition(" ")
            if looks_like_user_id(head):
                target_id = head
                text_content = rest.strip()

        # 剔除 @ 标记与目标 ID，避免污染物品名解析
        if target_id:
            text_content = strip_target_from_text(text_content, target_id).strip()

        # 解析物品名和数量（支持「丹药 3」与「丹药x3」两种写法）
        if text_content:
            item_name, count = parse_name_and_count(text_content, 1)

        # 验证必要参数
        if not target_id:
            yield event.plain_result(
                f"请指定赠予对象\n"
                f"用法：{CMD_GIFT_ITEM} @某人 物品名 [数量]\n"
                f"或：{CMD_GIFT_ITEM} 用户ID 物品名 [数量]\n"
                f"提示：QQ 官方机器人下请直接 @对方，或填写其 openid"
            )
            return

        if not item_name:
            yield event.plain_result("请指定要赠予的物品名称")
            return

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 检查物品是否在身上（丹药在丹药背包，其他在储物戒）
        is_pill = self._is_pill(item_name)
        if is_pill:
            current = player.get_pills_inventory().get(item_name, 0)
            if current <= 0:
                yield event.plain_result(f"丹药背包中没有【{item_name}】")
                return
            if current < count:
                yield event.plain_result(f"丹药背包中【{item_name}】数量不足（当前：{current}个）")
                return
        else:
            if not self.storage_ring_manager.has_item(player, item_name, count):
                current = self.storage_ring_manager.get_item_count(player, item_name)
                if current == 0:
                    yield event.plain_result(f"储物戒中没有【{item_name}】")
                else:
                    yield event.plain_result(f"储物戒中【{item_name}】数量不足（当前：{current}个）")
                return

        target_player = await self.db.get_player_by_id(target_id)
        if not target_player:
            yield event.plain_result(f"目标玩家（ID:{target_id}）尚未开始修仙")
            return

        if target_id == player.user_id:
            yield event.plain_result("不能赠予物品给自己")
            return

        # 先从背包取出物品（丹药走丹药背包，其他走储物戒）
        success, err_msg = await self._take_for_gift(player, item_name, count)
        if not success:
            yield event.plain_result(f"赠予失败：{err_msg}")
            return

        # 存储待处理的赠予请求到数据库
        sender_name = event.get_sender_name()
        await self.db.ext.create_pending_gift(
            receiver_id=target_id,
            sender_id=player.user_id,
            sender_name=sender_name,
            item_name=item_name,
            count=count,
            expires_hours=24  # 24小时后过期
        )

        yield event.plain_result(
            f"📦 赠予请求已发送！\n"
            f"【{item_name}】x{count} → @{target_id}\n"
            f"等待对方确认...（24小时内有效）\n"
            f"对方可使用 {CMD_ACCEPT_GIFT} 接收或 {CMD_REJECT_GIFT} 拒绝"
        )

    @player_required
    async def handle_accept_gift(self, player: Player, event: AstrMessageEvent):
        """接收赠予的物品"""
        user_id = player.user_id

        # 从数据库获取待处理的赠予请求
        gift = await self.db.ext.get_pending_gift(user_id)
        if not gift:
            yield event.plain_result("你没有待接收的赠予物品")
            return

        item_name = gift["item_name"]
        count = gift["count"]
        sender_name = gift["sender_name"]
        gift_id = gift["id"]

        # 尝试存入接收者的背包（丹药进丹药背包，其他进储物戒）
        success, message = await self._give_to_player(player, item_name, count)

        if success:
            # 删除数据库中的赠予请求
            await self.db.ext.delete_pending_gift(gift_id)
            where = "丹药背包" if self._is_pill(item_name) else "储物戒"
            yield event.plain_result(
                f"✅ 已接收来自【{sender_name}】的赠予！\n"
                f"获得：【{item_name}】x{count}（已放入{where}）"
            )
        else:
            # 存入失败，物品返还给发送者
            sender_id = gift["sender_id"]
            sender_player = await self.db.get_player_by_id(sender_id)
            if sender_player:
                await self._give_to_player(sender_player, item_name, count)

            # 删除数据库中的赠予请求
            await self.db.ext.delete_pending_gift(gift_id)
            yield event.plain_result(
                f"❌ 接收失败：{message}\n"
                f"物品已返还给【{sender_name}】"
            )

    @player_required
    async def handle_reject_gift(self, player: Player, event: AstrMessageEvent):
        """拒绝赠予的物品"""
        user_id = player.user_id

        # 从数据库获取待处理的赠予请求
        gift = await self.db.ext.get_pending_gift(user_id)
        if not gift:
            yield event.plain_result("你没有待处理的赠予请求")
            return

        item_name = gift["item_name"]
        count = gift["count"]
        sender_id = gift["sender_id"]
        sender_name = gift["sender_name"]
        gift_id = gift["id"]

        # 物品返还给发送者
        sender_player = await self.db.get_player_by_id(sender_id)
        if sender_player:
            await self._give_to_player(sender_player, item_name, count)

        # 删除数据库中的赠予请求
        await self.db.ext.delete_pending_gift(gift_id)
        yield event.plain_result(
            f"已拒绝来自【{sender_name}】的赠予\n"
            f"【{item_name}】x{count} 已返还"
        )

    @player_required
    async def handle_upgrade_ring(self, player: Player, event: AstrMessageEvent, ring_name: str):
        """升级/更换储物戒"""
        if not ring_name or ring_name.strip() == "":
            # 显示可用的储物戒列表
            rings = self.storage_ring_manager.get_all_storage_rings()
            current_capacity = self.storage_ring_manager.get_ring_capacity(player.storage_ring)

            lines = [
                f"=== 储物戒列表 ===\n",
                f"当前：【{player.storage_ring}】({current_capacity}格)\n",
                f"━━━━━━━━━━━━━━━\n",
            ]

            for ring in rings:
                # 标记当前装备
                if ring["name"] == player.storage_ring:
                    marker = "✓ "
                elif ring["capacity"] <= current_capacity:
                    marker = "✗ "  # 容量不高于当前的
                else:
                    marker = "  "

                level_name = self.storage_ring_manager._format_required_level(ring["required_level_index"])
                lines.append(
                    f"{marker}【{ring['name']}】({ring['rank']})\n"
                    f"    容量：{ring['capacity']}格 | 需求：{level_name}\n"
                )

            lines.append(f"\n用法：{CMD_UPGRADE_RING} 储物戒名")
            lines.append("\n注：储物戒只能升级，不能卸下")

            yield event.plain_result("".join(lines))
            return

        ring_name = ring_name.strip()

        # 检查是否为储物戒类型
        ring_config = self.storage_ring_manager.get_storage_ring_config(ring_name)
        if not ring_config:
            yield event.plain_result(f"未找到储物戒：{ring_name}")
            return

        # 升级储物戒
        success, message = await self.storage_ring_manager.upgrade_ring(player, ring_name)

        if success:
            yield event.plain_result(f"✅ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    def _categorize_items(self, items: dict) -> dict:
        """将物品按分类整理"""
        result = {cat: [] for cat in ITEM_CATEGORIES.keys()}
        
        for item_name, count in items.items():
            categorized = False
            for category, keywords in ITEM_CATEGORIES.items():
                if category == "其他":
                    continue
                # 检查物品名是否包含分类关键词
                for keyword in keywords:
                    if keyword in item_name or item_name in keyword:
                        result[category].append((item_name, count))
                        categorized = True
                        break
                if categorized:
                    break
            
            # 根据配置判断物品类型
            if not categorized:
                item_config = self.config_manager.items_data.get(item_name, {})
                item_type = item_config.get("type", "")
                
                if item_type in ["weapon", "武器"]:
                    result["装备"].append((item_name, count))
                elif item_type in ["armor", "防具"]:
                    result["装备"].append((item_name, count))
                elif item_type in ["technique", "功法", "main_technique"]:
                    result["功法"].append((item_name, count))
                elif item_type in ["material", "材料"]:
                    result["材料"].append((item_name, count))
                else:
                    result["其他"].append((item_name, count))
        
        # 移除空分类
        return {k: v for k, v in result.items() if v}

    @player_required
    async def handle_recycle_item(self, player: Player, event: AstrMessageEvent, args: str):
        """回收储物戒中的物品，按售价折算为灵石"""
        if not args or args.strip() == "":
            yield event.plain_result(
                f"请指定要回收的物品\n"
                f"用法：{CMD_RECYCLE_ITEM} 物品名 [数量]\n"
                f"示例：{CMD_RECYCLE_ITEM} 灵草 5\n"
                f"💡 按物品售价的 {int(RECYCLE_RATE * 100)}% 折算灵石（至少 1 灵石/个），回收后不可找回"
            )
            return

        args = args.strip()
        # ⚠️ 宿主的 CommandFilter 对 str 参数只取第一个 token，
        #    `/回收 灵草 5` 传进来的实为 "灵草"（数量被丢弃）⇒ 必须从原始消息重解析。
        item_name, count = parse_counted_args(event, args, [CMD_RECYCLE_ITEM], 1)

        if not item_name:
            yield event.plain_result(
                f"请指定要回收的物品\n"
                f"用法：{CMD_RECYCLE_ITEM} 物品名 [数量]\n"
                f"示例：{CMD_RECYCLE_ITEM} 灵草 5"
            )
            return

        if count <= 0:
            yield event.plain_result("数量必须大于0")
            return

        # 跨所有物品表按名称解析售价
        cfg = self.config_manager
        item_cfg = (
            cfg.items_data.get(item_name)
            or cfg.weapons_data.get(item_name)
            or cfg.pills_data.get(item_name)
            or cfg.exp_pills_data.get(item_name)
            or cfg.utility_pills_data.get(item_name)
        )
        if not item_cfg or not item_cfg.get("price"):
            yield event.plain_result(
                f"❌ 未找到「{item_name}」的回收价，该物品无法回收（可能是专属道具）"
            )
            return

        price = item_cfg["price"]
        unit = max(1, int(price * RECYCLE_RATE))
        total = unit * count

        # 先移除物品：复用 discard_item（已修复 lost update，会同步最新储物戒回 player）
        success, message = await self.storage_ring_manager.discard_item(player, item_name, count)
        if not success:
            yield event.plain_result(f"❌ {message}")
            return

        # discard_item 已把最新储物戒同步回 player，这里仅加灵石后写回
        player.gold += total
        await self.db.update_player(player)

        yield event.plain_result(
            f"♻️ 回收成功！\n"
            f"└─ {item_name}×{count}\n"
            f"└─ 获得灵石 +{total:,}（单价 {unit}/个，{int(RECYCLE_RATE * 100)}% 回收价）\n"
            f"└─ 当前灵石：{player.gold:,}"
        )

    @player_required
    async def handle_search_item(self, player: Player, event: AstrMessageEvent, keyword: str):
        """搜索储物戒中的物品"""
        if not keyword or keyword.strip() == "":
            yield event.plain_result(
                f"请指定搜索关键词\n"
                f"用法：{CMD_SEARCH_ITEM} 关键词\n"
                f"示例：{CMD_SEARCH_ITEM} 灵草"
            )
            return

        keyword = keyword.strip().lower()
        items = player.get_storage_ring_items()
        
        # 模糊搜索
        matched = []
        for item_name, count in items.items():
            if keyword in item_name.lower():
                matched.append((item_name, count))
        
        if not matched:
            yield event.plain_result(f"未找到包含「{keyword}」的物品")
            return
        
        lines = [f"=== 搜索结果：{keyword} ===\n"]
        for item_name, count in matched:
            lines.append(f"  · {item_name}×{count}\n")
        lines.append(f"\n共找到 {len(matched)} 种物品")
        
        yield event.plain_result("".join(lines))

    @player_required
    async def handle_retrieve_all(self, player: Player, event: AstrMessageEvent, category: str = None):
        """批量取出指定分类的物品"""
        if not category or category.strip() == "":
            yield event.plain_result(
                f"请指定要取出的分类\n"
                f"用法：{CMD_RETRIEVE_ALL} 分类名\n"
                f"可用分类：材料、装备、功法、其他\n"
                f"示例：{CMD_RETRIEVE_ALL} 材料"
            )
            return
        
        category = category.strip()
        if category not in ITEM_CATEGORIES:
            yield event.plain_result(f"未知分类：{category}\n可用分类：材料、装备、功法、其他")
            return
        
        items = player.get_storage_ring_items()
        categorized = self._categorize_items(items)
        cat_items = categorized.get(category, [])
        
        if not cat_items:
            yield event.plain_result(f"储物戒中没有【{category}】类物品")
            return
        
        # 取出所有该分类的物品
        retrieved = []
        failed = []
        for item_name, count in cat_items:
            success, msg = await self.storage_ring_manager.retrieve_item(player, item_name, count)
            if success:
                retrieved.append(f"{item_name}×{count}")
            else:
                failed.append(f"{item_name}：{msg}")
        
        lines = [f"=== 批量取出【{category}】 ===\n"]
        if retrieved:
            lines.append(f"✅ 已取出：\n")
            for item in retrieved:
                lines.append(f"  · {item}\n")
        if failed:
            lines.append(f"\n❌ 失败：\n")
            for item in failed:
                lines.append(f"  · {item}\n")
        
        yield event.plain_result("".join(lines))
