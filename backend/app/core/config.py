"""Configuration for all environments."""
import os


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

    # Microsoft 365 / Graph API
    MS365_TENANT_ID = os.getenv("MS365_TENANT_ID", "")
    MS365_CLIENT_ID = os.getenv("MS365_CLIENT_ID", "")
    MS365_CLIENT_SECRET = os.getenv("MS365_CLIENT_SECRET", "")
    MS365_GRAPH_URL = "https://graph.microsoft.com/v1.0"
    MS365_SCOPES = ["https://graph.microsoft.com/.default"]

    # Google Workspace / GCP
    GOOGLE_DOMAIN = os.getenv("GOOGLE_DOMAIN", "")
    GOOGLE_SA_KEY_PATH = os.getenv("GOOGLE_SA_KEY_PATH", "/secrets/google-sa.json")
    GOOGLE_SUPER_ADMIN = os.getenv("GOOGLE_SUPER_ADMIN", "")
    GOOGLE_SCOPES = [
        "https://www.googleapis.com/auth/admin.directory.user.readonly",
        "https://www.googleapis.com/auth/admin.directory.group.readonly",
        "https://www.googleapis.com/auth/admin.directory.device.chromeos.readonly",
        "https://www.googleapis.com/auth/admin.directory.device.mobile.readonly",
        "https://www.googleapis.com/auth/admin.directory.orgunit.readonly",
        "https://www.googleapis.com/auth/admin.reports.audit.readonly",
    ]


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/migration_dev"
    )


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "sqlite:///:memory:"
    )


class ProductionConfig(BaseConfig):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@postgres:5432/migration_prod"
    )
