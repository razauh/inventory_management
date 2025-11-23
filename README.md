# Inventory Management System

A comprehensive inventory management application built with Python and PySide6.

## Features

- Dashboard overview
- Product management
- Inventory tracking
- Purchase management
- Sales tracking
- Customer and vendor management
- Expense tracking
- Reporting capabilities

## Installation

1. Make sure you have Python 3.8+ installed
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python -m inventory_management.main
   ```

## Development Notes

### Removing Python Cache Files

If you need to clean up Python cache files (`.pyc` and `__pycache__` directories), you can run:
```bash
python clean_pycache.py
```

This will remove all Python bytecode cache files that might have been generated during execution.

### Git Management

The `.gitignore` file is configured to ignore:
- Python cache files (`__pycache__`, `*.pyc`)
- Database files
- Log files
- IDE files

This ensures that only source code and essential files are tracked in the repository.

## License

[Add your license information here]