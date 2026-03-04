#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SV_CONST_RE = re.compile(r"^(?:(\d+)'([sS]?[hdb])([0-9a-fA-F_xzXZ]+)|(\d+))$")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract deep picorv32 architecture metadata from Verilator XML: "
            "hierarchy, module internals, and source locations"
        )
    )
    parser.add_argument(
        "--arch-dir",
        default="build_result/arch",
        help="Directory containing matrix_manifest.json and XML files",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Optional manifest JSON path (defaults to <arch-dir>/matrix_manifest.json)",
    )
    parser.add_argument(
        "--xml",
        nargs="*",
        default=None,
        help="Optional explicit XML file list (overrides manifest)",
    )
    parser.add_argument(
        "--out-dir",
        default="build_result/arch/deep",
        help="Output directory for *.deep.json and deep_manifest.json",
    )
    return parser.parse_args(list(argv))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def safe_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw, 10)
    except ValueError:
        return None


def sv_const_to_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    m = SV_CONST_RE.match(raw)
    if not m:
        return None
    if m.group(4) is not None:
        return int(m.group(4), 10)

    base_spec = m.group(2).lower()
    digits = m.group(3).replace("_", "")
    if any(ch in digits.lower() for ch in "xz"):
        return None

    base = 10
    if base_spec.endswith("h"):
        base = 16
    elif base_spec.endswith("b"):
        base = 2
    return int(digits, base)


def build_file_table(root: ET.Element) -> Dict[str, Dict[str, str]]:
    file_table: Dict[str, Dict[str, str]] = {}
    for section_name in ("files", "module_files"):
        section = root.find(section_name)
        if section is None:
            continue
        for file_elem in section.findall("file"):
            file_id = file_elem.attrib.get("id")
            if not file_id:
                continue
            file_table[file_id] = {
                "id": file_id,
                "path": file_elem.attrib.get("filename", ""),
                "language": file_elem.attrib.get("language", ""),
            }
    return file_table


def parse_loc(
    raw_loc: Optional[str], file_table: Dict[str, Dict[str, str]]
) -> Optional[Dict[str, Any]]:
    if not raw_loc:
        return None

    parts = raw_loc.split(",")
    if len(parts) < 5:
        return {"raw": raw_loc}

    file_id = parts[0]
    line = safe_int(parts[1])
    column = safe_int(parts[2])
    end_line = safe_int(parts[3])
    end_column = safe_int(parts[4])

    return {
        "raw": raw_loc,
        "file_id": file_id,
        "file_path": file_table.get(file_id, {}).get("path"),
        "line": line,
        "column": column,
        "end_line": end_line,
        "end_column": end_column,
    }


def build_dtype_table(root: ET.Element) -> Dict[str, Dict[str, Any]]:
    netlist = root.find("netlist")
    if netlist is None:
        return {}

    typetable = netlist.find("typetable")
    dtype_elems: List[ET.Element] = []

    if typetable is not None:
        dtype_elems = list(typetable)
    else:
        for child in netlist:
            if child.tag.endswith("dtype"):
                dtype_elems.append(child)

    dtypes: Dict[str, Dict[str, Any]] = {}
    for dtype_elem in dtype_elems:
        dtype_id = dtype_elem.attrib.get("id")
        if not dtype_id:
            continue
        dtypes[dtype_id] = {
            "tag": dtype_elem.tag,
            "attrs": dict(dtype_elem.attrib),
        }
    return dtypes


def dtype_width(attrs: Dict[str, str]) -> Optional[int]:
    left = safe_int(attrs.get("left"))
    right = safe_int(attrs.get("right"))
    if left is None or right is None:
        return None
    return abs(left - right) + 1


def format_dtype(
    dtype_id: Optional[str],
    dtypes: Dict[str, Dict[str, Any]],
    cache: Optional[Dict[str, str]] = None,
    seen: Optional[set[str]] = None,
) -> str:
    if dtype_id is None:
        return "unknown"

    if cache is None:
        cache = {}
    if seen is None:
        seen = set()

    if dtype_id in cache:
        return cache[dtype_id]
    if dtype_id in seen:
        return f"dtype_{dtype_id}"

    seen.add(dtype_id)
    entry = dtypes.get(dtype_id)
    if entry is None:
        text = f"unknown_dtype_{dtype_id}"
        cache[dtype_id] = text
        return text

    tag = entry["tag"]
    attrs = entry["attrs"]

    if tag == "basicdtype":
        name = attrs.get("name", "basic")
        left = attrs.get("left")
        right = attrs.get("right")
        if left is not None and right is not None:
            text = f"{name}[{left}:{right}]"
        else:
            text = name
        if attrs.get("signed") == "true":
            text = "signed " + text
    elif tag in ("packarraydtype", "unpackarraydtype", "refdtype"):
        sub_id = attrs.get("sub_dtype_id")
        sub_text = format_dtype(sub_id, dtypes, cache, seen)
        left = attrs.get("left")
        right = attrs.get("right")
        if left is not None and right is not None:
            text = f"{tag}({sub_text})[{left}:{right}]"
        else:
            text = f"{tag}({sub_text})"
    elif tag == "voiddtype":
        text = "void"
    else:
        name = attrs.get("name", "")
        text = f"{tag}({name})" if name else tag

    cache[dtype_id] = text
    return text


def dtype_info(
    dtype_id: Optional[str], dtypes: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    if dtype_id is None:
        return {
            "dtype_id": None,
            "tag": "unknown",
            "text": "unknown",
            "width": None,
            "attrs": {},
        }

    entry = dtypes.get(dtype_id)
    if entry is None:
        return {
            "dtype_id": dtype_id,
            "tag": "unknown",
            "text": f"unknown_dtype_{dtype_id}",
            "width": None,
            "attrs": {},
        }

    attrs = dict(entry["attrs"])
    attrs.pop("id", None)
    width = dtype_width(attrs) if entry["tag"] == "basicdtype" else None

    return {
        "dtype_id": dtype_id,
        "tag": entry["tag"],
        "text": format_dtype(dtype_id, dtypes),
        "width": width,
        "attrs": attrs,
    }


def collect_varrefs(elem: ET.Element) -> List[str]:
    refs = {
        varref.attrib["name"]
        for varref in elem.findall(".//varref")
        if "name" in varref.attrib
    }
    return sorted(refs)


def extract_var(
    var_elem: ET.Element,
    dtypes: Dict[str, Dict[str, Any]],
    file_table: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    attrs = var_elem.attrib
    dtype_id = attrs.get("dtype_id")
    const_elem = var_elem.find("const")
    default_raw = const_elem.attrib.get("name") if const_elem is not None else None

    item = {
        "name": attrs.get("name"),
        "orig_name": attrs.get("origName"),
        "vartype": attrs.get("vartype"),
        "direction": attrs.get("dir"),
        "pin_index": safe_int(attrs.get("pinIndex")),
        "dtype": dtype_info(dtype_id, dtypes),
        "is_parameter": attrs.get("param") == "true",
        "is_public": attrs.get("public") == "true",
        "loc": parse_loc(attrs.get("loc"), file_table),
        "default": {
            "raw": default_raw,
            "int": sv_const_to_int(default_raw),
            "loc": parse_loc(const_elem.attrib.get("loc"), file_table)
            if const_elem is not None
            else None,
        }
        if const_elem is not None
        else None,
        "raw_attrs": dict(attrs),
    }
    return item


def normalize_port_direction(raw: str) -> str:
    raw_lower = raw.lower()
    if raw_lower in ("in", "out", "inout"):
        return raw_lower
    return "unknown"


def extract_instance(
    inst_elem: ET.Element, file_table: Dict[str, Dict[str, str]]
) -> Dict[str, Any]:
    ports: List[Dict[str, Any]] = []
    for port_elem in inst_elem.findall("port"):
        signals = collect_varrefs(port_elem)
        ports.append(
            {
                "name": port_elem.attrib.get("name"),
                "direction": normalize_port_direction(
                    port_elem.attrib.get("direction", "unknown")
                ),
                "port_index": safe_int(port_elem.attrib.get("portIndex")),
                "signals": signals,
                "signal_count": len(signals),
                "loc": parse_loc(port_elem.attrib.get("loc"), file_table),
            }
        )

    ports.sort(
        key=lambda p: (
            p["port_index"] if p["port_index"] is not None else 10**9,
            p["name"] or "",
        )
    )

    return {
        "name": inst_elem.attrib.get("name"),
        "orig_name": inst_elem.attrib.get("origName"),
        "def_name": inst_elem.attrib.get("defName"),
        "loc": parse_loc(inst_elem.attrib.get("loc"), file_table),
        "ports": ports,
    }


def summarize_block(
    block_elem: ET.Element,
    block_type: str,
    file_table: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    refs = collect_varrefs(block_elem)
    tag_hist = Counter(node.tag for node in block_elem.iter())
    tag_hist.pop(block_elem.tag, None)

    item: Dict[str, Any] = {
        "type": block_type,
        "loc": parse_loc(block_elem.attrib.get("loc"), file_table),
        "signal_refs": refs,
        "signal_ref_count": len(refs),
        "tag_histogram": dict(sorted(tag_hist.items())),
    }

    if block_type == "always":
        sensitivity = []
        for sen_elem in block_elem.findall("./sentree/senitem"):
            sen_refs = collect_varrefs(sen_elem)
            for sig in sen_refs:
                sensitivity.append(
                    {
                        "edge": sen_elem.attrib.get("edgeType", ""),
                        "signal": sig,
                        "loc": parse_loc(sen_elem.attrib.get("loc"), file_table),
                    }
                )
        item["sensitivity"] = sensitivity

    if block_type == "contassign":
        lhs = [
            child.attrib.get("name")
            for child in block_elem
            if child.tag == "varref" and child.attrib.get("name") is not None
        ]
        lhs_set = set(lhs)
        rhs = [sig for sig in refs if sig not in lhs_set]
        item["lhs_signals"] = lhs
        item["rhs_signals"] = rhs

    if block_type == "task":
        item["name"] = block_elem.attrib.get("name")

    return item


def parse_modules(
    root: ET.Element,
    dtypes: Dict[str, Dict[str, Any]],
    file_table: Dict[str, Dict[str, str]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Dict[str, Any]]]]:
    netlist = root.find("netlist")
    if netlist is None:
        raise ValueError("XML missing <netlist> section")

    module_records: List[Dict[str, Any]] = []
    module_instance_map: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for module_elem in netlist.findall("module"):
        module_name = module_elem.attrib.get("name")
        if not module_name:
            continue

        params: List[Dict[str, Any]] = []
        ports: List[Dict[str, Any]] = []
        locals_: List[Dict[str, Any]] = []

        for var_elem in module_elem.findall("var"):
            var_item = extract_var(var_elem, dtypes, file_table)
            if var_item["is_parameter"]:
                params.append(var_item)
            elif var_item["direction"] is not None:
                ports.append(var_item)
            else:
                locals_.append(var_item)

        params.sort(key=lambda x: x["name"] or "")
        ports.sort(
            key=lambda x: (
                x["pin_index"] if x["pin_index"] is not None else 10**9,
                x["name"] or "",
            )
        )
        locals_.sort(key=lambda x: x["name"] or "")

        instance_records: List[Dict[str, Any]] = []
        instance_map: Dict[str, Dict[str, Any]] = {}
        for inst_elem in module_elem.findall("instance"):
            inst_item = extract_instance(inst_elem, file_table)
            instance_records.append(inst_item)

            inst_name = inst_item.get("name")
            if inst_name:
                instance_map[inst_name] = {
                    "def_name": inst_item.get("def_name"),
                    "ports": [
                        {
                            "name": p["name"],
                            "direction": p["direction"],
                            "signals": p["signals"],
                        }
                        for p in inst_item["ports"]
                    ],
                }

        instance_records.sort(key=lambda x: x["name"] or "")
        module_instance_map[module_name] = instance_map

        always_blocks = [
            summarize_block(block, "always", file_table)
            for block in module_elem.findall("always")
        ]
        initial_blocks = [
            summarize_block(block, "initial", file_table)
            for block in module_elem.findall("initial")
        ]
        initial_static_blocks = [
            summarize_block(block, "initialstatic", file_table)
            for block in module_elem.findall("initialstatic")
        ]
        task_blocks = [
            summarize_block(block, "task", file_table)
            for block in module_elem.findall("task")
        ]
        cont_assigns = [
            summarize_block(block, "contassign", file_table)
            for block in module_elem.findall("contassign")
        ]

        module_record = {
            "name": module_name,
            "orig_name": module_elem.attrib.get("origName"),
            "is_top_module": module_elem.attrib.get("topModule") == "1",
            "is_public": module_elem.attrib.get("public") == "true",
            "loc": parse_loc(module_elem.attrib.get("loc"), file_table),
            "parameters": params,
            "ports": ports,
            "locals": locals_,
            "instances": instance_records,
            "always_blocks": always_blocks,
            "initial_blocks": initial_blocks,
            "initial_static_blocks": initial_static_blocks,
            "tasks": task_blocks,
            "continuous_assignments": cont_assigns,
            "stats": {
                "parameter_count": len(params),
                "port_count": len(ports),
                "local_count": len(locals_),
                "instance_count": len(instance_records),
                "always_count": len(always_blocks),
                "initial_count": len(initial_blocks),
                "initial_static_count": len(initial_static_blocks),
                "task_count": len(task_blocks),
                "contassign_count": len(cont_assigns),
            },
        }
        module_records.append(module_record)

    module_records.sort(key=lambda x: x["name"])
    return module_records, module_instance_map


def parse_cells_hierarchy(
    root: ET.Element,
    file_table: Dict[str, Dict[str, str]],
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, str]]]:
    cells = root.find("cells")
    if cells is None:
        raise ValueError("XML missing <cells> section")
    top_cell = cells.find("cell")
    if top_cell is None:
        raise ValueError("XML <cells> has no top cell")

    nodes: List[Dict[str, Any]] = []
    hierarchy_edges: List[Dict[str, str]] = []

    def walk(cell: ET.Element, parent_path: Optional[str]) -> None:
        path = cell.attrib.get("hier")
        if not path:
            return
        node = {
            "id": path,
            "path": path,
            "instance": cell.attrib.get("name"),
            "module": cell.attrib.get("submodname"),
            "parent": parent_path,
            "loc": parse_loc(cell.attrib.get("loc"), file_table),
        }
        nodes.append(node)
        if parent_path is not None:
            hierarchy_edges.append(
                {"src": parent_path, "dst": path, "kind": "hierarchy"}
            )
        for child in cell.findall("cell"):
            walk(child, path)

    walk(top_cell, None)
    nodes.sort(key=lambda n: n["path"])
    hierarchy_edges.sort(key=lambda e: (e["src"], e["dst"]))

    top_path = top_cell.attrib.get("hier", "")
    return top_path, nodes, hierarchy_edges


def build_local_connection_edges(
    instances: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    signal_endpoints: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for inst_name, inst_data in instances.items():
        for port in inst_data.get("ports", []):
            direction = str(port.get("direction", "unknown"))
            port_name = str(port.get("name", ""))
            for sig in port.get("signals", []):
                signal_endpoints[str(sig)].append(
                    {
                        "instance": inst_name,
                        "direction": direction,
                        "port": port_name,
                    }
                )

    edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for signal_name, endpoints in signal_endpoints.items():
        producers = [ep for ep in endpoints if ep["direction"] in ("out", "inout")]
        consumers = [ep for ep in endpoints if ep["direction"] in ("in", "inout")]

        if producers and consumers:
            for src_ep in producers:
                for dst_ep in consumers:
                    if src_ep["instance"] == dst_ep["instance"]:
                        continue
                    key = (src_ep["instance"], dst_ep["instance"], "directed")
                    edge = edges.setdefault(
                        key,
                        {
                            "src_instance": src_ep["instance"],
                            "dst_instance": dst_ep["instance"],
                            "kind": "directed",
                            "signals": set(),
                        },
                    )
                    edge["signals"].add(signal_name)
            continue

        uniq_instances = sorted({ep["instance"] for ep in endpoints})
        if len(uniq_instances) <= 1:
            continue
        for i in range(len(uniq_instances)):
            for j in range(i + 1, len(uniq_instances)):
                src = uniq_instances[i]
                dst = uniq_instances[j]
                key = (src, dst, "undirected")
                edge = edges.setdefault(
                    key,
                    {
                        "src_instance": src,
                        "dst_instance": dst,
                        "kind": "undirected",
                        "signals": set(),
                    },
                )
                edge["signals"].add(signal_name)

    result = []
    for edge in edges.values():
        signals = sorted(edge["signals"])
        result.append(
            {
                "src_instance": edge["src_instance"],
                "dst_instance": edge["dst_instance"],
                "kind": edge["kind"],
                "signals": signals,
                "signal_count": len(signals),
            }
        )
    result.sort(key=lambda e: (e["src_instance"], e["dst_instance"], e["kind"]))
    return result


def lift_local_edges_to_hierarchy(
    nodes: List[Dict[str, Any]],
    local_module_edges: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    path_to_module = {
        node["path"]: node["module"]
        for node in nodes
        if node.get("path") and node.get("module")
    }
    known_paths = set(path_to_module)

    lifted: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for parent_path, module_name in path_to_module.items():
        if not module_name:
            continue
        for edge in local_module_edges.get(module_name, []):
            src_path = f"{parent_path}.{edge['src_instance']}"
            dst_path = f"{parent_path}.{edge['dst_instance']}"

            if src_path not in known_paths or dst_path not in known_paths:
                continue

            edge_kind = str(edge["kind"])
            if edge_kind == "undirected" and dst_path < src_path:
                src_path, dst_path = dst_path, src_path

            key = (src_path, dst_path, edge_kind)
            item = lifted.setdefault(
                key,
                {
                    "src": src_path,
                    "dst": dst_path,
                    "kind": edge_kind,
                    "scope": parent_path,
                    "signals": set(),
                },
            )
            item["signals"].update(edge["signals"])

    out = []
    for item in lifted.values():
        signals = sorted(item["signals"])
        out.append(
            {
                "src": item["src"],
                "dst": item["dst"],
                "kind": item["kind"],
                "scope": item["scope"],
                "signals": signals,
                "signal_count": len(signals),
            }
        )
    out.sort(key=lambda e: (e["src"], e["dst"], e["kind"]))
    return out


def extract_deep_architecture(xml_path: Path, config_id: str) -> Dict[str, Any]:
    root = ET.parse(xml_path).getroot()

    file_table = build_file_table(root)
    dtypes = build_dtype_table(root)
    modules, module_instance_map = parse_modules(root, dtypes, file_table)
    top_path, nodes, hierarchy_edges = parse_cells_hierarchy(root, file_table)

    local_edges_by_module = {
        module_name: build_local_connection_edges(instances)
        for module_name, instances in module_instance_map.items()
    }
    connection_edges = lift_local_edges_to_hierarchy(nodes, local_edges_by_module)

    modules_by_name = {m["name"]: m for m in modules}
    for node in nodes:
        module_record = modules_by_name.get(node.get("module"))
        node["module_orig_name"] = (
            module_record.get("orig_name") if module_record else None
        )
        node["module_decl_loc"] = module_record.get("loc") if module_record else None

    top_module_name = next((m["name"] for m in modules if m["is_top_module"]), None)
    top_params = {}
    if top_module_name is not None:
        for p in modules_by_name[top_module_name]["parameters"]:
            top_params[p["name"]] = p.get("default")

    summary = {
        "file_count": len(file_table),
        "dtype_count": len(dtypes),
        "module_count": len(modules),
        "node_count": len(nodes),
        "hierarchy_edge_count": len(hierarchy_edges),
        "connection_edge_count": len(connection_edges),
        "parameter_total": sum(m["stats"]["parameter_count"] for m in modules),
        "port_total": sum(m["stats"]["port_count"] for m in modules),
        "local_signal_total": sum(m["stats"]["local_count"] for m in modules),
    }

    return {
        "config_id": config_id,
        "xml_path": str(xml_path),
        "summary": summary,
        "files": [file_table[file_id] for file_id in sorted(file_table)],
        "top": {
            "hier_path": top_path,
            "module": top_module_name,
            "params": top_params,
        },
        "hierarchy": {
            "nodes": nodes,
            "edges": hierarchy_edges,
        },
        "connectivity": {
            "edges": connection_edges,
        },
        "modules": modules,
    }


def resolve_targets(
    args: argparse.Namespace, repo_root: Path
) -> List[Tuple[str, Path]]:
    arch_dir = (repo_root / args.arch_dir).resolve()

    if args.xml:
        targets = []
        for xml_str in args.xml:
            xml_path = Path(xml_str)
            if not xml_path.is_absolute():
                xml_path = (repo_root / xml_path).resolve()
            if not xml_path.exists():
                raise FileNotFoundError(f"Missing XML: {xml_path}")
            targets.append((xml_path.stem, xml_path))
        return targets

    manifest_path = (
        (repo_root / args.manifest).resolve()
        if args.manifest is not None
        else (arch_dir / "matrix_manifest.json").resolve()
    )
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    manifest = read_json(manifest_path)
    rows = manifest.get("matrix", [])
    if not rows:
        raise ValueError(f"Manifest matrix is empty: {manifest_path}")

    targets = []
    for row in rows:
        config_id = row.get("config_id")
        xml_path_raw = row.get("xml_path")
        if not config_id or not xml_path_raw:
            continue
        xml_path = Path(xml_path_raw)
        if not xml_path.is_absolute():
            xml_path = (repo_root / xml_path).resolve()
        if not xml_path.exists():
            raise FileNotFoundError(f"Missing XML for {config_id}: {xml_path}")
        targets.append((config_id, xml_path))

    return targets


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = (repo_root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = resolve_targets(args, repo_root)

    manifest_rows = []
    for config_id, xml_path in targets:
        deep = extract_deep_architecture(xml_path, config_id)
        out_path = out_dir / f"{config_id}.deep.json"
        write_json(out_path, deep)
        manifest_rows.append(
            {
                "config_id": config_id,
                "xml_path": str(xml_path),
                "deep_json_path": str(out_path),
                "summary": deep["summary"],
            }
        )
        print(
            f"[{config_id}] modules={deep['summary']['module_count']} "
            f"nodes={deep['summary']['node_count']} "
            f"conn={deep['summary']['connection_edge_count']}"
        )

    write_json(out_dir / "deep_manifest.json", {"matrix": manifest_rows})
    print(f"Wrote deep manifest: {out_dir / 'deep_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
