from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment."""

    # AliasChoices is required for non-trivial ENV_VAR → field_name mappings;
    # pydantic-settings v2 does NOT silently accept `alias=` without it.
    phishnet_api_key: str = Field(
        ..., validation_alias=AliasChoices("PHISHNET_API_KEY", "phishnet_api_key")
    )
    admin_token: str = Field(
        ..., validation_alias=AliasChoices("PHISHPICKER_ADMIN_TOKEN", "admin_token")
    )
    data_dir: Path = Field(
        default=Path("./data"),
        validation_alias=AliasChoices("PHISHPICKER_DATA_DIR", "data_dir"),
    )
    phishnet_base_url: str = "https://api.phish.net/v5"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "phishpicker.db"

    @property
    def live_db_path(self) -> Path:
        return self.data_dir / "live.db"
