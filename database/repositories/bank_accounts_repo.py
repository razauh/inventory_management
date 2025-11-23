import sqlite3

class BankAccountsRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_company_bank_accounts(self):
        """
        List all active company bank accounts.
        Returns a list of dicts (sqlite3.Row-like) with keys:
        bank_account_id, bank_name, account_title, account_no
        """
        cursor = self.conn.execute("""
            SELECT 
                account_id as bank_account_id,
                bank_name,
                label as account_title,
                account_no
            FROM company_bank_accounts
            WHERE is_active = 1
            ORDER BY label
        """)
        return [dict(row) for row in cursor.fetchall()]
