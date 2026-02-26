"""Functional tests for Phase 3 MCP tools."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ========== Fixtures ==========

SAMPLE_PR_RESPONSE = {
    "id": 42,
    "title": "Test PR",
    "state": "OPEN",
    "draft": False,
    "source": {"branch": {"name": "feat"}},
    "destination": {"branch": {"name": "main"}},
    "links": {"html": {"href": "https://bitbucket.org/test/repo/pull-requests/42"}},
    "created_on": "2026-01-01T00:00:00Z",
    "author": {"display_name": "Dev", "uuid": "{author-uuid}"},
    "reviewers": [],
    "participants": [],
    "comment_count": 0,
    "task_count": 0,
    "description": "",
    "close_source_branch": False,
    "updated_on": "2026-01-01T00:00:00Z",
}

SAMPLE_DRAFT_PR_RESPONSE = {
    **SAMPLE_PR_RESPONSE,
    "id": 43,
    "state": "OPEN",
    "draft": True,
}


# ========== Tool 1: create_draft_pull_request ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_create_draft_pull_request(mock_get_client):
    from src.server import create_draft_pull_request

    mock_client = AsyncMock()
    mock_client.create_pull_request.return_value = SAMPLE_DRAFT_PR_RESPONSE
    mock_get_client.return_value = mock_client

    result = await create_draft_pull_request(
        "my-repo", "Test", "Description", "feat", "main"
    )

    mock_client.create_pull_request.assert_called_once_with(
        "my-repo", "Test", "Description", "feat", "main", None, None, draft=True
    )
    assert result["draft"] is True
    assert result["id"] == 43


# ========== Tool 2: publish_draft_pull_request ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_publish_draft_pull_request(mock_get_client):
    from src.server import publish_draft_pull_request

    mock_client = AsyncMock()
    published = {**SAMPLE_DRAFT_PR_RESPONSE, "draft": False, "state": "OPEN"}
    mock_client.publish_draft_pull_request.return_value = published
    mock_get_client.return_value = mock_client

    result = await publish_draft_pull_request("my-repo", "43")

    mock_client.publish_draft_pull_request.assert_called_once_with(
        "my-repo", "43", None
    )
    assert result["draft"] is False
    assert result["id"] == 43


# ========== Tool 3: convert_pull_request_to_draft ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_convert_pull_request_to_draft_returns_error(mock_get_client):
    from src.server import convert_pull_request_to_draft

    result = await convert_pull_request_to_draft("my-repo", "42")

    assert result["error"] == "Not supported by Bitbucket API"
    assert "Bitbucket Cloud REST API" in result["message"]
    assert result["pr_id"] == "42"
    assert result["repo_slug"] == "my-repo"
    mock_get_client.assert_not_called()


# ========== Tool 4: submit_pull_request_batch_review ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_submit_batch_review_comments_only(mock_get_client):
    from src.server import submit_pull_request_batch_review

    mock_client = AsyncMock()
    mock_client.add_pull_request_comment.return_value = {}
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_get_client.return_value = mock_client

    result = await submit_pull_request_batch_review(
        "my-repo", "42",
        comments=[
            {"content": "Comment 1"},
            {"content": "Comment 2"},
        ],
        review_action="comment_only"
    )

    assert result["comments_posted"] == 2
    assert result["action"] == "comment_only"
    assert mock_client.add_pull_request_comment.call_count == 2
    mock_client.approve_pull_request.assert_not_called()
    mock_client.request_changes_pull_request.assert_not_called()


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_submit_batch_review_with_approve(mock_get_client):
    from src.server import submit_pull_request_batch_review

    mock_client = AsyncMock()
    mock_client.add_pull_request_comment.return_value = {}
    mock_client.approve_pull_request.return_value = {}
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_get_client.return_value = mock_client

    result = await submit_pull_request_batch_review(
        "my-repo", "42",
        comments=[{"content": "LGTM"}],
        review_action="approve"
    )

    assert result["comments_posted"] == 1
    assert result["action"] == "approve"
    mock_client.approve_pull_request.assert_called_once_with("my-repo", "42", None)
    mock_client.request_changes_pull_request.assert_not_called()


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_submit_batch_review_with_request_changes(mock_get_client):
    from src.server import submit_pull_request_batch_review

    mock_client = AsyncMock()
    mock_client.add_pull_request_comment.return_value = {}
    mock_client.request_changes_pull_request.return_value = {}
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_get_client.return_value = mock_client

    result = await submit_pull_request_batch_review(
        "my-repo", "42",
        comments=[{"content": "Please fix this"}],
        review_action="request_changes"
    )

    assert result["action"] == "request_changes"
    mock_client.request_changes_pull_request.assert_called_once_with("my-repo", "42", None)
    mock_client.approve_pull_request.assert_not_called()


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_submit_batch_review_with_review_message(mock_get_client):
    from src.server import submit_pull_request_batch_review

    mock_client = AsyncMock()
    mock_client.add_pull_request_comment.return_value = {}
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_get_client.return_value = mock_client

    result = await submit_pull_request_batch_review(
        "my-repo", "42",
        comments=[{"content": "inline comment"}],
        review_action="comment_only",
        review_message="Overall review message"
    )

    # review_message + 1 comment = 2 total
    assert result["comments_posted"] == 2
    assert mock_client.add_pull_request_comment.call_count == 2
    # First call is the review_message
    first_call_args = mock_client.add_pull_request_comment.call_args_list[0]
    assert first_call_args[0][2] == "Overall review message"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_submit_batch_review_invalid_action(mock_get_client):
    from src.server import submit_pull_request_batch_review

    mock_get_client.return_value = AsyncMock()

    with pytest.raises(ValueError, match="Invalid review_action"):
        await submit_pull_request_batch_review(
            "my-repo", "42",
            comments=[],
            review_action="invalid_action"
        )


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_submit_batch_review_inline_comments(mock_get_client):
    from src.server import submit_pull_request_batch_review

    mock_client = AsyncMock()
    mock_client.add_pull_request_comment.return_value = {}
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_get_client.return_value = mock_client

    result = await submit_pull_request_batch_review(
        "my-repo", "42",
        comments=[
            {
                "content": "Fix this line",
                "inline": {"path": "src/main.py", "to": 10, "from": None}
            }
        ],
        review_action="comment_only"
    )

    assert result["comments_posted"] == 1
    call_kwargs = mock_client.add_pull_request_comment.call_args[1]
    assert call_kwargs["inline_path"] == "src/main.py"
    assert call_kwargs["inline_to"] == 10
    assert call_kwargs["inline_from"] is None


# ========== Tool 5: get_pull_request_review_summary ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_review_summary_ready(mock_get_client):
    from src.server import get_pull_request_review_summary

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_client.get_pull_request_diffstat.return_value = {
        "values": [
            {"status": "modified", "lines_added": 10, "lines_removed": 5,
             "old": {"path": "src/a.py"}, "new": {"path": "src/a.py"}}
        ]
    }
    mock_client.get_pull_request_comments.return_value = {"values": []}
    mock_client.get_pull_request_statuses.return_value = {
        "values": [{"state": "SUCCESSFUL", "name": "CI", "description": "OK",
                    "url": "https://ci.example.com", "commit": {"hash": "abc123"},
                    "created_on": "2026-01-01", "updated_on": "2026-01-01"}]
    }
    mock_get_client.return_value = mock_client

    result = await get_pull_request_review_summary("my-repo", "42")

    assert result["review_readiness"] == "ready"
    assert result["diffstat"]["files_changed"] == 1
    assert result["diffstat"]["lines_added"] == 10
    assert result["diffstat"]["lines_removed"] == 5
    assert len(result["unresolved_comments"]) == 0
    assert len(result["ci_statuses"]) == 1


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_review_summary_draft(mock_get_client):
    from src.server import get_pull_request_review_summary

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = {**SAMPLE_PR_RESPONSE, "draft": True}
    mock_client.get_pull_request_diffstat.return_value = {"values": []}
    mock_client.get_pull_request_comments.return_value = {"values": []}
    mock_client.get_pull_request_statuses.return_value = {"values": []}
    mock_get_client.return_value = mock_client

    result = await get_pull_request_review_summary("my-repo", "42")

    assert result["review_readiness"] == "draft"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_review_summary_ci_failing(mock_get_client):
    from src.server import get_pull_request_review_summary

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_client.get_pull_request_diffstat.return_value = {"values": []}
    mock_client.get_pull_request_comments.return_value = {"values": []}
    mock_client.get_pull_request_statuses.return_value = {
        "values": [{"state": "FAILED", "name": "CI", "description": "Build failed",
                    "url": "https://ci.example.com", "commit": {"hash": "abc"},
                    "created_on": "2026-01-01", "updated_on": "2026-01-01"}]
    }
    mock_get_client.return_value = mock_client

    result = await get_pull_request_review_summary("my-repo", "42")

    assert result["review_readiness"] == "ci_failing"


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_get_review_summary_unresolved(mock_get_client):
    from src.server import get_pull_request_review_summary

    unresolved_comment = {
        "id": 1,
        "content": {"raw": "Fix this"},
        "user": {"display_name": "Reviewer", "nickname": "rev"},
        "created_on": "2026-01-01T00:00:00Z",
        "updated_on": "2026-01-01T00:00:00Z",
        "pending": False,
    }

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_client.get_pull_request_diffstat.return_value = {"values": []}
    mock_client.get_pull_request_comments.return_value = {"values": [unresolved_comment]}
    mock_client.get_pull_request_statuses.return_value = {"values": []}
    mock_get_client.return_value = mock_client

    result = await get_pull_request_review_summary("my-repo", "42")

    assert result["review_readiness"] == "has_unresolved_comments"
    assert len(result["unresolved_comments"]) == 1


# ========== Tool 6: suggest_pull_request_reviewers ==========

@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_suggest_reviewers_basic(mock_get_client):
    from src.server import suggest_pull_request_reviewers

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = {
        **SAMPLE_PR_RESPONSE,
        "author": {"uuid": "{author-uuid}", "display_name": "Author"},
        "reviewers": [],
    }
    mock_client.get_effective_default_reviewers.return_value = {
        "values": [
            {"user": {"uuid": "{rev-1}", "display_name": "Reviewer One"}, "reviewer_type": "repository"}
        ]
    }
    mock_client.get_pull_requests.return_value = {"values": []}
    mock_get_client.return_value = mock_client

    result = await suggest_pull_request_reviewers("my-repo", "42")

    assert len(result["suggested_reviewers"]) == 1
    assert result["suggested_reviewers"][0]["display_name"] == "Reviewer One"
    assert result["suggested_reviewers"][0]["score"] == 10
    assert result["suggested_reviewers"][0]["reason"] == "default_reviewer"
    assert result["source"]["default_reviewers"] == 1


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_suggest_reviewers_excludes_author(mock_get_client):
    from src.server import suggest_pull_request_reviewers

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = {
        **SAMPLE_PR_RESPONSE,
        "author": {"uuid": "{author-uuid}", "display_name": "Author"},
        "reviewers": [],
    }
    mock_client.get_effective_default_reviewers.return_value = {
        "values": [
            # This one is the author — should be excluded
            {"user": {"uuid": "{author-uuid}", "display_name": "Author"}, "reviewer_type": "repository"},
            {"user": {"uuid": "{rev-1}", "display_name": "Other Reviewer"}, "reviewer_type": "repository"},
        ]
    }
    mock_client.get_pull_requests.return_value = {"values": []}
    mock_get_client.return_value = mock_client

    result = await suggest_pull_request_reviewers("my-repo", "42")

    uuids = [r["account_id"] for r in result["suggested_reviewers"]]
    assert "{author-uuid}" not in uuids
    assert "{rev-1}" in uuids


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_suggest_reviewers_excludes_assigned(mock_get_client):
    from src.server import suggest_pull_request_reviewers

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = {
        **SAMPLE_PR_RESPONSE,
        "author": {"uuid": "{author-uuid}", "display_name": "Author"},
        "reviewers": [
            {"uuid": "{already-assigned}", "display_name": "Already Assigned"}
        ],
    }
    mock_client.get_effective_default_reviewers.return_value = {
        "values": [
            {"user": {"uuid": "{already-assigned}", "display_name": "Already Assigned"}, "reviewer_type": "repository"},
            {"user": {"uuid": "{new-rev}", "display_name": "New Reviewer"}, "reviewer_type": "repository"},
        ]
    }
    mock_client.get_pull_requests.return_value = {"values": []}
    mock_get_client.return_value = mock_client

    result = await suggest_pull_request_reviewers("my-repo", "42")

    suggested_uuids = [r["account_id"] for r in result["suggested_reviewers"]]
    assert "{already-assigned}" not in suggested_uuids
    assert "{new-rev}" in suggested_uuids
    assert len(result["already_assigned"]) == 1


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_suggest_reviewers_max_suggestions(mock_get_client):
    from src.server import suggest_pull_request_reviewers

    mock_client = AsyncMock()
    mock_client.get_pull_request.return_value = {
        **SAMPLE_PR_RESPONSE,
        "author": {"uuid": "{author-uuid}", "display_name": "Author"},
        "reviewers": [],
    }
    mock_client.get_effective_default_reviewers.return_value = {
        "values": [
            {"user": {"uuid": f"{{rev-{i}}}", "display_name": f"Reviewer {i}"}, "reviewer_type": "repository"}
            for i in range(10)
        ]
    }
    mock_client.get_pull_requests.return_value = {"values": []}
    mock_get_client.return_value = mock_client

    result = await suggest_pull_request_reviewers("my-repo", "42", max_suggestions=3)

    assert len(result["suggested_reviewers"]) == 3


@pytest.mark.asyncio
@patch("src.server.get_client")
async def test_submit_batch_review_partial_failure(mock_get_client):
    """Test that batch review continues on comment failure and reports partial results."""
    from src.server import submit_pull_request_batch_review

    mock_client = AsyncMock()
    # First comment succeeds, second fails, third succeeds
    mock_client.add_pull_request_comment.side_effect = [
        {},  # comment 0 OK
        Exception("API error 422"),  # comment 1 fails
        {},  # comment 2 OK
    ]
    mock_client.get_pull_request.return_value = SAMPLE_PR_RESPONSE
    mock_get_client.return_value = mock_client

    result = await submit_pull_request_batch_review(
        "my-repo", "42",
        comments=[
            {"content": "Good"},
            {"content": "Bad"},
            {"content": "Also good"},
        ],
        review_action="comment_only"
    )

    assert result["comments_posted"] == 2
    assert result["partial_failure"] is True
    assert len(result["failed_comments"]) == 1
    assert result["failed_comments"][0]["index"] == 1
