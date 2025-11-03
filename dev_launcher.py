import sys
import os
import time
from pathlib import Path

# Add the project root to the Python path to handle relative imports
project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))

from PySide6.QtWidgets import QApplication
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PySide6.QtCore import Signal, QObject


class Restarter(QObject):
    """
    Handles file system monitoring and application restarting.
    Inherits from QObject to use Qt's signal and slot mechanism.
    """
    # A signal that will be emitted when a file change is detected
    restart_signal = Signal()

    def __init__(self, path_to_watch: str):
        super().__init__()
        self.path_to_watch = path_to_watch
        self.last_restart = 0
        self.debounce_time = 1  # seconds

        self.observer = Observer()
        self.event_handler = Handler(self.restart_signal)
        self.observer.schedule(self.event_handler, self.path_to_watch, recursive=True)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()


class Handler(FileSystemEventHandler):
    """
    Handles events from the watchdog observer.
    """
    def __init__(self, restart_signal: Signal):
        self.restart_signal = restart_signal

    def on_modified(self, event):
        # We only care about Python files
        if event.is_directory or not event.src_path.endswith('.py'):
            return
        
        # Get the absolute path of the changed file
        changed_file = Path(event.src_path).resolve()
        
        # Optional: Ignore specific files or directories
        if "__pycache__" in changed_file.parts or ".git" in changed_file.parts:
            return

        print(f"Change detected in: {changed_file}")
        self.restart_signal.emit()


def main():
    # --- Setup the Restarter ---
    # Get the directory of the current script to watch
    project_root = Path(__file__).parent.resolve()
    restarter = Restarter(path_to_watch=str(project_root))

    # Create the Qt Application
    app = QApplication(sys.argv)

    # Connect the restart signal to a lambda that quits the app
    # and then restarts it using os.execv
    def trigger_restart():
        # Debounce to prevent multiple rapid restarts from a single save operation
        if time.time() - restarter.last_restart > restarter.debounce_time:
            print("Restarting application...")
            restarter.last_restart = time.time()
            
            # Stop the filesystem observer to prevent resource leaks and race conditions
            restarter.stop()
            
            # Quit the application's event loop
            app.quit()
            
            # Relaunch the script
            # sys.executable is the path to the python interpreter
            # sys.argv are the arguments used to run the script
            os.execv(sys.executable, [sys.executable] + sys.argv)

    restarter.restart_signal.connect(trigger_restart)

    # Import and create the main window from the existing main.py
    # This imports the actual application
    try:
        from main import main as main_app
        # Run your original main application (we don't capture its return value)
        main_app()
    except ImportError:
        print("Error: Could not import main.py. Make sure main.py exists and has a main() function.")
        sys.exit(1)
    except Exception as e:
        print(f"Error running main application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Run the application's event loop
    exit_code = app.exec()

    # Clean up the observer thread before exiting
    restarter.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()