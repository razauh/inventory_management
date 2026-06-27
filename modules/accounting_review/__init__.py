from .controller import AccountingReviewController

MODULE_TITLE = "Accounting"


def create_module(conn, current_user=None):
    return AccountingReviewController(conn, current_user=current_user)


__all__ = ["AccountingReviewController", "MODULE_TITLE", "create_module"]
