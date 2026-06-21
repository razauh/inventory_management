TOAST_STYLES = {
    "success": {
        "border": "#2f855a",
        "background": "#f0fff4",
        "text": "#1a202c",
    },
    "info": {
        "border": "#3182ce",
        "background": "#ebf8ff",
        "text": "#1a202c",
    },
    "warning": {
        "border": "#b7791f",
        "background": "#fffaf0",
        "text": "#1a202c",
    },
    "error": {
        "border": "#c53030",
        "background": "#fff5f5",
        "text": "#1a202c",
    },
}


def style_for(level: str) -> str:
    colors = TOAST_STYLES.get(level, TOAST_STYLES["info"])
    return (
        "QFrame#notificationToast {"
        f"background: {colors['background']};"
        f"border: 1px solid {colors['border']};"
        "border-radius: 6px;"
        "}"
        "QLabel {"
        f"color: {colors['text']};"
        "}"
        "QPushButton {"
        "border: none;"
        "font-weight: bold;"
        "padding: 2px 6px;"
        "}"
    )
