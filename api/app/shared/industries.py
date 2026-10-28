"""
The fixed industry list the LLM prompts classify jobs into.

This is the single source of truth: prompts reference it through the
{{INDUSTRIES}} placeholder (see app/shared/prompts.py), so adding an industry
means editing this list only. Keep existing names and their order stable —
stored `inferred_industries` values and profile `target_industries` use them.
"""

INDUSTRIES: tuple[str, ...] = (
    "Technology & Software",
    "Banking & Financial Services",
    "Capital Markets & Investment Management",
    "Consulting & Professional Services",
    "Government & Public Sector",
    "Healthcare & Life Sciences",
    "Real Estate & Infrastructure",
    "Supply Chain & Logistics",
    "Media, Marketing & Communications",
    "Insurance",
    "Energy & Resources",
    "Education",
    "Manufacturing & Engineering",
    "Telecommunications",
    "Non-profit & Social Services",
    "Sports & Recreation",
)

_PER_LINE = 3
_CONTINUATION_INDENT = "  "


def render_industries() -> str:
    """Backticked, comma-separated names, three per line, for embedding in a prompt."""
    names = [f"`{name}`" for name in INDUSTRIES]
    lines = [", ".join(names[i:i + _PER_LINE]) for i in range(0, len(names), _PER_LINE)]
    return (",\n" + _CONTINUATION_INDENT).join(lines)
