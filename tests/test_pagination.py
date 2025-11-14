"""Tests for pagination utilities"""

import logging
from typing import Any, Dict

import httpx
import pytest
import respx

from src.utils.pagination import PaginationConfig, _aggregate_pages_sync, paginate_bitbucket


class TestPaginationConfig:
    """Tests for PaginationConfig validation and defaults"""

    def test_default_values(self):
        """Test that PaginationConfig has correct default values"""
        config = PaginationConfig()

        assert config.page_size == 10
        assert config.max_pages == 1
        assert config.max_items is None

    def test_custom_values(self):
        """Test that custom values are properly set"""
        config = PaginationConfig(page_size=25, max_pages=5, max_items=100)

        assert config.page_size == 25
        assert config.max_pages == 5
        assert config.max_items == 100

    def test_warning_log_max_pages_exceeds_limit(self, caplog):
        """Test that warning is logged when max_pages exceeds recommended limit"""
        with caplog.at_level(logging.WARNING):
            config = PaginationConfig(max_pages=15)

        assert config.max_pages == 15
        assert "max_pages is set to 15" in caplog.text
        assert "exceeds recommended limit of 10" in caplog.text

    def test_warning_log_max_items_exceeds_limit(self, caplog):
        """Test that warning is logged when max_items exceeds recommended limit"""
        with caplog.at_level(logging.WARNING):
            config = PaginationConfig(max_items=500)

        assert config.max_items == 500
        assert "max_items is set to 500" in caplog.text
        assert "exceeds recommended limit of 300" in caplog.text

    def test_no_warning_within_limits(self, caplog):
        """Test that no warnings are logged when values are within limits"""
        with caplog.at_level(logging.WARNING):
            config = PaginationConfig(max_pages=5, max_items=200)

        assert "warning" not in caplog.text.lower()

    def test_multiple_warnings(self, caplog):
        """Test that multiple warnings are logged when both limits exceeded"""
        with caplog.at_level(logging.WARNING):
            config = PaginationConfig(max_pages=15, max_items=500)

        assert "max_pages is set to 15" in caplog.text
        assert "max_items is set to 500" in caplog.text


class TestPaginateBitbucket:
    """Tests for paginate_bitbucket generator"""

    @pytest.mark.asyncio
    async def test_single_page_no_next_url(self):
        """Test pagination with single page that has no 'next' URL"""
        mock_response = {
            "values": [{"id": 1}, {"id": 2}],
            "pagelen": 10,
            "size": 2,
        }

        with respx.mock:
            route = respx.get("https://api.bitbucket.org/2.0/test").mock(
                return_value=httpx.Response(200, json=mock_response)
            )

            async with httpx.AsyncClient() as client:
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}
                ):
                    pages.append(page)

            assert len(pages) == 1
            assert pages[0] == mock_response
            assert route.called

    @pytest.mark.asyncio
    async def test_multiple_pages_follows_next_url(self):
        """Test pagination that follows 'next' URL across multiple pages"""
        page1 = {
            "values": [{"id": 1}, {"id": 2}],
            "pagelen": 2,
            "size": 4,
            "next": "https://api.bitbucket.org/2.0/test?page=2",
        }
        page2 = {
            "values": [{"id": 3}, {"id": 4}],
            "pagelen": 2,
            "size": 4,
        }

        def response_handler(request):
            if "page=2" in str(request.url):
                return httpx.Response(200, json=page2)
            else:
                return httpx.Response(200, json=page1)

        with respx.mock:
            respx.get(url__regex=r"https://api.bitbucket.org/2.0/test").mock(
                side_effect=response_handler
            )

            async with httpx.AsyncClient() as client:
                config = PaginationConfig(max_pages=2)
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}, config
                ):
                    pages.append(page)

            assert len(pages) == 2
            assert pages[0]["values"] == [{"id": 1}, {"id": 2}]
            assert pages[1]["values"] == [{"id": 3}, {"id": 4}]

    @pytest.mark.asyncio
    async def test_max_pages_limit(self):
        """Test that pagination respects max_pages limit"""
        page1 = {
            "values": [{"id": 1}],
            "pagelen": 1,
            "size": 3,
            "next": "https://api.bitbucket.org/2.0/test?page=2",
        }
        page2 = {
            "values": [{"id": 2}],
            "pagelen": 1,
            "size": 3,
            "next": "https://api.bitbucket.org/2.0/test?page=3",
        }
        page3 = {
            "values": [{"id": 3}],
            "pagelen": 1,
            "size": 3,
        }

        def response_handler(request):
            if "page=3" in str(request.url):
                return httpx.Response(200, json=page3)
            elif "page=2" in str(request.url):
                return httpx.Response(200, json=page2)
            else:
                return httpx.Response(200, json=page1)

        with respx.mock:
            route = respx.get(url__regex=r"https://api.bitbucket.org/2.0/test").mock(
                side_effect=response_handler
            )

            async with httpx.AsyncClient() as client:
                config = PaginationConfig(max_pages=2)
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}, config
                ):
                    pages.append(page)

            assert len(pages) == 2
            assert pages[0]["values"][0]["id"] == 1
            assert pages[1]["values"][0]["id"] == 2

    @pytest.mark.asyncio
    async def test_max_items_limit(self):
        """Test that pagination respects max_items limit"""
        page1 = {
            "values": [{"id": 1}, {"id": 2}],
            "pagelen": 2,
            "size": 4,
            "next": "https://api.bitbucket.org/2.0/test?page=2",
        }
        page2 = {
            "values": [{"id": 3}, {"id": 4}],
            "pagelen": 2,
            "size": 4,
        }

        with respx.mock:
            respx.get("https://api.bitbucket.org/2.0/test").mock(
                return_value=httpx.Response(200, json=page1)
            )
            respx.get("https://api.bitbucket.org/2.0/test?page=2").mock(
                return_value=httpx.Response(200, json=page2)
            )

            async with httpx.AsyncClient() as client:
                config = PaginationConfig(max_pages=10, max_items=3)
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}, config
                ):
                    pages.append(page)

            # Should have 2 pages but max_items limit prevents next URL
            assert len(pages) == 2
            # Total items across pages should be 4 (2+2), exceeding max_items of 3

    @pytest.mark.asyncio
    async def test_empty_response_no_values_key(self):
        """Test pagination with response missing 'values' key"""
        mock_response = {
            "pagelen": 0,
            "size": 0,
        }

        with respx.mock:
            respx.get("https://api.bitbucket.org/2.0/test").mock(
                return_value=httpx.Response(200, json=mock_response)
            )

            async with httpx.AsyncClient() as client:
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}
                ):
                    pages.append(page)

            assert len(pages) == 1
            assert pages[0] == mock_response

    @pytest.mark.asyncio
    async def test_empty_values_list(self):
        """Test pagination with empty values list"""
        mock_response = {
            "values": [],
            "pagelen": 0,
            "size": 0,
        }

        with respx.mock:
            respx.get("https://api.bitbucket.org/2.0/test").mock(
                return_value=httpx.Response(200, json=mock_response)
            )

            async with httpx.AsyncClient() as client:
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}
                ):
                    pages.append(page)

            assert len(pages) == 1
            assert pages[0]["values"] == []

    @pytest.mark.asyncio
    async def test_default_config_used_when_none_provided(self):
        """Test that default PaginationConfig is used when config is None"""
        mock_response = {
            "values": [{"id": 1}],
            "pagelen": 1,
            "size": 2,
            "next": "https://api.bitbucket.org/2.0/test?page=2",
        }

        with respx.mock:
            respx.get("https://api.bitbucket.org/2.0/test").mock(
                return_value=httpx.Response(200, json=mock_response)
            )

            async with httpx.AsyncClient() as client:
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}, None
                ):
                    pages.append(page)

            # Default config has max_pages=1, so only 1 page fetched
            assert len(pages) == 1

    @pytest.mark.asyncio
    async def test_http_error_handling(self):
        """Test that HTTP errors are raised"""
        with respx.mock:
            respx.get("https://api.bitbucket.org/2.0/test").mock(
                return_value=httpx.Response(401)
            )

            async with httpx.AsyncClient() as client:
                config = PaginationConfig()
                with pytest.raises(httpx.HTTPStatusError):
                    async for page in paginate_bitbucket(
                        client, "https://api.bitbucket.org/2.0/test", {}, config
                    ):
                        pass

    @pytest.mark.asyncio
    async def test_three_page_pagination_with_limits(self):
        """Test pagination through three pages with various limits"""
        page1 = {
            "values": [{"id": 1}, {"id": 2}, {"id": 3}],
            "pagelen": 3,
            "size": 9,
            "next": "https://api.bitbucket.org/2.0/test?page=2",
        }
        page2 = {
            "values": [{"id": 4}, {"id": 5}, {"id": 6}],
            "pagelen": 3,
            "size": 9,
            "next": "https://api.bitbucket.org/2.0/test?page=3",
        }
        page3 = {
            "values": [{"id": 7}, {"id": 8}, {"id": 9}],
            "pagelen": 3,
            "size": 9,
        }

        with respx.mock:
            respx.get("https://api.bitbucket.org/2.0/test").mock(
                return_value=httpx.Response(200, json=page1)
            )
            respx.get("https://api.bitbucket.org/2.0/test?page=2").mock(
                return_value=httpx.Response(200, json=page2)
            )
            respx.get("https://api.bitbucket.org/2.0/test?page=3").mock(
                return_value=httpx.Response(200, json=page3)
            )

            async with httpx.AsyncClient() as client:
                config = PaginationConfig(max_pages=3, max_items=8)
                pages = []
                async for page in paginate_bitbucket(
                    client, "https://api.bitbucket.org/2.0/test", {}, config
                ):
                    pages.append(page)

            assert len(pages) == 3
            total_items = sum(len(p["values"]) for p in pages)
            assert total_items == 9  # All items collected despite max_items=8


class TestAggregatePages:
    """Tests for aggregate_pages helper function"""

    def test_empty_pages_list(self):
        """Test aggregation of empty pages list"""
        result = _aggregate_pages_sync([])

        assert result["values"] == []
        assert result["pagelen"] == 0
        assert result["size"] == 0
        assert result["page"] == 1
        assert "next" not in result

    def test_single_page_aggregation(self):
        """Test aggregation of single page"""
        page = {
            "values": [{"id": 1}, {"id": 2}],
            "pagelen": 2,
            "size": 2,
            "page": 1,
        }

        result = _aggregate_pages_sync([page])

        assert result["values"] == page["values"]
        assert result["pagelen"] == 2
        assert result["size"] == 2
        assert result["page"] == 1
        assert "next" not in result

    def test_multiple_pages_concatenation(self):
        """Test that multiple pages are properly concatenated"""
        page1 = {
            "values": [{"id": 1}, {"id": 2}],
            "pagelen": 2,
            "size": 4,
            "page": 1,
        }
        page2 = {
            "values": [{"id": 3}, {"id": 4}],
            "pagelen": 2,
            "size": 4,
            "page": 2,
        }

        result = _aggregate_pages_sync([page1, page2])

        assert len(result["values"]) == 4
        assert result["values"] == [
            {"id": 1},
            {"id": 2},
            {"id": 3},
            {"id": 4},
        ]

    def test_metadata_preservation(self):
        """Test that first page metadata is preserved"""
        page1 = {
            "values": [{"id": 1}],
            "pagelen": 1,
            "size": 2,
            "page": 1,
        }
        page2 = {
            "values": [{"id": 2}],
            "pagelen": 1,
            "size": 2,
            "page": 2,
        }

        result = _aggregate_pages_sync([page1, page2])

        # Should use first page's metadata
        assert result["pagelen"] == 1
        assert result["size"] == 2
        assert result["page"] == 1

    def test_next_url_preservation_when_limit_reached(self):
        """Test that next URL from last page is preserved"""
        page1 = {
            "values": [{"id": 1}],
            "pagelen": 1,
            "size": 3,
        }
        page2 = {
            "values": [{"id": 2}],
            "pagelen": 1,
            "size": 3,
            "next": "https://api.bitbucket.org/2.0/test?page=3",
        }

        result = _aggregate_pages_sync([page1, page2])

        assert result["next"] == "https://api.bitbucket.org/2.0/test?page=3"

    def test_three_page_aggregation(self):
        """Test aggregation of three pages"""
        page1 = {
            "values": [{"id": 1}, {"id": 2}],
            "pagelen": 2,
            "size": 6,
        }
        page2 = {
            "values": [{"id": 3}, {"id": 4}],
            "pagelen": 2,
            "size": 6,
        }
        page3 = {
            "values": [{"id": 5}, {"id": 6}],
            "pagelen": 2,
            "size": 6,
        }

        result = _aggregate_pages_sync([page1, page2, page3])

        assert len(result["values"]) == 6
        assert result["values"][0]["id"] == 1
        assert result["values"][-1]["id"] == 6

    def test_missing_values_key_in_page(self):
        """Test aggregation when page is missing 'values' key"""
        page1 = {
            "pagelen": 0,
            "size": 0,
        }
        page2 = {
            "values": [{"id": 1}],
            "pagelen": 1,
            "size": 1,
        }

        result = _aggregate_pages_sync([page1, page2])

        assert len(result["values"]) == 1
        assert result["values"][0]["id"] == 1

    def test_missing_metadata_keys(self):
        """Test aggregation when page is missing metadata keys"""
        page1 = {"values": [{"id": 1}]}
        page2 = {"values": [{"id": 2}]}

        result = _aggregate_pages_sync([page1, page2])

        assert len(result["values"]) == 2
        assert result["pagelen"] == 0  # Default from missing key
        assert result["size"] == 0  # Default from missing key
        assert result["page"] == 1  # Default from missing key

    def test_complex_nested_values(self):
        """Test aggregation with complex nested object values"""
        page1 = {
            "values": [
                {"id": 1, "name": "Item 1", "metadata": {"type": "repo"}},
                {"id": 2, "name": "Item 2", "metadata": {"type": "repo"}},
            ],
            "pagelen": 2,
            "size": 3,
        }
        page2 = {
            "values": [
                {"id": 3, "name": "Item 3", "metadata": {"type": "repo"}},
            ],
            "pagelen": 1,
            "size": 3,
        }

        result = _aggregate_pages_sync([page1, page2])

        assert len(result["values"]) == 3
        assert result["values"][0]["metadata"]["type"] == "repo"
        assert result["values"][-1]["name"] == "Item 3"
