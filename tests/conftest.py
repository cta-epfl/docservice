import pytest


@pytest.fixture(scope="session")
def app():
    from docservice.app import app
    app.config.update({
        "TESTING": True,
        "DEBUG": True,
        "SERVER_NAME": 'app',
        "DOC_URL": "http://localhost:5003",
        "CTADS_DISABLE_ALL_AUTH": True,
    })

    yield app
