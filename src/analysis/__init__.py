"""BetVector analysis — narrative generation and match insights.

This package synthesises raw model output and feature data into
human-readable explanations.  The primary entry point is
:func:`narrative.generate_match_narrative`, which takes the data dict
from ``match_detail.load_match_data()`` and returns a structured
``MatchNarrative`` ready for rendering in the dashboard or email.
"""
