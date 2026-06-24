import networkx as nx


def _find_line_item(G: nx.DiGraph, label_query: str) -> str | None:
    q = label_query.lower()
    matches = [n for n, d in G.nodes(data=True)
               if d.get("kind") == "line_item" and q in d["label"].lower()]
    matches.sort(key=lambda n: len(G.nodes[n]["label"]))   # shortest label = closest match
    return matches[0] if matches else None


def drill_down(G: nx.DiGraph, label_query: str) -> dict:
    """Full breakdown behind a line item: its values + the notes it cites + their sub-items."""
    lid = _find_line_item(G, label_query)
    if lid is None:
        return {"query": label_query, "found": False}

    values = [G.nodes[v] for _, v, d in G.out_edges(lid, data=True) if d["rel"] == "has-value"]
    notes = []
    for _, nid, d in G.out_edges(lid, data=True):
        if d["rel"] != "references-note":
            continue
        sub_rows = [G.nodes[s]["row"] for _, s, e in G.out_edges(nid, data=True)
                    if e["rel"] == "has-sub-item"]
        notes.append({"note": G.nodes[nid]["number"], "sub": d.get("sub"),
                      "page": G.nodes[nid]["page"], "rows": sub_rows})
    return {"query": label_query, "found": True, "label": G.nodes[lid]["label"],
            "values": values, "notes": notes}

def referencing_line_items(G: nx.DiGraph, note_number: int) -> dict:
    """Which line items cite a given note (with the sub-section each points at)."""
    nid = f"note:{note_number}"
    if nid not in G:
        return {"note": note_number, "found": False, "items": []}
    items = [{"label": G.nodes[u]["label"], "sub": d.get("sub")}
             for u, _, d in G.in_edges(nid, data=True) if d["rel"] == "references-note"]
    return {"note": note_number, "found": True, "items": items}