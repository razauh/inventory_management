#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import argparse
import os
import shutil
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

from graphify.analyze import god_nodes, suggest_questions, surprising_connections
from graphify.build import build_from_json
from graphify.cache import check_semantic_cache, save_semantic_cache
from graphify.cluster import cluster, score_all
from graphify.detect import detect, detect_incremental, save_manifest
from graphify.export import to_html, to_json
from graphify.extract import extract
from graphify.llm import extract_corpus_parallel
from graphify.report import generate


NON_CODE_TYPES = ("document", "paper", "image", "video")
DIRECT_LLM_UNSUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
    ".svg",
    ".mp4",
    ".mov",
    ".mp3",
    ".wav",
    ".m4a",
}


def _non_code_files(files: dict[str, list[str]]) -> list[str]:
    selected: list[str] = []
    for file_type in NON_CODE_TYPES:
        selected.extend(files.get(file_type, []))
    return selected


def _semantic_needed(root: Path) -> bool:
    out_dir = root / "graphify-out"
    if (out_dir / "needs_update").exists() or (out_dir / ".needs_update").exists():
        return True

    incremental = detect_incremental(root)
    return bool(_non_code_files(incremental.get("new_files", {})))


def _resolve_backend() -> tuple[str, str, str | None]:
    backend = os.environ.get("GRAPHIFY_SEMANTIC_BACKEND", "").strip().lower()
    model = os.environ.get("GRAPHIFY_SEMANTIC_MODEL") or None

    if not backend:
        if os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY"):
            backend = "kimi"
        elif os.environ.get("OPENAI_API_KEY"):
            backend = "openai"
        elif shutil.which("claude"):
            backend = "claude"

    if backend == "kimi":
        api_key = os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY") or ""
    elif backend == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or ""
    elif backend == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    else:
        raise RuntimeError(
            "semantic refresh needs an LLM backend. Set GRAPHIFY_SEMANTIC_BACKEND "
            "to 'claude', 'openai', or 'kimi', with the matching key when required."
        )

    if backend in {"kimi", "openai"} and not api_key:
        raise RuntimeError(f"semantic backend '{backend}' is selected but its API key is not set")

    return backend, api_key, model


def _safe_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _unsupported_direct_files(files: list[str]) -> list[str]:
    return [f for f in files if Path(f).suffix.lower() in DIRECT_LLM_UNSUPPORTED_EXTENSIONS]


def _build_outputs(root: Path, extraction: dict, detection: dict) -> None:
    out_dir = root / "graphify-out"
    out_dir.mkdir(parents=True, exist_ok=True)

    graph = build_from_json(extraction)
    if graph.number_of_nodes() == 0:
        raise RuntimeError("semantic refresh produced an empty graph")

    communities = cluster(graph)
    cohesion = score_all(graph, communities)
    labels = {cid: f"Community {cid}" for cid in communities}
    questions = suggest_questions(graph, communities, labels)
    tokens = {
        "input": extraction.get("input_tokens", 0),
        "output": extraction.get("output_tokens", 0),
    }
    gods = god_nodes(graph)
    surprises = surprising_connections(graph, communities)

    report = generate(
        graph,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        tokens,
        str(root),
        suggested_questions=questions,
    )
    (out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(graph, communities, str(out_dir / "graph.json"), force=True)
    try:
        to_html(graph, communities, str(out_dir / "graph.html"), community_labels=labels or None)
    except ValueError as exc:
        stale_html = out_dir / "graph.html"
        if stale_html.exists():
            stale_html.unlink()
        print(f"[graphify semantic] Skipped graph.html: {exc}")

    save_manifest(detection.get("files", {}))
    for marker in ("needs_update", ".needs_update"):
        marker_path = out_dir / marker
        if marker_path.exists():
            marker_path.unlink()


def refresh(root: Path) -> None:
    root = root.resolve()
    detection = detect(root)
    files = detection.get("files", {})
    code_files = [Path(f) for f in files.get("code", [])]
    semantic_files = [f for f in _non_code_files(files) if Path(f).is_file()]

    ast = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    if code_files:
        ast = extract(code_files, cache_root=root)

    cached_nodes, cached_edges, cached_hyperedges, uncached = check_semantic_cache(semantic_files, root=root)
    print(
        f"[graphify semantic] Cache: {len(semantic_files) - len(uncached)} files hit, "
        f"{len(uncached)} files need extraction"
    )

    new = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    if uncached:
        unsupported = _unsupported_direct_files(uncached)
        if unsupported:
            examples = ", ".join(str(Path(f).relative_to(root)) for f in unsupported[:5])
            extra = "" if len(unsupported) <= 5 else f", and {len(unsupported) - 5} more"
            raise RuntimeError(
                "changed binary semantic files need the assistant /graphify pipeline "
                f"for vision/transcription/PDF extraction: {examples}{extra}"
            )

        backend, api_key, model = _resolve_backend()
        chunk_size = _safe_int_env("GRAPHIFY_SEMANTIC_CHUNK_SIZE", 22)
        max_workers = _safe_int_env("GRAPHIFY_SEMANTIC_MAX_WORKERS", 5)
        print(
            f"[graphify semantic] Extracting {len(uncached)} file(s) with backend '{backend}' "
            f"using {max_workers} worker(s)"
        )

        def on_chunk_done(idx: int, total: int, result: dict) -> None:
            nodes = len(result.get("nodes", []))
            edges = len(result.get("edges", []))
            print(f"  [chunk {idx + 1}/{total}] {nodes} nodes, {edges} edges", flush=True)

        new = extract_corpus_parallel(
            [Path(f) for f in uncached],
            backend=backend,
            api_key=api_key,
            model=model,
            root=root,
            chunk_size=chunk_size,
            max_workers=max_workers,
            on_chunk_done=on_chunk_done,
        )
        saved = save_semantic_cache(
            new.get("nodes", []),
            new.get("edges", []),
            new.get("hyperedges", []),
            root=root,
        )
        print(f"[graphify semantic] Cached {saved} file(s)")

    semantic = {
        "nodes": cached_nodes + new.get("nodes", []),
        "edges": cached_edges + new.get("edges", []),
        "hyperedges": cached_hyperedges + new.get("hyperedges", []),
        "input_tokens": new.get("input_tokens", 0),
        "output_tokens": new.get("output_tokens", 0),
    }

    seen = {node["id"] for node in ast.get("nodes", [])}
    nodes = list(ast.get("nodes", []))
    for node in semantic["nodes"]:
        node_id = node.get("id")
        if node_id and node_id not in seen:
            nodes.append(node)
            seen.add(node_id)

    extraction = {
        "nodes": nodes,
        "edges": ast.get("edges", []) + semantic["edges"],
        "hyperedges": semantic["hyperedges"],
        "input_tokens": semantic["input_tokens"],
        "output_tokens": semantic["output_tokens"],
    }
    _build_outputs(root, extraction, detection)
    print(
        f"[graphify semantic] Updated graph.json with {len(extraction['nodes'])} nodes "
        f"and {len(extraction['edges'])} edges"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh graphify semantic graph data when needed.")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--check-needed", action="store_true")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    os.chdir(root)
    if args.check_needed:
        return 10 if _semantic_needed(root) else 0

    try:
        refresh(root)
    except Exception as exc:
        print(f"[graphify semantic] Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
