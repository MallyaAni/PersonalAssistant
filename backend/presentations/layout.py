"""Content-aware geometry for compiled slides.

Slide boxes were previously fixed, so content that wrapped past its allotted
height simply overflowed: a two-line title was clipped mid-phrase, and six
bullets stacked past the key message and collided with it. Nothing in the
pipeline noticed, because a specification that overflows is still a valid
specification.

These helpers estimate how tall text will actually render and let the compiler
shrink or reflow before emitting geometry, so the deck stays deterministic and
editable rather than depending on renderer autofit.
"""

import math

# Average glyph advance as a fraction of point size for mixed-case body text.
# Deliberately generous: over-estimating width costs a slightly smaller font,
# while under-estimating costs clipped text, which is the failure being fixed.
_CHAR_WIDTH_RATIO = 0.52
# Rendered line pitch relative to point size.
_LINE_PITCH = 1.25
_POINTS_PER_INCH = 72.0


# How many characters of this size fit across one line of the given width.
def characters_per_line(width_inches: float, font_size: float) -> float:
    advance = font_size * _CHAR_WIDTH_RATIO / _POINTS_PER_INCH
    return max(width_inches / advance, 1.0)


# How many lines the text wraps to. Word wrapping never packs a line as tightly
# as a raw character count suggests, so the estimate is rounded up.
def line_count(text: str, width_inches: float, font_size: float) -> int:
    length = len(text.strip())
    if length == 0:
        return 1
    return max(1, math.ceil(length / characters_per_line(width_inches, font_size)))


# The height that many lines occupy, plus the padding a text box needs so
# descenders and the box edge do not touch.
def text_height(lines: int, font_size: float, padding: float = 0.14) -> float:
    return lines * font_size * _LINE_PITCH / _POINTS_PER_INCH + padding


# Height this text needs at this size in this width.
def required_height(
    text: str, width_inches: float, font_size: float, padding: float = 0.14
) -> float:
    return text_height(line_count(text, width_inches, font_size), font_size, padding)


# Largest size at or below `maximum` whose text fits the available height, or
# `minimum` when even that overflows. Returning the floor rather than raising
# keeps a pathological title from failing the whole deck; it will be tight but
# present, which beats a clipped one.
def fit_font_size(
    text: str,
    width_inches: float,
    available_height: float,
    maximum: float,
    minimum: float,
    padding: float = 0.14,
) -> float:
    size = maximum
    while size > minimum:
        if required_height(text, width_inches, size, padding) <= available_height:
            return size
        size -= 1
    return minimum


# Largest size at which every block fits the region once stacked with `gap`
# between them. Used for bullets, where the constraint is the whole column
# rather than any single line.
def fit_stack_font_size(
    texts: list[str],
    width_inches: float,
    available_height: float,
    maximum: float,
    minimum: float,
    gap: float,
    padding: float = 0.14,
) -> float:
    if not texts:
        return maximum
    size = maximum
    while size > minimum:
        total = sum(
            required_height(text, width_inches, size, padding) for text in texts
        ) + gap * (len(texts) - 1)
        if total <= available_height:
            return size
        size -= 1
    return minimum
