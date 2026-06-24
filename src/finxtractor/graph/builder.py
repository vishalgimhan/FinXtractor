import json
from pathlib import Path
import networkx as nx
from networkx.readwrite import json_graph

from ..schemas import Statement
from ..parsing.note_tables import collect_note_tables


def _li_id(i: int) -> str:      return f"li:{i}"
def _note_id(n: int) -> str:    return f"note:{n}"
def _sub_id(n: int, r: int) -> str:  return f"sub:{n}:{r}"
def _val_id(owner: str, yr) -> str:  return f"val:{owner}:{yr}"

# Each line item is a node, each value is a node, each note is a node, and edges connect them.

def _add_line_items(G: nx.DiGraph, stmt: Statement) -> None:
    for i, item in enumerate(stmt.line_items):
        lid = _li_id(i)
        G.add_node(lid, kind="line_item", label=item.label_raw,
                   is_subtotal=item.is_subtotal, page=item.page)
        for slot in ("current", "prior"):
            amount = getattr(item, f"value_{slot}")
            if amount is None:
                continue
            yr = getattr(stmt, f"year_{slot}") or slot
            vid = _val_id(lid, yr)
            G.add_node(vid, kind="value", year=yr, amount=amount)
            G.add_edge(lid, vid, rel="has-value")

def _add_notes(G: nx.DiGraph, stmt: Statement, note_tables: dict) -> None:
    for n, data in note_tables.items():
        nid = _note_id(n)
        G.add_node(nid, kind="note", number=n,
                   page=data["page"], found=data["found"])
        for r, row in enumerate(data["rows"]):
            sid = _sub_id(n, r)
            G.add_node(sid, kind="sub_item", row=row)
            G.add_edge(nid, sid, rel="has-sub-item")

    for i, item in enumerate(stmt.line_items):
        for ref in item.note_refs:
            nid = _note_id(ref.number)
            if nid in G:
                G.add_edge(_li_id(i), nid, rel="references-note", sub=ref.sub)

# Orchestrator
def build_graph(stmt: Statement, pdf: Path | str) -> nx.DiGraph:
    G = nx.DiGraph()
    note_tables = collect_note_tables(stmt, pdf)
    _add_line_items(G, stmt)
    _add_notes(G, stmt, note_tables)
    return G

def graph_to_json(G: nx.DiGraph) -> str:
    data = json_graph.node_link_data(G, edges="edges")
    return json.dumps(data, indent=2, default=str)

def graph_from_json(s: str) -> nx.DiGraph:
    return json_graph.node_link_graph(json.loads(s), directed=True, edges="edges")