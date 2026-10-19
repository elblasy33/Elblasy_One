"""Roles -> permissions. Enforced server-side by `require()`; the UI only mirrors this."""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    CASHIER = "cashier"
    INVENTORY_OPERATOR = "inventory_operator"
    ACCOUNTANT = "accountant"
    PLATFORM_ADMIN = "platform_admin"


P_SALES = "sales.create"
P_DISCOUNT = "sales.discount"
P_RETURNS = "sales.returns"
P_PAYMENTS = "payments.create"
P_EXPENSES = "expenses.create"
P_STOCK_ADJUST = "inventory.adjust"
P_COST_VISIBLE = "products.cost.view"
P_CREDIT = "customers.credit.override"
P_CONFIG = "config.manage"
P_CONNECTIONS = "connections.manage"
P_USERS = "users.manage"
P_REPORTS = "reports.view"
P_MULTI_COMPANY = "companies.switch"
P_AUDIT = "audit.view"
P_PRODUCTS = "products.manage"
P_PRODUCTS_VIEW = "products.view"
P_PURCHASING = "purchasing.manage"
P_PURCHASING_VIEW = "purchasing.view"
P_STOCK_APPROVE = "inventory.approve"
P_EXPENSE_APPROVE = "expenses.approve"
P_CUSTOMERS = "customers.manage"

ALL = {
    P_SALES, P_DISCOUNT, P_RETURNS, P_PAYMENTS, P_EXPENSES, P_STOCK_ADJUST, P_COST_VISIBLE,
    P_CREDIT, P_CONFIG, P_CONNECTIONS, P_USERS, P_REPORTS, P_MULTI_COMPANY, P_AUDIT,
    P_PRODUCTS, P_PRODUCTS_VIEW, P_PURCHASING, P_PURCHASING_VIEW, P_STOCK_APPROVE,
    P_EXPENSE_APPROVE,
    P_CUSTOMERS,
}  # fmt: skip

PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.OWNER: frozenset(ALL),
    Role.MANAGER: frozenset(ALL - {P_USERS, P_CONNECTIONS, P_MULTI_COMPANY}),
    Role.CASHIER: frozenset({P_SALES, P_PRODUCTS_VIEW, P_CUSTOMERS}),
    Role.INVENTORY_OPERATOR: frozenset(
        {P_STOCK_ADJUST, P_PRODUCTS, P_PRODUCTS_VIEW, P_PURCHASING, P_PURCHASING_VIEW}
    ),
    Role.ACCOUNTANT: frozenset(
        {
            P_PAYMENTS,
            P_EXPENSES,
            P_REPORTS,
            P_COST_VISIBLE,
            P_AUDIT,
            P_PRODUCTS_VIEW,
            P_PURCHASING_VIEW,
        }
    ),
    Role.PLATFORM_ADMIN: frozenset({P_CONNECTIONS, P_CONFIG, P_USERS, P_AUDIT}),
}


def has_permission(role: str, permission: str) -> bool:
    try:
        return permission in PERMISSIONS[Role(role)]
    except ValueError:
        return False
