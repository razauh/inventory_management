# database/repositories/__init__.py
"""
Repository layer public API.

Usage:
    from database.repositories import (
        # Customers
        CustomersRepo, Customer, CustomersDomainError,
        # Expenses
        ExpensesRepo, Expense, ExpenseCategory, ExpensesDomainError,
        # Customer advances (customer credit)
        CustomerAdvancesRepo, get_customer_advances_repo,
        # Inventory
        InventoryRepo,
        # Products
        ProductsRepo, Product,
        # Purchases
        PurchasesRepo, PurchaseHeader, PurchaseItem, PurchasePaymentsRepo,
        # Sales
        SalesRepo, SaleHeader, SaleItem, SalePaymentsRepo, get_sale_payments_repo,
        # Vendors
        VendorsRepo, Vendor, VendorAdvancesRepo, VendorBankAccountsRepo,
    )
"""

# ---------------- Customers ----------------
from .customers_repo import (
    CustomersRepo,
    Customer,
    DomainError as CustomersDomainError,
)

# ---------------- Expenses -----------------
from .expenses_repo import (
    ExpensesRepo,
    Expense,
    ExpenseCategory,
    DomainError as ExpensesDomainError,
)

# -------- Customer Advances (credit) -------
from .customer_advances_repo import (
    CustomerAdvancesRepo,
    get_customer_advances_repo,
)

# ---------------- Inventory ----------------
from .inventory_repo import InventoryRepo

# ---------------- Products -----------------
from .products_repo import ProductsRepo, Product

# ---------------- Purchases ----------------
from .purchase_payments_repo import PurchasePaymentsRepo
from .purchases_repo import PurchasesRepo, PurchaseHeader, PurchaseItem

# ------------------ Sales ------------------
from .sale_payments_repo import SalePaymentsRepo, get_sale_payments_repo
from .sales_repo import SalesRepo, SaleHeader, SaleItem

# ----------------- Vendors -----------------
from .vendor_advances_repo import VendorAdvancesRepo
from .vendor_bank_accounts_repo import VendorBankAccountsRepo
from .vendors_repo import VendorsRepo, Vendor

__all__ = [
    # customers_repo
    "CustomersRepo",
    "Customer",
    "CustomersDomainError",
    # expenses_repo
    "ExpensesRepo",
    "Expense",
    "ExpenseCategory",
    "ExpensesDomainError",
    # customer_advances_repo
    "CustomerAdvancesRepo",
    "get_customer_advances_repo",
    # inventory_repo
    "InventoryRepo",
    # products_repo
    "ProductsRepo",
    "Product",
    # purchases
    "PurchasePaymentsRepo",
    "PurchasesRepo",
    "PurchaseHeader",
    "PurchaseItem",
    # sales
    "SalePaymentsRepo",
    "get_sale_payments_repo",
    "SalesRepo",
    "SaleHeader",
    "SaleItem",
    # vendors
    "VendorAdvancesRepo",
    "VendorBankAccountsRepo",
    "VendorsRepo",
    "Vendor",
]
