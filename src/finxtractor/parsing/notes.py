import re
from ..schemas.note import NoteRef

_FOOTNOTE_MARKERS = re.compile(r"[*†‡§¶#]")                 # strip; not note numbers
_TOKEN_SPLIT = re.compile(r"\s*(?:,|&|/| and )\s*", re.I)   # 4, 5 | 4 & 5 | 4 and 5
_RANGE = re.compile(r"^(\d{1,2})\s*[-–—]\s*(\d{1,2})$")     # 4-5 | 5–7 (hyphen/en/em)
_SINGLE = re.compile(r"^(\d{1,2})\s*(?:\(\s*([a-z])\s*\))?$", re.I)  # 4 | 3(e)

def _parse_token(token: str) -> list[NoteRef]:
    token = token.strip()
    if not token:
        return []
    m = _RANGE.match(token)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= hi and hi - lo <= 20:                     # sane range guard
            return [NoteRef(number=n) for n in range(lo, hi + 1)]
        return []
    m = _SINGLE.match(token)
    if m:
        sub = m.group(2).lower() if m.group(2) else None
        return [NoteRef(number=int(m.group(1)), sub=sub)]
    return []     

def parse_note_refs(raw: str | None) -> list[NoteRef]:
    if not raw:
        return []
    cleaned = _FOOTNOTE_MARKERS.sub("", raw).strip()
    refs, seen = [], set()
    for token in _TOKEN_SPLIT.split(cleaned):
        for ref in _parse_token(token):
            if ref.key() not in seen:                      # dedupe by canonical key
                seen.add(ref.key())
                refs.append(ref)
    return refs

def resolve_line_item_notes(stmt) -> None:
    """Fill each line item's structured note_refs from its raw note string."""
    for item in stmt.line_items:
        item.note_refs = parse_note_refs(item.note_ref_raw)