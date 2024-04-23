import pytest


@pytest.fixture(scope="session")
def app():
    from docservice.app import app
    app.config.update({
        "TESTING": True,
        "DEBUG": True,
        "SERVER_NAME": 'app',
    })

    yield app
