#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate overview/hierarchy/diff visualizations and AI summary JSON"
    )
    parser.add_argument(
        "--arch-dir",
        default="build_result/arch",
        help="Directory containing *.arch.json and matrix_manifest.json",
    )
    parser.add_argument(
        "--baseline",
        default="p32_c2_sb0_bp0_cs1_fd1",
        help="Baseline config_id for diffs",
    )
    return parser.parse_args(list(argv))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def mm_id(path: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9_]", "_", path)


def mm_label(text: str) -> str:
    return text.replace('"', "'")


def top_child_path(top_path: str, node_path: str) -> str:
    if node_path == top_path:
        return top_path
    prefix = top_path + "."
    if not node_path.startswith(prefix):
        return node_path
    suffix = node_path[len(prefix) :]
    first = suffix.split(".", 1)[0]
    return prefix + first


def node_lookup(arch: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {node["path"]: node for node in arch["nodes"]}


def summarize_top_links(arch: Dict[str, Any]) -> List[Dict[str, Any]]:
    top = arch["top_path"]
    links: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for edge in arch["connection_edges"]:
        src_top = top_child_path(top, edge["src"])
        dst_top = top_child_path(top, edge["dst"])
        if src_top == dst_top:
            continue
        kind = edge["kind"]
        key = (src_top, dst_top, kind)
        item = links.setdefault(
            key,
            {
                "src": src_top,
                "dst": dst_top,
                "kind": kind,
                "signal_count": 0,
                "signals": set(),
            },
        )
        item["signal_count"] += edge.get("signal_count", 0)
        item["signals"].update(edge.get("signals", []))

    out = []
    for item in links.values():
        signals = sorted(item["signals"])
        out.append(
            {
                "src": item["src"],
                "dst": item["dst"],
                "kind": item["kind"],
                "signal_count": item["signal_count"],
                "signals": signals,
                "signals_preview": signals[:8],
            }
        )
    out.sort(key=lambda x: (x["src"], x["dst"], x["kind"]))
    return out


def build_hierarchy_mermaid(arch: Dict[str, Any]) -> str:
    lines = ["graph TD"]
    nodes = sorted(arch["nodes"], key=lambda n: n["path"])
    for node in nodes:
        node_id = mm_id(node["path"])
        label = f"{node['instance']}<br/>{node['module']}"
        lines.append(f'    {node_id}["{mm_label(label)}"]')

    for edge in sorted(arch["hierarchy_edges"], key=lambda e: (e["src"], e["dst"])):
        lines.append(f"    {mm_id(edge['src'])} --> {mm_id(edge['dst'])}")

    return "\n".join(lines) + "\n"


def build_overview_mermaid(arch: Dict[str, Any]) -> str:
    top = arch["top_path"]
    nmap = node_lookup(arch)
    top_children = [n for n in arch["nodes"] if n.get("parent") == top]
    top_children.sort(key=lambda n: n["path"])

    top_links = summarize_top_links(arch)

    lines = ["graph LR"]
    root_label = f"{nmap[top]['instance']}<br/>{nmap[top]['module']}"
    lines.append(f'    {mm_id(top)}["{mm_label(root_label)}"]')

    for child in top_children:
        child_label = f"{child['instance']}<br/>{child['module']}"
        lines.append(f'    {mm_id(child["path"])}["{mm_label(child_label)}"]')
        lines.append(f"    {mm_id(top)} -.-> {mm_id(child['path'])}")

    for link in top_links:
        count = link["signal_count"]
        unit = "sig" if count == 1 else "sigs"
        if link["kind"] == "directed":
            lines.append(
                f"    {mm_id(link['src'])} -->|{count} {unit}| {mm_id(link['dst'])}"
            )
        else:
            lines.append(
                f"    {mm_id(link['src'])} ---|{count} {unit}| {mm_id(link['dst'])}"
            )

    return "\n".join(lines) + "\n"


def extract_key_params(arch: Dict[str, Any]) -> Dict[str, int]:
    keys = [
        "NUM_CORES",
        "STBUF_ENABLE",
        "STBUF_ALLOW_LOAD_BYPASS",
        "STBUF_CONFLICT_STALL",
        "FENCE_DRAIN_STBUF",
    ]
    out: Dict[str, int] = {}
    params = arch.get("params", {})
    for k in keys:
        data = params.get(k)
        if data is None:
            continue
        val = data.get("int")
        if isinstance(val, int):
            out[k] = val
    return out


def edge_set(edges: List[Dict[str, Any]]) -> set[Tuple[str, str, str]]:
    return {(e["src"], e["dst"], e["kind"]) for e in edges}


def compute_diff(base: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    base_params = base.get("params", {})
    target_params = target.get("params", {})
    param_names = sorted(set(base_params) | set(target_params))

    param_changes = []
    for name in param_names:
        b = base_params.get(name, {})
        t = target_params.get(name, {})
        b_raw = b.get("raw")
        t_raw = t.get("raw")
        if b_raw != t_raw:
            param_changes.append(
                {
                    "name": name,
                    "base": b_raw,
                    "target": t_raw,
                    "base_int": b.get("int"),
                    "target_int": t.get("int"),
                }
            )

    base_nodes = {n["path"] for n in base["nodes"]}
    target_nodes = {n["path"] for n in target["nodes"]}

    base_h = edge_set(base["hierarchy_edges"])
    target_h = edge_set(target["hierarchy_edges"])
    base_c = edge_set(base["connection_edges"])
    target_c = edge_set(target["connection_edges"])

    added_nodes = sorted(target_nodes - base_nodes)
    removed_nodes = sorted(base_nodes - target_nodes)
    added_h = sorted(target_h - base_h)
    removed_h = sorted(base_h - target_h)
    added_c = sorted(target_c - base_c)
    removed_c = sorted(base_c - target_c)

    return {
        "base_config": base["config_id"],
        "target_config": target["config_id"],
        "param_changes": param_changes,
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "added_hierarchy_edges": [
            {"src": s, "dst": d, "kind": k} for (s, d, k) in added_h
        ],
        "removed_hierarchy_edges": [
            {"src": s, "dst": d, "kind": k} for (s, d, k) in removed_h
        ],
        "added_connection_edges": [
            {"src": s, "dst": d, "kind": k} for (s, d, k) in added_c
        ],
        "removed_connection_edges": [
            {"src": s, "dst": d, "kind": k} for (s, d, k) in removed_c
        ],
        "summary": {
            "param_change_count": len(param_changes),
            "added_node_count": len(added_nodes),
            "removed_node_count": len(removed_nodes),
            "added_hierarchy_edge_count": len(added_h),
            "removed_hierarchy_edge_count": len(removed_h),
            "added_connection_edge_count": len(added_c),
            "removed_connection_edge_count": len(removed_c),
        },
    }


def build_diff_mermaid(diff: Dict[str, Any]) -> str:
    base = diff["base_config"]
    target = diff["target_config"]
    lines = ["graph LR"]
    lines.append(f'    base["{mm_label(base)}"]')
    lines.append(f'    target["{mm_label(target)}"]')

    param_changes = diff["param_changes"]
    if param_changes:
        for idx, change in enumerate(param_changes):
            nid = f"p_{idx}"
            label = f"{change['name']}: {change['base']} -> {change['target']}"
            lines.append(f'    {nid}["{mm_label(label)}"]')
            lines.append(f"    base --> {nid}")
            lines.append(f"    {nid} --> target")
    else:
        lines.append('    base -- "no_param_change" --> target')

    summary = diff["summary"]
    summary_items = [
        ("added_nodes", summary["added_node_count"]),
        ("removed_nodes", summary["removed_node_count"]),
        ("added_hier_edges", summary["added_hierarchy_edge_count"]),
        ("removed_hier_edges", summary["removed_hierarchy_edge_count"]),
        ("added_conn_edges", summary["added_connection_edge_count"]),
        ("removed_conn_edges", summary["removed_connection_edge_count"]),
    ]
    for idx, (name, count) in enumerate(summary_items):
        nid = f"s_{idx}"
        lines.append(f'    {nid}["{name}: {count}"]')
        lines.append(f"    base -.-> {nid}")
        lines.append(f"    {nid} -.-> target")

    return "\n".join(lines) + "\n"


def build_ai_summary(
    arches: Dict[str, Dict[str, Any]],
    manifest_rows: List[Dict[str, Any]],
    diffs: Dict[str, Dict[str, Any]],
    baseline: str,
) -> Dict[str, Any]:
    rows = []
    for row in manifest_rows:
        cfg = row["config_id"]
        arch = arches[cfg]
        top = arch["top_path"]
        top_blocks = [
            {
                "path": n["path"],
                "instance": n["instance"],
                "module": n["module"],
            }
            for n in arch["nodes"]
            if n.get("parent") == top
        ]
        top_blocks.sort(key=lambda x: x["path"])
        top_links = summarize_top_links(arch)

        diff = diffs.get(cfg)
        diff_summary = diff["summary"] if diff else None
        changed_params = [c["name"] for c in diff["param_changes"]] if diff else []

        rows.append(
            {
                "config_id": cfg,
                "preset": arch["preset"],
                "cores": arch["cores"],
                "key_params": extract_key_params(arch),
                "summary": arch["summary"],
                "top_blocks": top_blocks,
                "top_links": top_links,
                "diff_from_baseline": {
                    "baseline": baseline,
                    "summary": diff_summary,
                    "changed_params": changed_params,
                }
                if diff
                else None,
            }
        )

    return {
        "baseline": baseline,
        "config_count": len(rows),
        "configs": rows,
    }


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    arch_dir = (repo_root / args.arch_dir).resolve()
    manifest_path = arch_dir / "matrix_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    manifest = read_json(manifest_path)
    matrix_rows = manifest.get("matrix", [])
    if not matrix_rows:
        raise ValueError("Manifest matrix is empty")

    arches: Dict[str, Dict[str, Any]] = {}
    for row in matrix_rows:
        cfg = row["config_id"]
        json_path = Path(row["json_path"])
        if not json_path.exists():
            raise FileNotFoundError(f"Missing arch json for {cfg}: {json_path}")
        arches[cfg] = read_json(json_path)

    if args.baseline not in arches:
        raise ValueError(
            f"Baseline config '{args.baseline}' not found. "
            f"Known configs: {', '.join(sorted(arches))}"
        )

    vis_dir = arch_dir / "visuals"
    mm_dir = vis_dir / "mermaid"
    json_dir = vis_dir / "json"
    diff_dir = vis_dir / "diff"
    for d in (mm_dir, json_dir, diff_dir):
        d.mkdir(parents=True, exist_ok=True)

    for cfg, arch in sorted(arches.items()):
        hierarchy_mmd = build_hierarchy_mermaid(arch)
        overview_mmd = build_overview_mermaid(arch)
        top_links = summarize_top_links(arch)

        write_text(mm_dir / f"{cfg}.hierarchy.mmd", hierarchy_mmd)
        write_text(mm_dir / f"{cfg}.overview.mmd", overview_mmd)
        write_json(
            json_dir / f"{cfg}.overview.json",
            {
                "config_id": cfg,
                "top_path": arch["top_path"],
                "top_links": top_links,
                "summary": arch["summary"],
            },
        )

    baseline_arch = arches[args.baseline]
    all_diffs: Dict[str, Dict[str, Any]] = {}
    for cfg, arch in sorted(arches.items()):
        if cfg == args.baseline:
            continue
        diff = compute_diff(baseline_arch, arch)
        all_diffs[cfg] = diff
        write_json(diff_dir / f"{args.baseline}__vs__{cfg}.diff.json", diff)
        write_text(
            diff_dir / f"{args.baseline}__vs__{cfg}.diff.mmd", build_diff_mermaid(diff)
        )

    write_json(
        vis_dir / "matrix_diffs.json", {"baseline": args.baseline, "diffs": all_diffs}
    )

    ai_summary = build_ai_summary(
        arches=arches,
        manifest_rows=sorted(matrix_rows, key=lambda x: x["config_id"]),
        diffs=all_diffs,
        baseline=args.baseline,
    )
    write_json(vis_dir / "matrix_ai_summary.json", ai_summary)

    print(f"Wrote visuals to: {vis_dir}")
    print(
        f"Configs: {len(arches)}, diffs vs baseline {args.baseline}: {len(all_diffs)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
