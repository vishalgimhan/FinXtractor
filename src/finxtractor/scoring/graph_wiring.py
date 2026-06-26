import networkx as nx
from .schemas import Ratio, AltmanResult, CompositeScore
from .schemas import MetricInput

def _line_item_node_for(G: nx.DiGraph, account: str) -> str | None:
    """Find the graph's line-item node whose canonical account matches."""
    for n, d in G.nodes(data=True):
        if d.get("kind") == "line_item" and d.get("account") == account:
            return n
    return None


def wire_scoring(G: nx.DiGraph, ratios: list[Ratio], altman: AltmanResult,
                 composite: CompositeScore) -> nx.DiGraph:
    score_id = "score:composite"
    G.add_node(score_id, kind="score", value=float(composite.score_0_100 or 0),
               grade=composite.grade)

    for r in ratios + ([_altman_as_pseudo_ratio(altman)] if altman.z_double_prime else []):
        rid = f"ratio:{r.name}"
        G.add_node(rid, kind="ratio", value=float(r.value) if r.value is not None else None)
        G.add_edge(score_id, rid, rel="contributes-to-score")
        for inp in r.inputs:
            li = _line_item_node_for(G, inp.account)
            if li:
                G.add_edge(rid, li, rel="derived-into-ratio",
                           page=inp.page, bbox=inp.bbox)
    return G

def _altman_as_pseudo_ratio(a: AltmanResult) -> Ratio:
    return Ratio(name="altman_zscore", value=a.z_double_prime,
                 formula="6.56·X1+3.26·X2+6.72·X3+1.05·X4", inputs=a.inputs)


def trace_score(G: nx.DiGraph) -> dict:
    """Walk score -> ratios -> line items -> page/bbox. The explainability payload."""
    score_id = "score:composite"
    if score_id not in G:
        return {}
    out = {"score": G.nodes[score_id]["value"], "grade": G.nodes[score_id]["grade"], "ratios": []}
    for _, rid, _ in G.out_edges(score_id, data=True):
        sources = []
        for _, li, ed in G.out_edges(rid, data=True):
            if ed["rel"] == "derived-into-ratio":
                sources.append({"label": G.nodes[li]["label"], "account": G.nodes[li]["account"],
                                "page": ed.get("page"), "bbox": ed.get("bbox")})
        out["ratios"].append({"ratio": G.nodes[rid]["kind"] and rid.split(":")[1],
                              "value": G.nodes[rid]["value"], "sources": sources})
    return out