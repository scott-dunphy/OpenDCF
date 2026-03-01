from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "OpenDCF - CRE Valuation Engine"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./opendcf.db"


settings = Settings()
