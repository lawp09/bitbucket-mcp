"""Pytest configuration and fixtures"""

import pytest


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring real API access"
    )
