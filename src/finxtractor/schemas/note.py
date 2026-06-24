from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class NoteRef(BaseModel):
    number: int                      # the parent note, e.g. 3
    sub: Optional[str] = None        # sub-section letter, e.g. "e"; None if whole note

    def key(self) -> str:
        return f"{self.number}{f'({self.sub})' if self.sub else ''}"