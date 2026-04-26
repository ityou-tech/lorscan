"""Package smoke test."""

import lorscan


def test_version_is_set():
    assert lorscan.__version__ == "0.1.0"


def test_version_is_string():
    assert isinstance(lorscan.__version__, str)
