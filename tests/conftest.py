"""Pytest configuration and fixtures"""

import pytest


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring real API access"
    )


@pytest.fixture(autouse=True, scope="function")
def reset_page_hard_cap():
    """Restore the module-level pagination hard cap around every test.

    Session-wide state: the stateless tests in test_main.py really do call
    set_page_hard_cap(), which would otherwise clamp pagination in every test that runs
    after them, making results depend on collection order.
    """
    from src.utils import pagination

    saved = pagination.get_page_hard_cap()
    yield
    pagination.set_page_hard_cap(saved)
