from __future__ import annotations

from html import escape
from typing import Any, Optional

from PySide6.QtCore import Qt


def escape_html(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def html_table_from_model(model: Any, title: Optional[str] = None) -> str:
    if model is None:
        return "<p>(No data)</p>"

    cols = model.columnCount()
    rows = model.rowCount()
    parts = []

    if title:
        parts.append(f"<h3>{escape_html(title)}</h3>")

    parts.append('<table border="1" cellspacing="0" cellpadding="4">')
    parts.append("<thead><tr>")
    for c in range(cols):
        hdr = model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
        parts.append(f"<th>{escape_html(hdr)}</th>")
    parts.append("</tr></thead><tbody>")
    for r in range(rows):
        parts.append("<tr>")
        for c in range(cols):
            val = model.index(r, c).data(Qt.DisplayRole)
            parts.append(f"<td>{escape_html(val)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)
