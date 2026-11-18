# Version of the valuation math. BUMP THIS BY ONE whenever an engine change can move a result
# (cash flows, recoveries, value, IRR, ...). Each run stores the version it used
# (valuations.result_engine_version); results from an older version show "Needs re-run (engine updated)".
ENGINE_VERSION = 2  # 2: growth caps with stops cap the expense; pre-analysis fee in growth caps


def engine_outdated(result_engine_version: int | None) -> bool:
    """Results stored with this version came from an older engine (None: before versioning)."""
    return result_engine_version is None or result_engine_version < ENGINE_VERSION
