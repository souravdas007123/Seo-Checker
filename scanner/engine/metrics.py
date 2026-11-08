"""Title ki pixel width ka andaza (Arial 20px, Google desktop SERP jaisa). Ye ESTIMATE hai, exact nahi."""
from __future__ import annotations

# Arial glyph widths (1000 units per em)
_WIDTHS = {}
for _pair in (
    "a556 b556 c500 d556 e556 f278 g556 h556 i222 j222 k500 l222 m833 n556 o556 p556 q556 r333 s500 t278 "
    "u556 v500 w722 x500 y500 z500 "
    "A667 B667 C722 D722 E667 F611 G778 H722 I278 J500 K667 L556 M833 N722 O778 P667 Q778 R722 S667 T611 "
    "U722 V667 W944 X667 Y667 Z611"
).split():
    _WIDTHS[_pair[0]] = int(_pair[1:])
for _d in "0123456789":
    _WIDTHS[_d] = 556
_WIDTHS.update({" ": 278, ".": 278, ",": 278, ":": 278, ";": 278, "-": 333, "|": 260, "!": 278,
                "?": 556, "&": 667, "'": 191, '"': 355, "(": 333, ")": 333, "/": 278, "_": 556,
                "@": 1015, "%": 889, "+": 584, "–": 556, "—": 1000})

FONT_PX = 20
TITLE_PX_LIMIT = 580


def title_px(text: str) -> int:
    total = 0
    for ch in text:
        if ch in _WIDTHS:
            total += _WIDTHS[ch]
        elif ord(ch) > 0x2E80:  # CJK etc.
            total += 1000
        elif ord(ch) >= 0x0900:  # Indic scripts: rough average
            total += 650
        else:
            total += 560
    return round(total * FONT_PX / 1000)
