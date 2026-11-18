"""One bounded representation budget shared by provider and semantic validation."""

def characters(role, payload):
    if payload.get('narrative_contract'):
        return 38000
    calibrated_validation = (
        role == 'validation'
        and payload.get('analysis_stage') in {'perspective_validation', 'final_validation'}
        and (payload.get('decision_policy') or {}).get('schema_version') == 'mara.decision-calibration/1.0'
    )
    # Calibrated analysis preserves question/gap, request, knowledge and memory
    # assessments together. Research plans and legacy analyses keep 24k.
    return 38000 if calibrated_validation else 24000
