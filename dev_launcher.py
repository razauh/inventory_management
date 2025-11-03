import sys
import os
import time
from pathlib import Path


project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))

from PySide6.QtWidgets import QApplication
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PySide6.QtCore import Signal, QObject


class Restarter(QObject):


    restart_signal = Signal()

    def __init__(self, path_to_watch: str):
        super().__init__()
        self.path_to_watch = path_to_watch
        self.last_restart = 0
        self.debounce_time = 1  

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
     
        if event.is_directory or not event.src_path.endswith('.py'):
            return

        changed_file = Path(event.src_path).resolve()

        if "__pycache__" in changed_file.parts or ".git" in changed_file.parts:
            return

        print(f"Change detected in: {changed_file}")
        self.restart_signal.emit()


def main():

    app = QApplication(sys.argv)

    project_root = Path(__file__).parent.resolve()
    restarter = Restarter(path_to_watch=str(project_root))

    def trigger_restart():

        if time.time() - restarter.last_restart > restarter.debounce_time:
            print("Restarting application...")
            restarter.last_restart = time.time()

            restarter.stop()
            
            app.quit()

            os.execv(sys.executable, [sys.executable] + sys.argv)

    restarter.restart_signal.connect(trigger_restart)

    original_exit = sys.exit
    captured_exit_code = None

    def no_exit(arg=None):

        raise SystemExit(arg) if arg is not None else SystemExit()
    
    sys.exit = no_exit
    
    try:
        # Set environment variable to indicate we're running under dev_launcher
        import os
        os.environ['__DEV_LAUNCHER__'] = '1'
        
        from main import main as main_app

        try:
            main_app()
        except SystemExit as e:
            captured_exit_code = e.code if e.code is not None else 0
            
    except ImportError:
        print("Error: Could not import main.py. Make sure main.py exists and has a main() function.")

        original_exit(1)
    except Exception as e:

        sys.exit = original_exit
        print(f"Error running main application: {e}")
        import traceback
        traceback.print_exc()
        original_exit(1)  # Use original_exit directly to ensure proper exit
    finally:
        # Always restore the original sys.exit in the finally block
        sys.exit = original_exit
        # Remove the environment variable after main app runs
        if '__DEV_LAUNCHER__' in os.environ:
            del os.environ['__DEV_LAUNCHER__']
    
    # If a non-zero exit code was captured after restoration, propagate the failure
    if captured_exit_code is not None and captured_exit_code != 0:
        print(f"Main application called sys.exit({captured_exit_code}), propagating failure")
        original_exit(captured_exit_code)

    # Run the application's event loop - the main UI should now be running
    # and file watching is active via the connected signal
    exit_code = app.exec()

    # Clean up the observer thread before exiting
    restarter.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()