#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


REQUIRED_DOMAINS = ["IFU", "LSU", "MMU", "CSR", "PMP"]


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add semantic domain tags and security clusters for picorv32 arch outputs"
    )
    parser.add_argument(
        "--arch-dir",
        default="build_result/arch",
        help="Directory with matrix_manifest.json and *.arch.json",
    )
    parser.add_argument(
        "--baseline",
        default="p32_c2_sb0_bp0_cs1_fd1",
        help="Baseline config id for comparative notes",
    )
    return parser.parse_args(list(argv))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def classify_node(node: Dict[str, Any]) -> Dict[str, Any]:
    module = str(node.get("module", ""))
    inst = str(node.get("instance", ""))
    path = str(node.get("path", ""))
    text = f"{module} {inst} {path}".lower()

    domains: List[str] = []
    reasons: List[str] = []

    if "pmp" in text:
        domains.append("PMP")
        reasons.append("name contains pmp")
    if "csr" in text:
        domains.append("CSR")
        reasons.append("name contains csr")
    if "mmu" in text or "tlb" in text:
        domains.append("MMU")
        reasons.append("name contains mmu/tlb")
    if "ifu" in text or "fetch" in text or "icache" in text:
        domains.append("IFU")
        reasons.append("name contains ifu/fetch/icache")
    if (
        "lsu" in text
        or "load" in text
        or "store" in text
        or "axi_adapter" in text
        or "dbus" in text
    ):
        domains.append("LSU")
        reasons.append("name indicates load/store or bus adapter")
    if "arbiter" in text or "xbar" in text or "axi_arb" in text:
        domains.append("INTERCONNECT")
        reasons.append("name indicates shared interconnect")
    if "memory" in text or module == "axi4_memory" or inst == "mem":
        domains.append("MEMORY")
        reasons.append("name indicates memory backend")
    if "pcpi_mul" in text or "pcpi_div" in text or " mul" in text or " div" in text:
        domains.append("EXECUTE")
        reasons.append("name indicates arithmetic execute extension")
    if module.startswith("picorv32_axi"):
        domains.append("CORE")
        reasons.append("name indicates per-hart core shell")
    if module.startswith("picorv32__") or "picorv32_core" in text:
        domains.append("CORE")
        reasons.append("name indicates core pipeline")
    if (
        node.get("parent") is None
        or inst.endswith("wrapper")
        or module.endswith("wrapper")
    ):
        domains.append("SOC_TOP")
        reasons.append("top-level wrapper")

    if not domains:
        domains = ["UNCLASSIFIED"]
        reasons = ["no heuristic match"]

    primary_order = [
        "PMP",
        "CSR",
        "MMU",
        "IFU",
        "LSU",
        "INTERCONNECT",
        "MEMORY",
        "EXECUTE",
        "CORE",
        "SOC_TOP",
        "UNCLASSIFIED",
    ]
    primary = next((d for d in primary_order if d in domains), domains[0])

    return {
        "path": path,
        "instance": inst,
        "module": module,
        "primary_domain": primary,
        "domains": sorted(
            set(domains),
            key=lambda d: primary_order.index(d) if d in primary_order else 99,
        ),
        "reasons": reasons,
    }


def domain_presence(annotations: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_domain: Dict[str, List[str]] = {d: [] for d in REQUIRED_DOMAINS}
    core_nodes = [a["path"] for a in annotations if a["primary_domain"] == "CORE"]

    for ann in annotations:
        path = ann["path"]
        for d in ann["domains"]:
            if d in by_domain:
                by_domain[d].append(path)

    result: Dict[str, Dict[str, Any]] = {}
    for d in REQUIRED_DOMAINS:
        explicit = sorted(set(by_domain[d]))
        if explicit:
            result[d] = {
                "state": "explicit",
                "evidence_nodes": explicit,
                "note": "dedicated module names detected",
            }
            continue

        if d in ("IFU", "LSU", "CSR") and core_nodes:
            result[d] = {
                "state": "implicit",
                "evidence_nodes": sorted(set(core_nodes)),
                "note": "no dedicated block name; likely integrated in core pipeline",
            }
            continue

        result[d] = {
            "state": "absent",
            "evidence_nodes": [],
            "note": "not observed in elaborated hierarchy",
        }

    return result


def node_set_by_primary(annotations: List[Dict[str, Any]], domain: str) -> Set[str]:
    return {a["path"] for a in annotations if a["primary_domain"] == domain}


def cluster_memory_ordering(
    config_id: str,
    params: Dict[str, Dict[str, Any]],
    annotations: List[Dict[str, Any]],
    connection_edges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    stbuf = int(params.get("STBUF_ENABLE", {}).get("int", 0) or 0)
    bypass = int(params.get("STBUF_ALLOW_LOAD_BYPASS", {}).get("int", 0) or 0)
    fence_drain = int(params.get("FENCE_DRAIN_STBUF", {}).get("int", 1) or 0)

    if stbuf == 1 and fence_drain == 0:
        risk = "high"
    elif stbuf == 1 and bypass == 1:
        risk = "high"
    elif stbuf == 1:
        risk = "medium"
    else:
        risk = "low"

    cluster_nodes = set()
    for d in ("CORE", "LSU", "INTERCONNECT", "MEMORY"):
        cluster_nodes.update(node_set_by_primary(annotations, d))

    edge_count = 0
    for e in connection_edges:
        if e["src"] in cluster_nodes and e["dst"] in cluster_nodes:
            edge_count += 1

    concerns = []
    if stbuf == 1:
        concerns.append(
            "store buffer enabled: memory visibility can deviate from strict in-order commit"
        )
    if bypass == 1:
        concerns.append(
            "load bypass enabled: stale/forwarded-read corner cases require dedicated checks"
        )
    if fence_drain == 0:
        concerns.append(
            "fence drain disabled: stronger ordering assumptions may no longer hold"
        )
    if not concerns:
        concerns.append("baseline ordering path still requires litmus and fence checks")

    return {
        "cluster_id": "memory_ordering_visibility",
        "config_id": config_id,
        "risk": risk,
        "nodes": sorted(cluster_nodes),
        "edge_count": edge_count,
        "params": {
            "STBUF_ENABLE": stbuf,
            "STBUF_ALLOW_LOAD_BYPASS": bypass,
            "FENCE_DRAIN_STBUF": fence_drain,
        },
        "concerns": concerns,
        "recommended_checks": [
            "dual-hart store/load litmus with deterministic outcome checks",
            "fence progress and visibility assertions around shared addresses",
            "differential run across default/sb/sb-bypass/sb-fence-nop with same seeds",
        ],
    }


def cluster_shared_fabric(
    config_id: str,
    params: Dict[str, Dict[str, Any]],
    annotations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    cores = int(params.get("NUM_CORES", {}).get("int", 0) or 0)
    interconnect_nodes = sorted(node_set_by_primary(annotations, "INTERCONNECT"))
    core_shell_nodes = sorted(
        a["path"]
        for a in annotations
        if a["instance"].startswith("uut") or a["module"].startswith("picorv32_axi")
    )

    if cores >= 2:
        risk = "medium"
    else:
        risk = "low"

    return {
        "cluster_id": "shared_interconnect_isolation",
        "config_id": config_id,
        "risk": risk,
        "nodes": sorted(set(interconnect_nodes + core_shell_nodes)),
        "params": {"NUM_CORES": cores},
        "concerns": [
            "shared arbitration can hide starvation and fairness regressions",
            "cross-hart bus interactions can mask attribution bugs",
        ],
        "recommended_checks": [
            "arbiter fairness assertions under sustained dual-core pressure",
            "per-hart request/response attribution scoreboards",
        ],
    }


def cluster_interrupt_trap(
    config_id: str, annotations: List[Dict[str, Any]]
) -> Dict[str, Any]:
    top_nodes = sorted(node_set_by_primary(annotations, "SOC_TOP"))
    core_nodes = sorted(node_set_by_primary(annotations, "CORE"))
    risk = "medium" if core_nodes else "low"
    return {
        "cluster_id": "interrupt_trap_control",
        "config_id": config_id,
        "risk": risk,
        "nodes": sorted(set(top_nodes + core_nodes)),
        "concerns": [
            "shared IRQ/trap paths can cause cross-hart interference if not isolated",
            "trap completion conditions can hide partial-pass conditions",
        ],
        "recommended_checks": [
            "trap completion policy assertions for all harts",
            "interrupt delivery consistency checks under concurrent traffic",
        ],
    }


def cluster_exec_extensions(
    config_id: str, annotations: List[Dict[str, Any]]
) -> Dict[str, Any]:
    exec_nodes = sorted(node_set_by_primary(annotations, "EXECUTE"))
    risk = "medium" if exec_nodes else "low"
    return {
        "cluster_id": "execute_extension_surface",
        "config_id": config_id,
        "risk": risk,
        "nodes": exec_nodes,
        "concerns": [
            "mul/div extension handshakes are high-value targets for timeout/state bugs",
            "long-latency execute blocks can expose corner-case control hazards",
        ],
        "recommended_checks": [
            "pcpi handshake liveness assertions",
            "m-extension differential tests with random stalls",
        ],
    }


def build_config_semantic(arch: Dict[str, Any], baseline_id: str) -> Dict[str, Any]:
    config_id = arch["config_id"]
    params = arch.get("params", {})
    annotations = [classify_node(n) for n in arch["nodes"]]
    presence = domain_presence(annotations)

    clusters = [
        cluster_memory_ordering(
            config_id, params, annotations, arch.get("connection_edges", [])
        ),
        cluster_shared_fabric(config_id, params, annotations),
        cluster_interrupt_trap(config_id, annotations),
        cluster_exec_extensions(config_id, annotations),
    ]

    max_risk = "low"
    risk_order = {"low": 0, "medium": 1, "high": 2}
    for c in clusters:
        if risk_order[c["risk"]] > risk_order[max_risk]:
            max_risk = c["risk"]

    return {
        "config_id": config_id,
        "baseline": baseline_id,
        "key_params": {
            "NUM_CORES": int(params.get("NUM_CORES", {}).get("int", 0) or 0),
            "STBUF_ENABLE": int(params.get("STBUF_ENABLE", {}).get("int", 0) or 0),
            "STBUF_ALLOW_LOAD_BYPASS": int(
                params.get("STBUF_ALLOW_LOAD_BYPASS", {}).get("int", 0) or 0
            ),
            "STBUF_CONFLICT_STALL": int(
                params.get("STBUF_CONFLICT_STALL", {}).get("int", 0) or 0
            ),
            "FENCE_DRAIN_STBUF": int(
                params.get("FENCE_DRAIN_STBUF", {}).get("int", 0) or 0
            ),
        },
        "domain_presence": presence,
        "node_annotations": annotations,
        "security_clusters": clusters,
        "overall_risk": max_risk,
    }


def build_report(semantics: Dict[str, Any], baseline: str) -> str:
    lines: List[str] = []
    lines.append("# Picorv32 Architecture Semantic + Security Report")
    lines.append("")
    lines.append(f"Baseline config: `{baseline}`")
    lines.append("")
    lines.append("## Config matrix")
    lines.append("")
    lines.append("| config_id | cores | stbuf | bypass | fence_drain | overall_risk |")
    lines.append("|---|---:|---:|---:|---:|---|")

    cfg_rows = sorted(semantics["configs"], key=lambda c: c["config_id"])
    for cfg in cfg_rows:
        p = cfg["key_params"]
        lines.append(
            "| "
            + f"{cfg['config_id']} | {p['NUM_CORES']} | {p['STBUF_ENABLE']} | "
            + f"{p['STBUF_ALLOW_LOAD_BYPASS']} | {p['FENCE_DRAIN_STBUF']} | {cfg['overall_risk']} |"
        )

    lines.append("")
    lines.append("## Domain presence (required domains)")
    lines.append("")
    for cfg in cfg_rows:
        lines.append(f"### {cfg['config_id']}")
        for d in REQUIRED_DOMAINS:
            st = cfg["domain_presence"][d]["state"]
            note = cfg["domain_presence"][d]["note"]
            lines.append(f"- {d}: {st} ({note})")
        lines.append("")

    lines.append("## Security clusters")
    lines.append("")
    for cfg in cfg_rows:
        lines.append(f"### {cfg['config_id']}")
        for cluster in cfg["security_clusters"]:
            lines.append(
                f"- [{cluster['risk']}] {cluster['cluster_id']} (nodes={len(cluster['nodes'])})"
            )
            for concern in cluster["concerns"]:
                lines.append(f"  - concern: {concern}")
            for check in cluster["recommended_checks"][:2]:
                lines.append(f"  - check: {check}")
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- For this picorv32 matrix, structural hierarchy is largely stable across presets."
    )
    lines.append(
        "- Main security delta comes from memory-ordering parameters, not module add/remove."
    )
    lines.append(
        "- Next migration target should be ibex/rocket-chip for explicit MMU/CSR/PMP blocks."
    )
    lines.append("")

    return "\n".join(lines)


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    arch_dir = (repo_root / args.arch_dir).resolve()
    vis_dir = arch_dir / "visuals"
    manifest_path = arch_dir / "matrix_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    manifest = read_json(manifest_path)
    rows = manifest.get("matrix", [])
    if not rows:
        raise ValueError("Manifest matrix is empty")

    configs: List[Dict[str, Any]] = []
    known_ids = set()
    for row in rows:
        cfg = row["config_id"]
        known_ids.add(cfg)
        arch_json = Path(row["json_path"])
        if not arch_json.exists():
            raise FileNotFoundError(f"Missing arch json: {arch_json}")
        arch = read_json(arch_json)
        configs.append(build_config_semantic(arch, args.baseline))

    if args.baseline not in known_ids:
        raise ValueError(f"Baseline config '{args.baseline}' not in matrix")

    semantics = {
        "baseline": args.baseline,
        "config_count": len(configs),
        "configs": sorted(configs, key=lambda c: c["config_id"]),
    }

    vis_dir.mkdir(parents=True, exist_ok=True)
    write_json(vis_dir / "matrix_semantic_annotations.json", semantics)

    cluster_index: Dict[str, List[Dict[str, Any]]] = {}
    for cfg in semantics["configs"]:
        for cluster in cfg["security_clusters"]:
            cid = cluster["cluster_id"]
            cluster_index.setdefault(cid, []).append(
                {
                    "config_id": cfg["config_id"],
                    "risk": cluster["risk"],
                    "node_count": len(cluster["nodes"]),
                    "concerns": cluster["concerns"],
                }
            )
    write_json(vis_dir / "matrix_security_clusters.json", cluster_index)

    report_text = build_report(semantics, args.baseline)
    write_text(vis_dir / "architecture_security_report.md", report_text)

    print(f"Wrote semantic annotations: {vis_dir / 'matrix_semantic_annotations.json'}")
    print(f"Wrote security clusters: {vis_dir / 'matrix_security_clusters.json'}")
    print(f"Wrote report: {vis_dir / 'architecture_security_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
