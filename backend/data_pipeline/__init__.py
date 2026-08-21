"""Jiangsu admission-data collection pipeline.

The package deliberately keeps collection separate from publication: raw official
artifacts may be collected before the target-university whitelist is finalized,
but records cannot be published without passing the whitelist gate.
"""

from data_pipeline.config import PipelineConfig, SourceConfig, load_pipeline_config

__all__ = ["PipelineConfig", "SourceConfig", "load_pipeline_config"]
