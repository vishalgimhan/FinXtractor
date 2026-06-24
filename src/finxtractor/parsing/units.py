import re
from .text import extract_pages
from ..schemas import Units

_THOUSANDS = re.compile(r"\$\s*['`’]?\s*000|in thousands|amounts? in '?000", re.I)
_MILLIONS  = re.compile(r"\$\s*['`’]?\s*0?m\b|in millions|\$\s*million", re.I)
_AUD = re.compile(r"\bAUD\b|\bA\$|australian dollar", re.I)
_USD = re.compile(r"\bUSD\b|\bUS\$|united states dollar", re.I)
_PAREN_NEG = re.compile(r"\(\s*[\d,]+\s*\)")
_TRAIL_NEG = re.compile(r"[\d,]+\s*-(?:\s|$)")

def detect_units(text: str) -> Units:
    if _MILLIONS.search(text):
        return Units.MILLIONS
    if _THOUSANDS.search(text):
        return Units.THOUSANDS
    return Units.ACTUAL

def detect_currency(text: str) -> str:
    if _USD.search(text):
        return "USD"
    if _AUD.search(text):
        return "AUD"
    return "AUD"

def detect_sign_convention(text: str) -> str:
    if _TRAIL_NEG.search(text) and not _PAREN_NEG.search(text):
        return "trailing_minus"
    return "parentheses_negative"

