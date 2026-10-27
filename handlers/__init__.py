# handlers/__init__.py

from .player_handler import PlayerHandler
from .misc_handler import MiscHandler
from .equipment_handler import EquipmentHandler
from .breakthrough_handler import BreakthroughHandler
from .pill_handler import PillHandler
from .shop_handler import ShopHandler
from .storage_ring_handler import StorageRingHandler
from .sect_handlers import SectHandlers
from .boss_handlers import BossHandlers
from .combat_handlers import CombatHandlers
from .ranking_handlers import RankingHandlers

from .rift_handlers import RiftHandlers
from .adventure_handlers import AdventureHandlers
from .alchemy_handlers import AlchemyHandlers
from .impart_handlers import ImpartHandlers
from .nickname_handler import NicknameHandler
from .bank_handlers import BankHandlers
from .bounty_handlers import BountyHandlers
from .impart_pk_handlers import ImpartPkHandlers
# Phase 4
from .blessed_land_handlers import BlessedLandHandlers
from .spirit_farm_handlers import SpiritFarmHandlers
from .dual_cultivation_handlers import DualCultivationHandlers
from .spirit_eye_handlers import SpiritEyeHandlers
# v3.2.9：天灾人祸
from .calamity_handler import CalamityHandlers
# v3.3.3：炼器系统
from .forge_handlers import ForgeHandlers
# v3.3.8：功法残页合成 + 投毒系统
from .technique_handlers import TechniqueHandlers
from .poison_handlers import PoisonHandlers

__all__ = [
    "PlayerHandler",
    "MiscHandler",
    "EquipmentHandler",
    "BreakthroughHandler",
    "PillHandler",
    "ShopHandler",
    "StorageRingHandler",
    "SectHandlers",
    "BossHandlers",
    "CombatHandlers",
    "RankingHandlers",
    "RiftHandlers",
    "AdventureHandlers",
    "AlchemyHandlers",
    "ImpartHandlers",
    "NicknameHandler",
    "BankHandlers",
    "BountyHandlers",
    "ImpartPkHandlers",
    # Phase 4
    "BlessedLandHandlers",
    "SpiritFarmHandlers",
    "DualCultivationHandlers",
    "SpiritEyeHandlers",
    # v3.2.9
    "CalamityHandlers",
    # v3.3.3
    "ForgeHandlers",
    # v3.3.8
    "TechniqueHandlers",
    "PoisonHandlers",
]
