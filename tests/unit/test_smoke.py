"""Package smoke test."""

import lorscan


def test_version_is_set():
    assert lorscan.__version__ == "0.1.0"


def test_import_does_not_error():
    import lorscan  # noqa: F401
