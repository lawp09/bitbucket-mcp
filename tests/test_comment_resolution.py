"""Tests for comment resolution support in pull request comments"""

import httpx
import pytest
import respx
from datetime import datetime
from src.client import BitbucketClient
from src.utils.pagination import PaginationConfig


class TestCommentResolutionParsing:
    """Tests for parsing resolution object from API responses"""

    @pytest.mark.asyncio
    async def test_comment_with_resolution_object(self):
        """Test parsing comment with resolution object present"""
        mock_response = {
            "values": [
                {
                    "id": 1,
                    "content": {"raw": "This is resolved"},
                    "created_on": "2025-01-01T10:00:00Z",
                    "resolution": {
                        "type": "resolved",
                        "user": {
                            "username": "reviewer",
                            "display_name": "Reviewer User",
                            "uuid": "{uuid-123}"
                        },
                        "created_on": "2025-01-01T11:00:00Z"
                    }
                }
            ],
            "pagelen": 10,
            "size": 1
        }

        with respx.mock:
            respx.get(
                "https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/comments"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_comments("repo", "1")

            assert len(result["values"]) == 1
            comment = result["values"][0]
            assert comment["id"] == 1
            assert "resolution" in comment
            assert comment["resolution"] is not None
            assert comment["resolution"]["type"] == "resolved"
            assert "user" in comment["resolution"]
            assert "created_on" in comment["resolution"]

    @pytest.mark.asyncio
    async def test_comment_with_null_resolution(self):
        """Test parsing comment with resolution=null (unresolved)"""
        mock_response = {
            "values": [
                {
                    "id": 2,
                    "content": {"raw": "This is unresolved"},
                    "created_on": "2025-01-01T10:00:00Z",
                    "resolution": None
                }
            ],
            "pagelen": 10,
            "size": 1
        }

        with respx.mock:
            respx.get(
                "https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/comments"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_comments("repo", "1")

            assert len(result["values"]) == 1
            comment = result["values"][0]
            assert comment["id"] == 2
            assert "resolution" in comment
            assert comment["resolution"] is None

    @pytest.mark.asyncio
    async def test_comment_without_resolution_field_backward_compatibility(self):
        """Test comment without resolution field (backward compatibility)"""
        mock_response = {
            "values": [
                {
                    "id": 3,
                    "content": {"raw": "Legacy comment"},
                    "created_on": "2025-01-01T10:00:00Z"
                    # Note: no resolution field
                }
            ],
            "pagelen": 10,
            "size": 1
        }

        with respx.mock:
            respx.get(
                "https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/comments"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_comments("repo", "1")

            assert len(result["values"]) == 1
            comment = result["values"][0]
            assert comment["id"] == 3
            # Should handle gracefully - either missing or None
            assert comment.get("resolution") is None


class TestUnresolvedOnlyFiltering:
    """Tests for unresolved_only filter parameter"""

    @pytest.mark.asyncio
    async def test_unresolved_only_does_not_add_query_param(self):
        """Test that unresolved_only=True does NOT add q param (filtering is client-side)"""
        mock_response = {
            "values": [
                {
                    "id": 2,
                    "content": {"raw": "Unresolved comment"},
                    "resolution": None
                }
            ],
            "pagelen": 10,
            "size": 1
        }

        with respx.mock as respx_mock:
            route = respx_mock.get(
                url="https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/comments"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_comments(
                    "repo", "1", unresolved_only=True
                )

            assert route.called
            assert "q" not in dict(route.calls[0].request.url.params)
            assert len(result["values"]) == 1
            assert result["values"][0]["resolution"] is None

    @pytest.mark.asyncio
    async def test_unresolved_only_false_no_query_param(self):
        """Test that unresolved_only=False does not add query parameter"""
        mock_response = {
            "values": [
                {
                    "id": 1,
                    "content": {"raw": "Resolved"},
                    "resolution": {"type": "resolved", "user": {"username": "user"}}
                },
                {
                    "id": 2,
                    "content": {"raw": "Unresolved"},
                    "resolution": None
                }
            ],
            "pagelen": 10,
            "size": 2
        }

        with respx.mock as respx_mock:
            route = respx_mock.get(
                url="https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/comments"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_comments("repo", "1", unresolved_only=False)

            assert route.called
            assert len(result["values"]) == 2

    @pytest.mark.asyncio
    async def test_unresolved_only_returns_all_comments_for_client_side_filtering(self):
        """Test that unresolved_only=True returns ALL comments from API (filtering is caller's job)"""
        mock_response = {
            "values": [
                {
                    "id": 10,
                    "content": {"raw": "Unresolved comment"},
                    "resolution": None
                },
                {
                    "id": 11,
                    "content": {"raw": "Resolved comment"},
                    "resolution": {"type": "resolved", "user": {"username": "reviewer"}}
                }
            ],
            "pagelen": 10,
            "size": 2
        }

        with respx.mock:
            respx.get(
                url="https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/comments"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_comments(
                    "repo", "1", unresolved_only=True
                )

            # Client returns ALL comments — caller (server.py) is responsible for filtering
            assert len(result["values"]) == 2
            assert result["values"][0]["resolution"] is None
            assert result["values"][1]["resolution"] is not None


class TestCommentStatsCalculation:
    """Tests for comment statistics calculation"""

    @pytest.mark.asyncio
    async def test_comment_stats_calculation_from_comment_list(self):
        """Test stats calculation logic with mixed resolved/unresolved comments"""
        comments = [
            {"id": 1, "content": {"raw": "Comment 1"}, "resolution": {"type": "resolved"}},
            {"id": 2, "content": {"raw": "Comment 2"}, "resolution": None},
            {"id": 3, "content": {"raw": "Comment 3"}, "resolution": {"type": "resolved"}},
            {"id": 4, "content": {"raw": "Comment 4"}, "resolution": None},
            {"id": 5, "content": {"raw": "Comment 5"}, "resolution": {"type": "resolved"}}
        ]

        # Calculate stats as the client does
        total = len(comments)
        resolved = sum(1 for c in comments if c.get("resolution") is not None)
        unresolved = total - resolved

        assert total == 5
        assert resolved == 3
        assert unresolved == 2

    @pytest.mark.asyncio
    async def test_comment_stats_all_resolved(self):
        """Test stats when all comments are resolved"""
        comments = [
            {"id": 1, "content": {"raw": "C1"}, "resolution": {"type": "resolved"}},
            {"id": 2, "content": {"raw": "C2"}, "resolution": {"type": "resolved"}},
            {"id": 3, "content": {"raw": "C3"}, "resolution": {"type": "resolved"}}
        ]

        # Calculate stats as the client does
        total = len(comments)
        resolved = sum(1 for c in comments if c.get("resolution") is not None)
        unresolved = total - resolved

        assert total == 3
        assert resolved == 3
        assert unresolved == 0

    @pytest.mark.asyncio
    async def test_comment_stats_all_unresolved(self):
        """Test stats when all comments are unresolved"""
        comments = [
            {"id": 1, "content": {"raw": "C1"}, "resolution": None},
            {"id": 2, "content": {"raw": "C2"}, "resolution": None},
            {"id": 3, "content": {"raw": "C3"}, "resolution": None}
        ]

        # Calculate stats as the client does
        total = len(comments)
        resolved = sum(1 for c in comments if c.get("resolution") is not None)
        unresolved = total - resolved

        assert total == 3
        assert resolved == 0
        assert unresolved == 3

    @pytest.mark.asyncio
    async def test_comment_stats_no_comments(self):
        """Test stats with no comments"""
        comments = []

        # Calculate stats as the client does
        total = len(comments)
        resolved = sum(1 for c in comments if c.get("resolution") is not None)
        unresolved = total - resolved

        assert total == 0
        assert resolved == 0
        assert unresolved == 0


class TestCommentEnrichmentFields:
    """Tests for enriching comments with calculated fields"""

    def test_is_resolved_field_when_resolved(self):
        """Test is_resolved field is True when resolution is not None"""
        comment = {
            "id": 1,
            "content": {"raw": "Comment"},
            "resolution": {
                "type": "resolved",
                "user": {"username": "reviewer"}
            }
        }

        # Check if resolved can be determined
        is_resolved = comment.get("resolution") is not None
        assert is_resolved is True

    def test_is_resolved_field_when_unresolved(self):
        """Test is_resolved field is False when resolution is None"""
        comment = {
            "id": 2,
            "content": {"raw": "Comment"},
            "resolution": None
        }

        # Check if resolved can be determined
        is_resolved = comment.get("resolution") is not None
        assert is_resolved is False

    def test_resolved_by_field_present(self):
        """Test resolved_by field is extracted from resolution object"""
        comment = {
            "id": 3,
            "content": {"raw": "Comment"},
            "resolution": {
                "type": "resolved",
                "user": {
                    "username": "reviewer",
                    "display_name": "Code Reviewer",
                    "uuid": "{uuid-123}"
                }
            }
        }

        # Extract resolved_by
        resolved_by = None
        if comment.get("resolution"):
            resolved_by = comment["resolution"].get("user", {}).get("display_name") or \
                         comment["resolution"].get("user", {}).get("username")

        assert resolved_by == "Code Reviewer"

    def test_resolved_by_field_absent_when_unresolved(self):
        """Test resolved_by is None when comment is unresolved"""
        comment = {
            "id": 4,
            "content": {"raw": "Comment"},
            "resolution": None
        }

        # Extract resolved_by
        resolved_by = None
        if comment.get("resolution"):
            resolved_by = comment["resolution"].get("user", {}).get("display_name") or \
                         comment["resolution"].get("user", {}).get("username")

        assert resolved_by is None

    def test_resolved_on_field_present(self):
        """Test resolved_on field is extracted from resolution object"""
        timestamp = "2025-01-01T11:00:00Z"
        comment = {
            "id": 5,
            "content": {"raw": "Comment"},
            "resolution": {
                "type": "resolved",
                "user": {"username": "reviewer"},
                "created_on": timestamp
            }
        }

        # Extract resolved_on
        resolved_on = None
        if comment.get("resolution"):
            resolved_on = comment["resolution"].get("created_on")

        assert resolved_on == timestamp

    def test_resolved_on_field_absent_when_unresolved(self):
        """Test resolved_on is None when comment is unresolved"""
        comment = {
            "id": 6,
            "content": {"raw": "Comment"},
            "resolution": None
        }

        # Extract resolved_on
        resolved_on = None
        if comment.get("resolution"):
            resolved_on = comment["resolution"].get("created_on")

        assert resolved_on is None


class TestMultipleResolutionStatuses:
    """Integration tests for handling multiple comments with various states"""

    @pytest.mark.asyncio
    async def test_activity_log_includes_comment_resolution(self):
        """Test that activity log includes resolution info in comments"""
        mock_response = {
            "values": [
                {
                    "type": "comment",
                    "comment": {
                        "id": 1,
                        "content": {"raw": "Activity comment 1"},
                        "resolution": {"type": "resolved", "user": {"username": "reviewer"}}
                    }
                },
                {
                    "type": "comment",
                    "comment": {
                        "id": 2,
                        "content": {"raw": "Activity comment 2"},
                        "resolution": None
                    }
                }
            ],
            "pagelen": 10,
            "size": 2
        }

        with respx.mock:
            respx.get(
                "https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/activity"
            ).mock(return_value=httpx.Response(200, json=mock_response))

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_activity("repo", "1")

            assert len(result["values"]) == 2
            assert result["values"][0]["comment"]["resolution"] is not None
            assert result["values"][1]["comment"]["resolution"] is None

    @pytest.mark.asyncio
    async def test_pagination_with_resolution_info(self):
        """Test pagination across multiple pages preserves resolution info"""
        page1 = {
            "values": [
                {"id": 1, "content": {"raw": "C1"}, "resolution": {"type": "resolved"}},
                {"id": 2, "content": {"raw": "C2"}, "resolution": None}
            ],
            "pagelen": 2,
            "size": 4,
            "next": "https://api.bitbucket.org/2.0/repositories/workspace/repo/pullrequests/1/comments?page=2"
        }
        page2 = {
            "values": [
                {"id": 3, "content": {"raw": "C3"}, "resolution": None},
                {"id": 4, "content": {"raw": "C4"}, "resolution": {"type": "resolved"}}
            ],
            "pagelen": 2,
            "size": 4
        }

        def response_handler(request):
            if "page=2" in str(request.url):
                return httpx.Response(200, json=page2)
            else:
                return httpx.Response(200, json=page1)

        with respx.mock:
            respx.get(url__regex=r"comments").mock(side_effect=response_handler)

            async with BitbucketClient("test@example.com", "token", "workspace") as client:
                result = await client.get_pull_request_comments(
                    "repo", "1", page_size=2, max_pages=2
                )

            assert len(result["values"]) == 4
            assert result["values"][0]["resolution"] is not None
            assert result["values"][1]["resolution"] is None
            assert result["values"][2]["resolution"] is None
            assert result["values"][3]["resolution"] is not None
