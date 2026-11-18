from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "OpenDCF - CRE Valuation Engine"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./opendcf.db"
    # Worker processes for collateral Monte Carlo (0 = one per CPU)
    mc_workers: int = 0
    # FRED (St. Louis Fed) key for live SOFR / Treasury curves; read from .env, never committed
    fred_api_key: str | None = None
    anthropic_api_key: str | None = None
    anthropic_document_model: str = "claude-sonnet-5"
    # Reading documents (extraction and appraisal rebuilds)
    anthropic_extraction_model: str = "claude-opus-5-5"
    # In-app modeling help chat
    anthropic_help_model: str = "claude-opus-5-5"
    document_store_path: str = "./data/documents"
    document_max_upload_bytes: int = 50 * 1024 * 1024


settings = Settings()
