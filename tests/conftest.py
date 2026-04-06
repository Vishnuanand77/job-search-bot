from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def no_load_dotenv():
    """Prevent load_dotenv from reading the real .env file during tests."""
    with patch("job_scout.config.load_dotenv"):
        yield
