from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="STW_")

    database_url: str = "sqlite:///./stewarding.db"
    secret_key: str = ""
    token_minutes: int = 600
    cors_origins: str = "http://localhost:5173"
    seed_password: str = ""
    upload_dir: str = "./uploads"
    scheduler_enabled: bool = True
    bcrypt_rounds: int = 12
    training_max_mb: int = 500  # the largest training file (video, audio or document) that can be uploaded
    tts_voice: str = ""  # path to a Piper voice (.onnx) so slide videos can read typed narration aloud; empty leaves typed voice-over off
    # browser push; create the pair with scripts/vapid_keys.py. Push stays off while the keys are empty.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    @field_validator("database_url")
    @classmethod
    def _postgres_driver(cls, value: str) -> str:
        """Hosting platforms hand out postgres:// or postgresql:// URLs; the app uses the psycopg driver."""
        for scheme in ("postgres://", "postgresql://"):
            if value.startswith(scheme):
                return "postgresql+psycopg://" + value.removeprefix(scheme)
        return value


settings = Settings()
