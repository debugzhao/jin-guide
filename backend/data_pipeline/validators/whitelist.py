from __future__ import annotations

from data_pipeline.config import PipelineConfig


class WhitelistViolation(ValueError):
    pass


def require_whitelisted_university(
    *,
    university_code: str,
    university_name: str,
    config: PipelineConfig,
) -> None:
    """Fail closed before a parsed record can enter a published dataset."""
    if not config.target_universities:
        raise WhitelistViolation(
            "target university whitelist is empty; publication is disabled"
        )

    by_code = {item.university_code: item for item in config.target_universities}
    target = by_code.get(university_code)
    if target is None:
        raise WhitelistViolation(
            f"university code {university_code!r} is outside the target whitelist"
        )
    if target.name != university_name:
        raise WhitelistViolation(
            f"university name mismatch for code {university_code!r}: "
            f"expected {target.name!r}, got {university_name!r}"
        )
