"""Integration tests for Bitbucket MCP server

These tests require valid Bitbucket credentials set in environment variables.
They are skipped if credentials are not available.
"""

import os
import pytest
import httpx
from src.client import BitbucketClient


# Skip all tests in this file if credentials not available
pytestmark = pytest.mark.skipif(
    not all([
        os.getenv("BITBUCKET_USERNAME"),
        os.getenv("BITBUCKET_TOKEN"),
        os.getenv("BITBUCKET_WORKSPACE")
    ]),
    reason="Bitbucket credentials not available"
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_authentication():
    """Test that authentication works with real API.

    Some scoped Bitbucket tokens can access repository endpoints but not `/user`.
    In that case, fall back to a repository listing call to verify credentials are usable.
    """
    client = BitbucketClient(
        email=os.getenv("BITBUCKET_USERNAME"),
        token=os.getenv("BITBUCKET_TOKEN"),
        workspace=os.getenv("BITBUCKET_WORKSPACE")
    )

    try:
        try:
            user = await client.get_user()
            assert user is not None
            assert "username" in user
            assert "display_name" in user
        except httpx.HTTPStatusError as exc:
            assert exc.response.status_code == 403
            repos = await client.list_repositories(limit=1)
            assert repos is not None
            assert "values" in repos
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_repositories():
    """Test listing repositories"""
    client = BitbucketClient(
        email=os.getenv("BITBUCKET_USERNAME"),
        token=os.getenv("BITBUCKET_TOKEN"),
        workspace=os.getenv("BITBUCKET_WORKSPACE")
    )

    try:
        repos = await client.list_repositories(limit=5)
        assert repos is not None
        assert "values" in repos
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_pull_requests():
    """Test getting pull requests (if any exist)"""
    client = BitbucketClient(
        email=os.getenv("BITBUCKET_USERNAME"),
        token=os.getenv("BITBUCKET_TOKEN"),
        workspace=os.getenv("BITBUCKET_WORKSPACE")
    )

    try:
        # First get a repository
        repos = await client.list_repositories(limit=1)

        if repos.get("values"):
            repo_slug = repos["values"][0]["slug"]

            # Try to get PRs for this repo
            prs = await client.get_pull_requests(repo_slug, limit=5)
            assert prs is not None
            assert "values" in prs
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_repository_tags():
    """Test listing recent repository tags with the real API."""
    client = BitbucketClient(
        email=os.getenv("BITBUCKET_USERNAME"),
        token=os.getenv("BITBUCKET_TOKEN"),
        workspace=os.getenv("BITBUCKET_WORKSPACE")
    )

    try:
        repos = await client.list_repositories(limit=1)

        if repos.get("values"):
            repo_slug = repos["values"][0]["slug"]
            tags = await client.get_repository_tags(repo_slug, page_size=10)

            assert tags is not None
            assert "values" in tags
            assert len(tags["values"]) <= 10

            if tags["values"]:
                assert "name" in tags["values"][0]
    finally:
        await client.close()
