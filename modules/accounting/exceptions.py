"""Project accounting exceptions."""


class AccountingError(Exception):
    """Base error for accounting module failures."""


class AccountingRuleError(AccountingError):
    """Raised when an accounting rule cannot be applied."""


class AccountingInvariantError(AccountingError):
    """Raised when an accounting invariant is broken."""


class AccountingNotImplementedError(AccountingError, NotImplementedError):
    """Raised by scaffold methods that are not implemented yet."""
