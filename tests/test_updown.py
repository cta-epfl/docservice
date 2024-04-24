from typing import Any
import pytest
from flask import url_for
import requests

@pytest.mark.timeout(30)
def test_health(app: Any, client: Any):
    print(url_for('default'))
    with pytest.raises(requests.exceptions.ConnectionError):
        r = client.get(url_for('default'))
