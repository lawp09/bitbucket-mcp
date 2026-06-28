"""Pagination utilities for Bitbucket API responses"""

import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PaginationConfig:
    """Configuration for pagination behavior

    Attributes:
        page_size: Number of items per page (default: 10)
        max_pages: Maximum number of pages to fetch (default: 1, None for unlimited)
        max_items: Maximum total items to fetch (default: None, no limit)
    """
    page_size: int = 10
    max_pages: Optional[int] = 1
    max_items: Optional[int] = None

    def __post_init__(self):
        """Validate configuration and log warnings"""
        if self.max_pages is not None and self.max_pages > 10:
            logger.warning(
                f"max_pages is set to {self.max_pages} which exceeds recommended limit of 10"
            )

        if self.max_items and self.max_items > 300:
            logger.warning(
                f"max_items is set to {self.max_items} which exceeds recommended limit of 300"
            )


async def paginate_bitbucket(
    client: httpx.AsyncClient,
    url: str,
    params: Dict[str, Any],
    config: Optional[PaginationConfig] = None,
    follow_redirects: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Paginate through Bitbucket API responses following 'next' links.

    Args:
        client: httpx AsyncClient for making requests
        url: Initial URL to fetch
        params: Query parameters for the request
        config: Pagination configuration (uses defaults if not provided)
        follow_redirects: Follow HTTP redirects (needed for the ``/src`` endpoint,
            which 302-redirects to a commit-pinned URL). Defaults to False to keep
            the existing behaviour of every other paginated endpoint unchanged.

    Yields:
        Dictionary containing page data with 'values' and metadata

    Raises:
        httpx.HTTPError: If any API request fails
    """
    if config is None:
        config = PaginationConfig()

    current_url = url
    pages_fetched = 0
    items_fetched = 0

    while current_url and (config.max_pages is None or pages_fetched < config.max_pages):
        response = await client.get(
            current_url,
            params=params if pages_fetched == 0 else None,
            follow_redirects=follow_redirects,
        )
        response.raise_for_status()

        data = response.json()
        pages_fetched += 1

        # Get values from response
        values = data.get("values", [])
        items_fetched += len(values)

        # Determine if we should continue
        next_url = data.get("next")
        should_continue = (
            next_url and
            (config.max_pages is None or pages_fetched < config.max_pages) and
            (config.max_items is None or items_fetched < config.max_items)
        )

        # If we're at max_items limit, clear next URL
        if config.max_items and items_fetched >= config.max_items:
            next_url = None

        yield data

        if should_continue:
            current_url = next_url
        else:
            break


def _aggregate_pages_sync(
    pages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Aggregate multiple paginated responses into a single response.

    Args:
        pages: List of page dictionaries from paginate_bitbucket

    Returns:
        Dictionary with aggregated values and metadata
    """
    if not pages:
        return {
            "values": [],
            "pagelen": 0,
            "size": 0,
            "page": 1,
        }

    # Start with first page's metadata
    first_page = pages[0]
    aggregated = {
        "values": [],
        "pagelen": first_page.get("pagelen", 0),
        "size": first_page.get("size", 0),
        "page": first_page.get("page", 1),
    }

    # Concatenate all values
    for page in pages:
        aggregated["values"].extend(page.get("values", []))

    # Add next URL if present in last page
    if pages:
        last_page = pages[-1]
        if "next" in last_page:
            aggregated["next"] = last_page["next"]

    return aggregated


async def aggregate_pages(
    client: httpx.AsyncClient,
    url: str,
    params: Dict[str, Any],
    config: PaginationConfig,
    follow_redirects: bool = False,
) -> Dict[str, Any]:
    """
    Fetch and aggregate paginated responses from Bitbucket API.

    Args:
        client: httpx AsyncClient for making requests
        url: API endpoint URL (can be absolute or relative to base_url)
        params: Query parameters for the request
        config: Pagination configuration
        follow_redirects: Follow HTTP redirects (needed for the ``/src`` directory
            listing). Defaults to False to preserve existing endpoint behaviour.

    Returns:
        Dictionary with aggregated values and metadata from all fetched pages
    """
    # Add pagelen to params
    params_with_pagination = {**params, "pagelen": config.page_size}

    # Collect all pages
    pages = []
    async for page in paginate_bitbucket(
        client, url, params_with_pagination, config, follow_redirects=follow_redirects
    ):
        pages.append(page)

    # Aggregate using the sync helper
    return _aggregate_pages_sync(pages)
