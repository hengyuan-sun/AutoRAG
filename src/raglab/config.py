from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAGLAB_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///storage/raglab.db"
    api_token: str = ""
    viewer_token: str = ""
    storage: Path = Path("storage")
    ollama_url: str = "http://127.0.0.1:11436"
    embed_model: str = "qwen3-embedding:0.6b"
    vector_dim: int = 1024
    docling_artifacts_path: Path | None = None
    docling_do_ocr: bool = False
    docling_table_structure: bool = True
    docling_max_pages: int = 1000
    max_file_bytes: int = 500 * 1024 * 1024
