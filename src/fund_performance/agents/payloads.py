"""Views of existing evidence for agents that do not need execution diagnostics."""


def assessment_for_narrative(assessment: dict) -> dict:
    """Preserve all assessment and evidence fields; omit only execution telemetry.

    The complete assessment and diagnostics remain in the run audit record.
    """
    return {k: v for k, v in assessment.items() if k not in ('tool_calls', 'diagnostics')}
