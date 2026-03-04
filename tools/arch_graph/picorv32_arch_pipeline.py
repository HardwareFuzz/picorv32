#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


PRESET_VALUES = {
    "default": {
        "STBUF_ENABLE": 0,
        "STBUF_ALLOW_LOAD_BYPASS": 0,
        "STBUF_CONFLICT_STALL": 1,
        "FENCE_DRAIN_STBUF": 1,
    },
    "sb": {
        "STBUF_ENABLE": 1,
        "STBUF_ALLOW_LOAD_BYPASS": 0,
        "STBUF_CONFLICT_STALL": 1,
        "FENCE_DRAIN_STBUF": 1,
    },
    "sb-bypass": {
        "STBUF_ENABLE": 1,
        "STBUF_ALLOW_LOAD_BYPASS": 1,
        "STBUF_CONFLICT_STALL": 1,
        "FENCE_DRAIN_STBUF": 1,
    },
    "sb-fence-nop": {
        "STBUF_ENABLE": 1,
        "STBUF_ALLOW_LOAD_BYPASS": 0,
        "STBUF_CONFLICT_STALL": 1,
        "FENCE_DRAIN_STBUF": 0,
    },
}


DEFAULT_MATRIX = [
    "1:default",
    "2:default",
    "2:sb",
    "2:sb-bypass",
    "2:sb-fence-nop",
]


SV_CONST_RE = re.compile(r"^(?:(\d+)'([sS]?[hdb])([0-9a-fA-F_xzXZ]+)|(\d+))$")


def preset_flags(preset: str) -> List[str]:
    if preset == "default":
        return []
    if preset == "sb":
        return ["-GSTBUF_ENABLE=1"]
    if preset == "sb-bypass":
        return [
            "-GSTBUF_ENABLE=1",
            "-GSTBUF_ALLOW_LOAD_BYPASS=1",
            "-GSTBUF_CONFLICT_STALL=1",
        ]
    if preset == "sb-fence-nop":
        return ["-GSTBUF_ENABLE=1", "-GFENCE_DRAIN_STBUF=0"]
    raise ValueError(f"Unsupported preset: {preset}")


def parse_matrix_entry(entry: str) -> Tuple[int, str]:
    if ":" not in entry:
        raise ValueError(f"Invalid matrix entry '{entry}', expected '<cores>:<preset>'")
    cores_str, preset = entry.split(":", 1)
    try:
        cores = int(cores_str)
    except ValueError as exc:
        raise ValueError(f"Invalid core count in matrix entry '{entry}'") from exc
    if cores <= 0:
        raise ValueError(f"Core count must be positive in matrix entry '{entry}'")
    if preset not in PRESET_VALUES:
        raise ValueError(
            f"Unknown preset '{preset}' in matrix entry '{entry}', "
            f"supported: {', '.join(sorted(PRESET_VALUES))}"
        )
    return cores, preset


def make_config_id(cores: int, preset: str) -> str:
    vals = PRESET_VALUES[preset]
    return (
        f"p32_c{cores}_sb{vals['STBUF_ENABLE']}_bp{vals['STBUF_ALLOW_LOAD_BYPASS']}"
        f"_cs{vals['STBUF_CONFLICT_STALL']}_fd{vals['FENCE_DRAIN_STBUF']}"
    )


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


def run_verilator_xml(
    repo_root: Path,
    verilator: str,
    top_module: str,
    cores: int,
    preset: str,
    xml_path: Path,
) -> str:
    cmd = [
        verilator,
        "--xml-only",
        "--xml-output",
        str(xml_path),
        "--top-module",
        top_module,
        "testbench.v",
        "picorv32.v",
        "-DVERBOSE_DEBUG",
        "-DREGS_INIT_ZERO=1",
        f"-GNUM_CORES={cores}",
        "-Wno-fatal",
    ] + preset_flags(preset)

    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    log_text = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError(
            f"Verilator failed for preset={preset}, cores={cores}, exit={completed.returncode}\n"
            f"Command: {' '.join(cmd)}\n"
            f"Output:\n{log_text}"
        )
    return log_text


def parse_cells_hierarchy(
    root: ET.Element,
) -> Tuple[str, List[Dict[str, Optional[str]]], List[Dict[str, str]]]:
    cells = root.find("cells")
    if cells is None:
        raise ValueError("XML missing <cells> section")
    top_cell = cells.find("cell")
    if top_cell is None:
        raise ValueError("XML <cells> has no top cell")

    nodes: List[Dict[str, Optional[str]]] = []
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
        }
        nodes.append(node)
        if parent_path is not None:
            hierarchy_edges.append(
                {
                    "src": parent_path,
                    "dst": path,
                    "kind": "hierarchy",
                }
            )
        for child in cell.findall("cell"):
            walk(child, path)

    walk(top_cell, None)
    top_path = top_cell.attrib.get("hier", "")
    return top_path, nodes, hierarchy_edges


def normalize_port_direction(raw: str) -> str:
    raw = raw.lower()
    if raw == "out":
        return "out"
    if raw == "in":
        return "in"
    if raw == "inout":
        return "inout"
    return "unknown"


def parse_module_instances(root: ET.Element) -> Dict[str, Dict[str, Dict[str, object]]]:
    netlist = root.find("netlist")
    if netlist is None:
        raise ValueError("XML missing <netlist> section")

    modules: Dict[str, Dict[str, Dict[str, object]]] = {}
    for module in netlist.findall("module"):
        module_name = module.attrib.get("name")
        if not module_name:
            continue
        inst_map: Dict[str, Dict[str, object]] = {}
        for instance in module.findall("instance"):
            inst_name = instance.attrib.get("name")
            if not inst_name:
                continue
            ports = []
            for port in instance.findall("port"):
                signals = sorted(
                    {
                        varref.attrib["name"]
                        for varref in port.findall(".//varref")
                        if "name" in varref.attrib
                    }
                )
                if not signals:
                    continue
                ports.append(
                    {
                        "name": port.attrib.get("name"),
                        "direction": normalize_port_direction(
                            port.attrib.get("direction", "unknown")
                        ),
                        "signals": signals,
                    }
                )
            inst_map[inst_name] = {
                "def_name": instance.attrib.get("defName"),
                "ports": ports,
            }
        modules[module_name] = inst_map
    return modules


def build_local_connection_edges(
    instances: Dict[str, Dict[str, object]],
) -> List[Dict[str, object]]:
    signal_endpoints: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for inst_name, inst_data in instances.items():
        ports = inst_data.get("ports", [])
        for port in ports:
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

    edges: Dict[Tuple[str, str, str], Dict[str, object]] = {}

    for signal_name, endpoints in signal_endpoints.items():
        producers = [e for e in endpoints if e["direction"] in ("out", "inout")]
        consumers = [e for e in endpoints if e["direction"] in ("in", "inout")]

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

        uniq_instances = sorted({e["instance"] for e in endpoints})
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
    nodes: List[Dict[str, Optional[str]]],
    local_module_edges: Dict[str, List[Dict[str, object]]],
) -> List[Dict[str, object]]:
    path_to_module = {
        n["path"]: n["module"] for n in nodes if n.get("path") and n.get("module")
    }
    known_paths = set(path_to_module)
    lifted: Dict[Tuple[str, str, str], Dict[str, object]] = {}

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


def extract_top_module_params(root: ET.Element) -> Dict[str, Dict[str, Optional[int]]]:
    netlist = root.find("netlist")
    if netlist is None:
        return {}
    top_module = None
    for module in netlist.findall("module"):
        if module.attrib.get("topModule") == "1":
            top_module = module
            break
    if top_module is None:
        return {}

    params: Dict[str, Dict[str, Optional[int]]] = {}
    for var in top_module.findall("var"):
        if var.attrib.get("param") != "true":
            continue
        name = var.attrib.get("name")
        if not name:
            continue
        const = var.find("const")
        raw = const.attrib.get("name") if const is not None else None
        params[name] = {"raw": raw, "int": sv_const_to_int(raw)}
    return params


def extract_architecture(
    xml_path: Path, config_id: str, preset: str, cores: int
) -> Dict[str, object]:
    root = ET.parse(xml_path).getroot()
    top_path, nodes, hierarchy_edges = parse_cells_hierarchy(root)
    module_instances = parse_module_instances(root)
    local_edges_by_module = {
        module_name: build_local_connection_edges(instances)
        for module_name, instances in module_instances.items()
    }
    connection_edges = lift_local_edges_to_hierarchy(nodes, local_edges_by_module)
    params = extract_top_module_params(root)

    return {
        "config_id": config_id,
        "preset": preset,
        "cores": cores,
        "xml_path": str(xml_path),
        "top_path": top_path,
        "params": params,
        "summary": {
            "node_count": len(nodes),
            "hierarchy_edge_count": len(hierarchy_edges),
            "connection_edge_count": len(connection_edges),
            "module_type_count": len({n["module"] for n in nodes if n.get("module")}),
        },
        "nodes": nodes,
        "hierarchy_edges": hierarchy_edges,
        "connection_edges": connection_edges,
    }


def write_json(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate config-specific picorv32 XML and extract hierarchy/connectivity graph JSON"
    )
    parser.add_argument(
        "--matrix",
        nargs="+",
        default=DEFAULT_MATRIX,
        help="List of '<cores>:<preset>' entries (preset in default/sb/sb-bypass/sb-fence-nop)",
    )
    parser.add_argument(
        "--out-dir",
        default="build_result/arch",
        help="Output directory for XML and JSON",
    )
    parser.add_argument(
        "--verilator", default="verilator", help="Verilator executable path"
    )
    parser.add_argument(
        "--top-module",
        default="picorv32_wrapper",
        help="Top module passed to Verilator",
    )
    parser.add_argument(
        "--skip-elab",
        action="store_true",
        help="Skip Verilator and parse existing XML files",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force re-run Verilator even if XML exists"
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = (repo_root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    matrix = [parse_matrix_entry(e) for e in args.matrix]
    manifest = []

    for cores, preset in matrix:
        config_id = make_config_id(cores, preset)
        xml_path = out_dir / f"{config_id}.xml"
        log_path = out_dir / f"{config_id}.verilator.log"

        if not args.skip_elab and (args.force or not xml_path.exists()):
            log_text = run_verilator_xml(
                repo_root=repo_root,
                verilator=args.verilator,
                top_module=args.top_module,
                cores=cores,
                preset=preset,
                xml_path=xml_path,
            )
            log_path.write_text(log_text, encoding="utf-8")
        elif not xml_path.exists():
            raise FileNotFoundError(
                f"Missing XML: {xml_path} (disable --skip-elab or generate first)"
            )

        arch = extract_architecture(
            xml_path=xml_path, config_id=config_id, preset=preset, cores=cores
        )
        arch_json_path = out_dir / f"{config_id}.arch.json"
        write_json(arch_json_path, arch)

        manifest.append(
            {
                "config_id": config_id,
                "preset": preset,
                "cores": cores,
                "xml_path": str(xml_path),
                "json_path": str(arch_json_path),
                "summary": arch["summary"],
            }
        )
        print(
            f"[{config_id}] nodes={arch['summary']['node_count']} "
            f"hier={arch['summary']['hierarchy_edge_count']} "
            f"conn={arch['summary']['connection_edge_count']}"
        )

    write_json(out_dir / "matrix_manifest.json", {"matrix": manifest})
    print(f"Wrote manifest: {out_dir / 'matrix_manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
