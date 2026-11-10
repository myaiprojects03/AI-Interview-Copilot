import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from tests.phase3_utils import SECRET


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        llm_provider="fake",
        stt_provider="fake",
        embedding_provider="fake",
        database_url=None,
    )


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        _env_file=None, environment="test", llm_provider="fake", stt_provider="fake",
        embedding_provider="fake", database_url=None, supabase_jwt_secret=SECRET,
        billing_provider="fake",
    )


@pytest.fixture
def auth_client(auth_settings: Settings):
    app = create_app(auth_settings)
    app.dependency_overrides[get_settings] = lambda: auth_settings
    with TestClient(app) as c:
        yield c
