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

1. Create or activate the local conda environment for this repo.
2. Run the one-shot bootstrap helper:
   ```bash
   ./scripts/bootstrap_repo.sh --from-dir /path/to/trusted/wheels
   # or, if you have explicitly approved an index:
   ./scripts/bootstrap_repo.sh --index-url https://your.trusted.index/simple
   ```
   If `.conda/` already exists and `.wheelhouse-app/` is already seeded, the script will reuse them.
3. If you prefer the manual flow, seed `.wheelhouse-app/` from a vetted source, then run the secure installer:
   ```bash
   ./scripts/seed_wheelhouse.sh --from-dir /path/to/trusted/wheels
   # or, if you have explicitly approved an index:
   ./scripts/seed_wheelhouse.sh --index-url https://your.trusted.index/simple
   ```
4. Run the secure installer:
   ```bash
   ./scripts/install_requirements_secure.sh
   ```
5. Run the application:
   ```bash
   python -m inventory_management.main
   ```

`requirements.in` is the editable manifest. `requirements.txt` is the secure pip driver and installs only from `.wheelhouse-app/` with hash checking.
The secure installer also verifies the app wheelhouse against `requirements.lock.txt` before it calls `pip`.
`scripts/bootstrap_repo.sh` combines env creation, seeding, install, and final version verification.

Bootstrap help:
```bash
./scripts/bootstrap_repo.sh --from-dir /path/to/trusted/wheels
./scripts/bootstrap_repo.sh --index-url https://your.trusted.index/simple
./scripts/bootstrap_repo.sh --help
```

## Development Notes

### Graphify Update Flow

The `scripts/update_graphify` entry point expects `graphify` to be available on
`PATH`. If your shell does not expose it yet, set `GRAPHIFY_BIN` to the full
path of the executable before running the script.

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
