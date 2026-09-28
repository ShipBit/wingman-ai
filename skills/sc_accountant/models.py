"""
SC_Accountant — Data Models

All financial record types used by the SC_Accountant skill.
Uses dataclasses with to_dict()/from_dict() for JSON/JSONL serialization.

Covers: Transactions, Trade Orders, Budgets, Sessions, Balance,
Opportunities (futures), Positions (investing), Hauls (cargo transport),
and Assets (fleet/equipment registry).

The three-statement accounting model is built on a classification layer that
maps every transaction category to a financial statement line (Revenue, COGS,
OpEx, CapEx) and a gameplay activity (Trading, Bounties, etc.).

Author: Mallachi
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Transaction category constants
# ---------------------------------------------------------------------------

# Trading (auto-captured from SC_LogReader or manual)
CATEGORY_COMMODITY_PURCHASE = "commodity_purchase"
CATEGORY_COMMODITY_SALE = "commodity_sale"
CATEGORY_ITEM_PURCHASE = "item_purchase"
CATEGORY_ITEM_SALE = "item_sale"

# Player-to-player (manual only)
CATEGORY_PLAYER_TRADE_BUY = "player_trade_buy"
CATEGORY_PLAYER_TRADE_SELL = "player_trade_sell"

# Income
CATEGORY_MISSION_REWARD = "mission_reward"
CATEGORY_BOUNTY_REWARD = "bounty_reward"
CATEGORY_SALVAGE_INCOME = "salvage_income"
CATEGORY_OTHER_INCOME = "other_income"

# Expenses
CATEGORY_FUEL = "fuel"
CATEGORY_REPAIRS = "repairs"
CATEGORY_INSURANCE = "insurance"
CATEGORY_AMMUNITION = "ammunition"
CATEGORY_MEDICAL = "medical"
CATEGORY_FINES = "fines"
CATEGORY_HANGAR_FEES = "hangar_fees"
CATEGORY_OTHER_EXPENSE = "other_expense"
CATEGORY_MONEY_SENT = "money_transfer_sent"

# Operating
CATEGORY_CREW_PAYMENT = "crew_payment"
CATEGORY_ORG_CONTRIBUTION = "org_contribution"
CATEGORY_RENTAL = "rental"

# Capital expenditures (asset purchases)
CATEGORY_SHIP_PURCHASE = "ship_purchase"
CATEGORY_COMPONENT_PURCHASE = "component_purchase"
CATEGORY_CAPITAL_INVESTMENT = "capital_investment"

ALL_CATEGORIES: set[str] = {
    CATEGORY_COMMODITY_PURCHASE,
    CATEGORY_COMMODITY_SALE,
    CATEGORY_ITEM_PURCHASE,
    CATEGORY_ITEM_SALE,
    CATEGORY_PLAYER_TRADE_BUY,
    CATEGORY_PLAYER_TRADE_SELL,
    CATEGORY_MISSION_REWARD,
    CATEGORY_BOUNTY_REWARD,
    CATEGORY_SALVAGE_INCOME,
    CATEGORY_OTHER_INCOME,
    CATEGORY_FUEL,
    CATEGORY_REPAIRS,
    CATEGORY_INSURANCE,
    CATEGORY_AMMUNITION,
    CATEGORY_MEDICAL,
    CATEGORY_FINES,
    CATEGORY_HANGAR_FEES,
    CATEGORY_OTHER_EXPENSE,
    CATEGORY_MONEY_SENT,
    CATEGORY_CREW_PAYMENT,
    CATEGORY_ORG_CONTRIBUTION,
    CATEGORY_RENTAL,
    CATEGORY_SHIP_PURCHASE,
    CATEGORY_COMPONENT_PURCHASE,
    CATEGORY_CAPITAL_INVESTMENT,
}

INCOME_CATEGORIES: set[str] = {
    CATEGORY_COMMODITY_SALE,
    CATEGORY_ITEM_SALE,
    CATEGORY_PLAYER_TRADE_SELL,
    CATEGORY_MISSION_REWARD,
    CATEGORY_BOUNTY_REWARD,
    CATEGORY_SALVAGE_INCOME,
    CATEGORY_OTHER_INCOME,
}

EXPENSE_CATEGORIES: set[str] = ALL_CATEGORIES - INCOME_CATEGORIES


# ---------------------------------------------------------------------------
# Financial statement classification
# ---------------------------------------------------------------------------


class StatementClass(str, Enum):
    """Maps transaction categories to income statement lines."""

    REVENUE = "revenue"
    COGS = "cogs"
    OPEX = "opex"
    CAPEX = "capex"


class Activity(str, Enum):
    """Gameplay loop that a transaction belongs to."""

    TRADING = "trading"
    BOUNTY_HUNTING = "bounty_hunting"
    MISSIONS = "missions"
    SALVAGE = "salvage"
    HAULING = "hauling"
    GENERAL = "general"


CATEGORY_CLASSIFICATION: dict[str, StatementClass] = {
    # Revenue
    CATEGORY_COMMODITY_SALE: StatementClass.REVENUE,
    CATEGORY_ITEM_SALE: StatementClass.REVENUE,
    CATEGORY_PLAYER_TRADE_SELL: StatementClass.REVENUE,
    CATEGORY_MISSION_REWARD: StatementClass.REVENUE,
    CATEGORY_BOUNTY_REWARD: StatementClass.REVENUE,
    CATEGORY_SALVAGE_INCOME: StatementClass.REVENUE,
    CATEGORY_OTHER_INCOME: StatementClass.REVENUE,
    # Cost of Goods Sold
    CATEGORY_COMMODITY_PURCHASE: StatementClass.COGS,
    CATEGORY_PLAYER_TRADE_BUY: StatementClass.COGS,
    # Operating Expenses
    CATEGORY_FUEL: StatementClass.OPEX,
    CATEGORY_REPAIRS: StatementClass.OPEX,
    CATEGORY_INSURANCE: StatementClass.OPEX,
    CATEGORY_AMMUNITION: StatementClass.OPEX,
    CATEGORY_MEDICAL: StatementClass.OPEX,
    CATEGORY_FINES: StatementClass.OPEX,
    CATEGORY_HANGAR_FEES: StatementClass.OPEX,
    CATEGORY_OTHER_EXPENSE: StatementClass.OPEX,
    CATEGORY_MONEY_SENT: StatementClass.OPEX,
    CATEGORY_CREW_PAYMENT: StatementClass.OPEX,
    CATEGORY_ORG_CONTRIBUTION: StatementClass.OPEX,
    CATEGORY_RENTAL: StatementClass.OPEX,
    CATEGORY_ITEM_PURCHASE: StatementClass.OPEX,
    # Capital Expenditures
    CATEGORY_SHIP_PURCHASE: StatementClass.CAPEX,
    CATEGORY_COMPONENT_PURCHASE: StatementClass.CAPEX,
    CATEGORY_CAPITAL_INVESTMENT: StatementClass.CAPEX,
}

CATEGORY_ACTIVITY: dict[str, Activity] = {
    CATEGORY_COMMODITY_SALE: Activity.TRADING,
    CATEGORY_COMMODITY_PURCHASE: Activity.TRADING,
    CATEGORY_ITEM_SALE: Activity.TRADING,
    CATEGORY_PLAYER_TRADE_SELL: Activity.TRADING,
    CATEGORY_PLAYER_TRADE_BUY: Activity.TRADING,
    CATEGORY_BOUNTY_REWARD: Activity.BOUNTY_HUNTING,
    CATEGORY_AMMUNITION: Activity.BOUNTY_HUNTING,
    CATEGORY_MISSION_REWARD: Activity.MISSIONS,
    CATEGORY_SALVAGE_INCOME: Activity.SALVAGE,
    CATEGORY_ITEM_PURCHASE: Activity.GENERAL,
    CATEGORY_FUEL: Activity.GENERAL,
    CATEGORY_REPAIRS: Activity.GENERAL,
    CATEGORY_INSURANCE: Activity.GENERAL,
    CATEGORY_MEDICAL: Activity.GENERAL,
    CATEGORY_FINES: Activity.GENERAL,
    CATEGORY_HANGAR_FEES: Activity.GENERAL,
    CATEGORY_OTHER_EXPENSE: Activity.GENERAL,
    CATEGORY_MONEY_SENT: Activity.GENERAL,
    CATEGORY_OTHER_INCOME: Activity.GENERAL,
    CATEGORY_CREW_PAYMENT: Activity.GENERAL,
    CATEGORY_ORG_CONTRIBUTION: Activity.GENERAL,
    CATEGORY_RENTAL: Activity.GENERAL,
    CATEGORY_SHIP_PURCHASE: Activity.GENERAL,
    CATEGORY_COMPONENT_PURCHASE: Activity.GENERAL,
    CATEGORY_CAPITAL_INVESTMENT: Activity.GENERAL,
}

# Human-readable labels for display
CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_COMMODITY_PURCHASE: "Commodity Purchase",
    CATEGORY_COMMODITY_SALE: "Commodity Sale",
    CATEGORY_ITEM_PURCHASE: "Item Purchase",
    CATEGORY_ITEM_SALE: "Item Sale",
    CATEGORY_PLAYER_TRADE_BUY: "P2P Trade (Buy)",
    CATEGORY_PLAYER_TRADE_SELL: "P2P Trade (Sell)",
    CATEGORY_MISSION_REWARD: "Mission Reward",
    CATEGORY_BOUNTY_REWARD: "Bounty Reward",
    CATEGORY_SALVAGE_INCOME: "Salvage Income",
    CATEGORY_OTHER_INCOME: "Other Income",
    CATEGORY_FUEL: "Fuel",
    CATEGORY_REPAIRS: "Repairs",
    CATEGORY_INSURANCE: "Insurance",
    CATEGORY_AMMUNITION: "Ammunition",
    CATEGORY_MEDICAL: "Medical",
    CATEGORY_FINES: "Fines",
    CATEGORY_HANGAR_FEES: "Hangar Fees",
    CATEGORY_OTHER_EXPENSE: "Other Expense",
    CATEGORY_MONEY_SENT: "Money Sent",
    CATEGORY_CREW_PAYMENT: "Crew Payment",
    CATEGORY_ORG_CONTRIBUTION: "Org Contribution",
    CATEGORY_RENTAL: "Rental",
    CATEGORY_SHIP_PURCHASE: "Ship Purchase",
    CATEGORY_COMPONENT_PURCHASE: "Component Purchase",
    CATEGORY_CAPITAL_INVESTMENT: "Capital Investment",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Transaction:
    """A single financial transaction record."""

    id: str
    timestamp: str  # ISO 8601
    category: str  # From ALL_CATEGORIES
    transaction_type: str  # "income" or "expense"
    amount: float  # aUEC (always positive; sign determined by type)
    description: str
    location: str
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "manual"  # "auto_log", "manual", "trade_order"
    # Optional linkage
    trade_order_id: str | None = None
    session_id: str | None = None
    # Auto-captured trade fields (from SC_LogReader ledger)
    item_name: str | None = None
    item_guid: str | None = None
    quantity: float | None = None
    quantity_unit: str | None = None
    shop_name: str | None = None
    player_id: str | None = None
    # Three-statement model fields
    linked_asset_id: str | None = None  # Links to Asset for per-ship P&L
    activity: str | None = None  # Activity enum value (auto-set from category)
    # SC_LogReader event fingerprint, used for precise import dedup (falls
    # back to timestamp:category:amount when absent, e.g. manual entries).
    source_fingerprint: str | None = None
    # SC_LogReader mission_id, when the event carried one. Used to scope
    # reward-bundle supersession to the same mission; never a wildcard.
    source_mission_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Transaction:
        """Create a Transaction from a dictionary."""
        # Handle missing fields for forward compatibility
        data.setdefault("notes", "")
        data.setdefault("tags", [])
        data.setdefault("source", "manual")
        data.setdefault("trade_order_id", None)
        data.setdefault("session_id", None)
        data.setdefault("item_name", None)
        data.setdefault("item_guid", None)
        data.setdefault("quantity", None)
        data.setdefault("quantity_unit", None)
        data.setdefault("shop_name", None)
        data.setdefault("player_id", None)
        data.setdefault("linked_asset_id", None)
        data.setdefault("activity", None)
        data.setdefault("source_fingerprint", None)
        data.setdefault("source_mission_id", None)
        data.pop("group_session_id", None)  # removed in v3.0
        return cls(**data)


@dataclass
class TradeOrder:
    """A planned trade that may be executed in the future."""

    id: str
    created_at: str  # ISO 8601
    status: str  # "open", "completed", "cancelled"
    order_type: str  # "buy" or "sell"
    item_name: str
    quantity: float
    quantity_unit: str = "scu"
    target_price: float | None = None
    target_location: str | None = None
    notes: str = ""
    # Completion tracking
    completed_at: str | None = None
    actual_price: float | None = None
    transaction_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TradeOrder:
        """Create a TradeOrder from a dictionary."""
        data.setdefault("quantity_unit", "scu")
        data.setdefault("target_price", None)
        data.setdefault("target_location", None)
        data.setdefault("notes", "")
        data.setdefault("completed_at", None)
        data.setdefault("actual_price", None)
        data.setdefault("transaction_id", None)
        return cls(**data)


@dataclass
class Budget:
    """Budget allocation for a category within a time period."""

    id: str
    category: str
    period_type: str  # "daily", "weekly", "monthly", "quarterly", "yearly"
    period_start: str  # ISO 8601 date
    period_end: str  # ISO 8601 date
    allocated_amount: float
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Budget:
        """Create a Budget from a dictionary."""
        data.setdefault("notes", "")
        return cls(**data)


@dataclass
class TradingSession:
    """Tracks a trading session for session-level P&L."""

    id: str
    started_at: str  # ISO 8601
    starting_balance: float
    ended_at: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TradingSession:
        """Create a TradingSession from a dictionary."""
        data.setdefault("ended_at", None)
        data.setdefault("notes", "")
        return cls(**data)


@dataclass
class AccountBalance:
    """Running balance state."""

    current_balance: float = 0.0
    last_updated: str = ""
    total_lifetime_income: float = 0.0
    total_lifetime_expenses: float = 0.0

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AccountBalance:
        """Create an AccountBalance from a dictionary."""
        return cls(
            current_balance=data.get("current_balance", 0.0),
            last_updated=data.get("last_updated", ""),
            total_lifetime_income=data.get("total_lifetime_income", 0.0),
            total_lifetime_expenses=data.get("total_lifetime_expenses", 0.0),
        )


# ---------------------------------------------------------------------------
# Futures — auto-generated trade opportunities
# ---------------------------------------------------------------------------


@dataclass
class Opportunity:
    """A pre-computed trade opportunity from market data."""

    id: str
    created_at: str  # ISO 8601
    status: str  # "available", "accepted", "fulfilled", "expired", "dismissed"
    # Route details
    commodity_name: str
    commodity_id: int
    commodity_code: str
    buy_terminal: str
    buy_terminal_id: int
    buy_location: str  # planet/system name
    buy_price: float  # per SCU
    sell_terminal: str
    sell_terminal_id: int
    sell_location: str
    sell_price: float  # per SCU
    # Calculated
    margin_per_scu: float
    available_scu: float
    estimated_profit: float  # margin_per_scu * available_scu
    score: int  # UEX route score
    # Lifecycle tracking
    route_id: int | None = None
    trade_order_id: str | None = None
    fulfilled_transaction_id: str | None = None
    fulfilled_at: str | None = None
    dismissed_at: str | None = None
    expired_at: str | None = None
    expiry_reason: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Opportunity:
        """Create an Opportunity from a dictionary."""
        data.setdefault("route_id", None)
        data.setdefault("trade_order_id", None)
        data.setdefault("fulfilled_transaction_id", None)
        data.setdefault("fulfilled_at", None)
        data.setdefault("dismissed_at", None)
        data.setdefault("expired_at", None)
        data.setdefault("expiry_reason", "")
        data.setdefault("notes", "")
        return cls(**data)


# ---------------------------------------------------------------------------
# Positions — commodity investment tracking
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """An investment position tracking commodity held for profit."""

    id: str
    opened_at: str  # ISO 8601
    status: str  # "open", "closed", "partial"
    commodity_name: str
    # Purchase details
    commodity_id: int | None = None
    quantity: float = 0.0
    quantity_unit: str = "scu"
    buy_price_per_unit: float = 0.0
    buy_total: float = 0.0
    buy_location: str = ""
    buy_transaction_id: str | None = None
    # Market valuation (updated periodically)
    current_market_price: float = 0.0
    unrealized_pnl: float = 0.0
    last_price_update: str = ""
    # Close details (populated on sale)
    sell_price_per_unit: float = 0.0
    sell_total: float = 0.0
    sell_location: str = ""
    sell_transaction_id: str | None = None
    closed_at: str | None = None
    realized_pnl: float = 0.0
    # Metadata
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Position:
        """Create a Position from a dictionary."""
        data.setdefault("commodity_id", None)
        data.setdefault("quantity", 0.0)
        data.setdefault("quantity_unit", "scu")
        data.setdefault("buy_price_per_unit", 0.0)
        data.setdefault("buy_total", 0.0)
        data.setdefault("buy_location", "")
        data.setdefault("buy_transaction_id", None)
        data.setdefault("current_market_price", 0.0)
        data.setdefault("unrealized_pnl", 0.0)
        data.setdefault("last_price_update", "")
        data.setdefault("sell_price_per_unit", 0.0)
        data.setdefault("sell_total", 0.0)
        data.setdefault("sell_location", "")
        data.setdefault("sell_transaction_id", None)
        data.setdefault("closed_at", None)
        data.setdefault("realized_pnl", 0.0)
        data.setdefault("notes", "")
        return cls(**data)




# ---------------------------------------------------------------------------
# Hauling — cargo transport tracking
# ---------------------------------------------------------------------------


@dataclass
class Haul:
    """A cargo transport trip between locations."""

    id: str
    started_at: str  # ISO 8601
    status: str  # "in_transit", "delivered", "cancelled"
    origin: str
    destination: str
    cargo_description: str
    # Cargo details
    quantity: float = 0.0
    quantity_unit: str = "scu"
    ship_name: str = ""
    # Costs and revenue
    fuel_cost: float = 0.0
    other_costs: float = 0.0
    revenue: float = 0.0
    # Completion
    completed_at: str | None = None
    notes: str = ""
    linked_transaction_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Haul:
        """Create a Haul from a dictionary."""
        data.setdefault("quantity", 0.0)
        data.setdefault("quantity_unit", "scu")
        data.setdefault("ship_name", "")
        data.setdefault("fuel_cost", 0.0)
        data.setdefault("other_costs", 0.0)
        data.setdefault("revenue", 0.0)
        data.setdefault("completed_at", None)
        data.setdefault("notes", "")
        data.setdefault("linked_transaction_ids", [])
        return cls(**data)


# ---------------------------------------------------------------------------
# Assets — fleet and equipment registry
# ---------------------------------------------------------------------------


@dataclass
class Asset:
    """A capital asset (ship, vehicle, component, equipment)."""

    id: str
    created_at: str  # ISO 8601
    asset_type: str  # "ship", "vehicle", "component", "equipment"
    name: str
    status: str  # "active", "sold", "destroyed"
    purchase_price: float = 0.0
    purchase_date: str = ""
    estimated_market_value: float = 0.0
    location: str = ""
    ship_model: str = ""
    parent_asset_id: str | None = None  # Components link to their ship
    notes: str = ""
    # Sale/destruction tracking
    sold_at: str | None = None
    sold_price: float = 0.0
    destroyed_at: str | None = None
    insurance_claim_amount: float = 0.0
    # Linked transaction for the purchase
    purchase_transaction_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Asset:
        """Create an Asset from a dictionary."""
        data.setdefault("purchase_price", 0.0)
        data.setdefault("purchase_date", "")
        data.setdefault("estimated_market_value", 0.0)
        data.setdefault("location", "")
        data.setdefault("ship_model", "")
        data.setdefault("parent_asset_id", None)
        data.setdefault("notes", "")
        data.setdefault("sold_at", None)
        data.setdefault("sold_price", 0.0)
        data.setdefault("destroyed_at", None)
        data.setdefault("insurance_claim_amount", 0.0)
        data.setdefault("purchase_transaction_id", None)
        return cls(**data)


