#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if (
    importlib.util.find_spec("graphify") is None
    and _VENV_PYTHON.exists()
    and os.environ.get("GRAPHIFY_REEXECED") != "1"
):
    os.environ["GRAPHIFY_REEXECED"] = "1"
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

from networkx.readwrite import json_graph

from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.detect import detect
from graphify.export import to_html, to_json
from graphify.extract import extract
from graphify.report import generate


OUTPUT_ROOT = ROOT / "graphify-out"
SCOPES_ROOT = OUTPUT_ROOT / "scopes"
MERGED_JSON = OUTPUT_ROOT / "merged-graph.json"
MERGED_HTML = OUTPUT_ROOT / "merged-graph.html"
MERGED_REPORT = OUTPUT_ROOT / "MERGED_GRAPH_REPORT.md"
MANIFEST = OUTPUT_ROOT / "split-merge-manifest.json"
GRAPHIFY_VENV_BIN = ROOT / ".venv" / "bin" / "graphify"

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "target",
    ".venv",
    ".pytest_cache",
    "graphify-out",
    "logs",
    "logs_docs",
    ".agents",
    ".claude",
    ".github",
}


def make_id(*parts: str) -> str:
    combined = "_".join(p.strip("_.") for p in parts if p)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", combined)
    return cleaned.strip("_").lower()


def resolve_graphify_bin() -> str:
    env_bin = os.environ.get("GRAPHIFY_BIN", "").strip()
    if env_bin and (Path(env_bin).exists() or shutil.which(env_bin)):
        return env_bin

    if GRAPHIFY_VENV_BIN.exists():
        return str(GRAPHIFY_VENV_BIN)

    found = shutil.which("graphify")
    if found:
        return found

    raise RuntimeError(
        "graphify CLI not found. Run scripts/update_graphify to bootstrap a local "
        ".venv or install graphify so it is available on PATH."
    )


def scope_detection(root: Path) -> list[dict]:
    scopes = []
    for path in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in EXCLUDE_DIRS):
        detected = detect(path)
        files = detected.get("files", {})
        total_files = sum(len(v) for v in files.values())
        if total_files == 0:
            continue
        scopes.append(
            {
                "name": path.name,
                "path": path,
                "detected": detected,
                "total_files": total_files,
                "total_words": detected.get("total_words", 0),
            }
        )
    return scopes


def document_nodes(scope_name: str, detected: dict) -> list[dict]:
    nodes = []
    buckets = detected.get("files", {})
    for file_type in ("document", "paper", "image"):
        for raw in buckets.get(file_type, []):
            rel = str(Path(raw))
            nodes.append(
                {
                    "id": make_id(scope_name, rel),
                    "label": Path(rel).name,
                    "file_type": file_type,
                    "source_file": rel,
                    "source_location": None,
                    "source_url": None,
                    "captured_at": None,
                    "author": None,
                    "contributor": None,
                }
            )
    return nodes


def build_scope(scope: dict) -> Path:
    scope_name = scope["name"]
    scope_path: Path = scope["path"]
    detected = scope["detected"]
    files = detected.get("files", {})
    code_files = [Path(f) for f in files.get("code", [])]

    extraction = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    if code_files:
        extraction = extract(code_files, cache_root=scope_path.resolve())

    extraction["nodes"].extend(document_nodes(scope_name, detected))

    if not extraction["nodes"]:
        raise RuntimeError(f"Scope {scope_name} produced no graph nodes.")

    graph = build_from_json(extraction)
    communities = cluster(graph) if graph.number_of_nodes() else {}
    cohesion = score_all(graph, communities) if communities else {}
    labels = {cid: f"Community {cid}" for cid in communities}
    questions = suggest_questions(graph, communities, labels) if communities else []
    gods = god_nodes(graph) if graph.number_of_nodes() else []
    surprises = surprising_connections(graph, communities) if graph.number_of_nodes() else []

    out_dir = SCOPES_ROOT / scope_name
    out_dir.mkdir(parents=True, exist_ok=True)

    graph_json = out_dir / "graph.json"
    wrote_json = to_json(graph, communities, str(graph_json), force=True)
    if not wrote_json:
        raise RuntimeError(f"Failed to write graph.json for {scope_name}.")

    report = generate(
        graph,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        {
            "total_files": scope["total_files"],
            "total_words": scope["total_words"],
            "files": files,
        },
        {"input": 0, "output": 0},
        scope_name,
        suggested_questions=questions,
    )
    (out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")

    try:
        to_html(graph, communities, str(out_dir / "graph.html"), community_labels=labels or None)
    except ValueError:
        pass

    return graph_json


def merge_graphs(graph_paths: list[Path]) -> None:
    cmd = [resolve_graphify_bin(), "merge-graphs", *(str(p) for p in graph_paths), "--out", str(MERGED_JSON)]
    subprocess.run(cmd, cwd=ROOT, check=True)


def write_merged_views(scope_graphs: list[Path], scopes: list[dict]) -> None:
    merged_payload = json.loads(MERGED_JSON.read_text(encoding="utf-8"))
    try:
        graph = json_graph.node_link_graph(merged_payload, edges="links")
    except TypeError:
        graph = json_graph.node_link_graph(merged_payload)

    communities = cluster(graph) if graph.number_of_nodes() else {}
    cohesion = score_all(graph, communities) if communities else {}
    labels = {cid: f"Community {cid}" for cid in communities}
    questions = suggest_questions(graph, communities, labels) if communities else []
    gods = god_nodes(graph) if graph.number_of_nodes() else []
    surprises = surprising_connections(graph, communities) if graph.number_of_nodes() else []
    total_files = sum(scope["total_files"] for scope in scopes)
    total_words = sum(scope["total_words"] for scope in scopes)

    report = generate(
        graph,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        {
            "total_files": total_files,
            "total_words": total_words,
            "warning": f"Merged from {len(scope_graphs)} top-level scopes.",
        },
        {"input": 0, "output": 0},
        f"{ROOT.name} merged",
        suggested_questions=questions,
    )
    MERGED_REPORT.write_text(report, encoding="utf-8")

    try:
        to_html(graph, communities, str(MERGED_HTML), community_labels=labels or None)
    except ValueError:
        pass


def refresh_merged_views() -> None:
    if not MERGED_JSON.exists():
        raise FileNotFoundError(f"merged graph not found: {MERGED_JSON}")

    scopes: list[dict] = []
    scope_graphs: list[Path] = []
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for scope in manifest.get("scopes", []):
            scopes.append(
                {
                    "name": scope.get("name", ""),
                    "total_files": scope.get("total_files", 0),
                    "total_words": scope.get("total_words", 0),
                }
            )
            graph_json = scope.get("graph_json")
            if graph_json:
                scope_graphs.append(ROOT / graph_json)

    if not scopes:
        detected = detect(ROOT)
        scopes = [
            {
                "name": ROOT.name,
                "total_files": detected.get("total_files", 0),
                "total_words": detected.get("total_words", 0),
            }
        ]
    if not scope_graphs:
        scope_graphs = [MERGED_JSON]

    write_merged_views(scope_graphs, scopes)


def write_manifest(graph_paths: list[Path], scopes: list[dict]) -> None:
    payload = {
        "scopes": [
            {
                "name": scope["name"],
                "path": str(scope["path"].relative_to(ROOT)),
                "graph_json": str(graph_path.relative_to(ROOT)),
                "total_files": scope["total_files"],
                "total_words": scope["total_words"],
            }
            for scope, graph_path in zip(scopes, graph_paths, strict=True)
        ],
        "merged_json": str(MERGED_JSON.relative_to(ROOT)),
        "merged_html": str(MERGED_HTML.relative_to(ROOT)),
        "merged_report": str(MERGED_REPORT.relative_to(ROOT)),
    }
    MANIFEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    if len(sys.argv) > 1:
        if sys.argv[1] == "--refresh-merged-views":
            refresh_merged_views()
            print(f"[graphify split] merged report refreshed at {MERGED_REPORT}")
            print(f"[graphify split] merged HTML refreshed at {MERGED_HTML}")
            return 0
        print("Usage: graphify_split_merge.py [--refresh-merged-views]", file=sys.stderr)
        return 2

    scopes = scope_detection(ROOT)
    if not scopes:
        print("No supported top-level scopes found.", file=sys.stderr)
        return 1

    SCOPES_ROOT.mkdir(parents=True, exist_ok=True)
    graph_paths = []
    for scope in scopes:
        print(f"[graphify split] building {scope['name']} ({scope['total_files']} files)")
        graph_paths.append(build_scope(scope))

    print(f"[graphify split] merging {len(graph_paths)} scope graphs")
    merge_graphs(graph_paths)
    write_merged_views(graph_paths, scopes)
    write_manifest(graph_paths, scopes)
    print(f"[graphify split] merged graph written to {MERGED_JSON}")
    print(f"[graphify split] merged report written to {MERGED_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
