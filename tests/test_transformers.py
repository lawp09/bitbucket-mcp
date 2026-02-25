"""Tests for response transformers."""

import pytest
from src.utils.transformers import (
    slim_repository, slim_repository_list,
    slim_pull_request, slim_pull_request_list, slim_pull_request_created,
    slim_status, slim_status_list,
    slim_commit, slim_commit_list,
    slim_diffstat_entry, slim_diffstat_list,
    slim_comment, slim_comment_list,
    slim_activity_entry, slim_activity_list,
    slim_pipeline_run, slim_pipeline_run_list,
    slim_pipeline_step, slim_pipeline_step_list,
    _slim_user, _slim_paginated,
)


# ========== Fixtures ==========

SAMPLE_LINKS = {
    "self": {"href": "https://api.bitbucket.org/2.0/some/url"},
    "html": {"href": "https://bitbucket.org/some/url"},
    "avatar": {"href": "https://bytebucket.org/ravatar/xyz"},
}

SAMPLE_USER = {
    "display_name": "Philippe LAWSON",
    "links": SAMPLE_LINKS,
    "type": "user",
    "uuid": "{e7ae358e-abb2-4b2e-8e00-3976fa551c45}",
    "account_id": "5db9be213a09190c2ad5c484",
    "nickname": "Phil",
    "username": "plawson",
}

SAMPLE_REPOSITORY = {
    "type": "repository",
    "full_name": "villemontreal/my-api",
    "links": {
        "self": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api"},
        "html": {"href": "https://bitbucket.org/villemontreal/my-api"},
        "avatar": {"href": "https://bytebucket.org/ravatar/xyz"},
        "pullrequests": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/pullrequests"},
        "commits": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/commits"},
        "forks": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/forks"},
        "watchers": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/watchers"},
        "branches": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/refs/branches"},
        "tags": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/refs/tags"},
        "downloads": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/downloads"},
        "source": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/src"},
        "clone": [
            {"name": "https", "href": "https://user@bitbucket.org/villemontreal/my-api.git"},
            {"name": "ssh", "href": "git@bitbucket.org:villemontreal/my-api.git"},
        ],
        "hooks": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/hooks"},
    },
    "name": "My API",
    "slug": "my-api",
    "description": "A test API",
    "scm": "git",
    "website": "",
    "owner": {
        "display_name": "Ville",
        "links": SAMPLE_LINKS,
        "type": "team",
        "uuid": "{d20e5e52-2a96-469b-8cae-f1c4d8138517}",
        "username": "villemontreal",
    },
    "workspace": {
        "type": "workspace",
        "uuid": "{d20e5e52-2a96-469b-8cae-f1c4d8138517}",
        "name": "Ville",
        "slug": "villemontreal",
        "links": SAMPLE_LINKS,
    },
    "is_private": True,
    "project": {
        "type": "project",
        "key": "SN",
        "uuid": "{3901493a-4ba2-40e3-bb68-23205a624a76}",
        "name": "Solutions Numériques",
        "links": SAMPLE_LINKS,
    },
    "fork_policy": "no_public_forks",
    "created_on": "2023-01-01T00:00:00+00:00",
    "updated_on": "2024-06-15T12:00:00+00:00",
    "size": 12345,
    "language": "typescript",
    "uuid": "{abcd-1234}",
    "mainbranch": {"name": "develop", "type": "branch"},
    "override_settings": {},
    "parent": None,
    "has_issues": False,
    "has_wiki": False,
}

SAMPLE_PR = {
    "type": "pullrequest",
    "id": 42,
    "title": "feat: add new endpoint",
    "description": "## Summary\nAdded GET /users endpoint",
    "state": "OPEN",
    "draft": False,
    "comment_count": 3,
    "task_count": 1,
    "close_source_branch": True,
    "merge_commit": None,
    "closed_by": None,
    "reason": "",
    "author": SAMPLE_USER,
    "source": {
        "branch": {"name": "feature/users"},
        "commit": {"hash": "abc123def456", "links": SAMPLE_LINKS, "type": "commit"},
        "repository": {"type": "repository", "full_name": "villemontreal/my-api", "links": SAMPLE_LINKS},
    },
    "destination": {
        "branch": {"name": "develop"},
        "commit": {"hash": "789xyz000111", "links": SAMPLE_LINKS, "type": "commit"},
        "repository": {"type": "repository", "full_name": "villemontreal/my-api", "links": SAMPLE_LINKS},
    },
    "reviewers": [SAMPLE_USER],
    "participants": [
        {**SAMPLE_USER, "role": "REVIEWER", "approved": True},
    ],
    "links": {
        "self": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/pullrequests/42"},
        "html": {"href": "https://bitbucket.org/villemontreal/my-api/pull-requests/42"},
        "commits": {"href": "..."},
        "approve": {"href": "..."},
        "diff": {"href": "..."},
        "diffstat": {"href": "..."},
        "comments": {"href": "..."},
        "activity": {"href": "..."},
        "merge": {"href": "..."},
        "decline": {"href": "..."},
        "statuses": {"href": "..."},
    },
    "summary": {"raw": "Summary text", "markup": "markdown", "html": "<p>Summary text</p>"},
    "created_on": "2024-01-15T10:00:00+00:00",
    "updated_on": "2024-01-16T14:00:00+00:00",
}

SAMPLE_STATUS = {
    "key": "0bc4f55e5bb8c781fde499da092c5618",
    "type": "build",
    "state": "SUCCESSFUL",
    "name": "Jenkins Build #5",
    "refname": "feature/users",
    "commit": {
        "hash": "12185f94580331a0ec5c59bd9a004903a245818a",
        "links": SAMPLE_LINKS,
        "type": "commit",
    },
    "url": "https://jenkins.example.com/job/my-build/5",
    "repository": {
        "type": "repository",
        "full_name": "villemontreal/my-api",
        "links": SAMPLE_LINKS,
        "name": "my-api",
        "uuid": "{cf3ff6ba}",
    },
    "description": "Build passed",
    "created_on": "2024-01-15T10:00:00+00:00",
    "updated_on": "2024-01-15T10:05:00+00:00",
    "links": SAMPLE_LINKS,
}

SAMPLE_COMMIT = {
    "type": "commit",
    "hash": "12185f94580331a0ec5c59bd9a004903a245818a",
    "date": "2024-01-15T10:00:00+00:00",
    "author": {
        "type": "author",
        "raw": "Phil Lawson <phil@example.com>",
        "user": SAMPLE_USER,
    },
    "message": "feat: add users endpoint\n\nImplemented GET /users with pagination",
    "summary": {
        "type": "rendered",
        "raw": "feat: add users endpoint\n\nImplemented GET /users with pagination",
        "markup": "markdown",
        "html": "<p>feat: add users endpoint</p><p>Implemented GET /users with pagination</p>",
    },
    "links": {
        "self": {"href": "https://api.bitbucket.org/2.0/repositories/villemontreal/my-api/commit/12185f9458"},
        "html": {"href": "https://bitbucket.org/villemontreal/my-api/commits/12185f9458"},
        "diff": {"href": "..."},
        "approve": {"href": "..."},
        "comments": {"href": "..."},
        "statuses": {"href": "..."},
        "patch": {"href": "..."},
    },
    "parents": [{"hash": "aaa111", "links": SAMPLE_LINKS, "type": "commit"}],
}

SAMPLE_DIFFSTAT = {
    "type": "diffstat",
    "lines_added": 45,
    "lines_removed": 12,
    "status": "modified",
    "old": {
        "path": "src/users.ts",
        "type": "commit_file",
        "escaped_path": "src/users.ts",
        "links": {"self": {"href": "https://api.bitbucket.org/2.0/.../src/old/src/users.ts"}},
    },
    "new": {
        "path": "src/users.ts",
        "type": "commit_file",
        "escaped_path": "src/users.ts",
        "links": {"self": {"href": "https://api.bitbucket.org/2.0/.../src/new/src/users.ts"}},
    },
}

SAMPLE_COMMENT = {
    "id": 12345,
    "created_on": "2024-01-15T10:00:00+00:00",
    "updated_on": "2024-01-15T10:00:00+00:00",
    "content": {
        "type": "rendered",
        "raw": "Looks good, but please add tests",
        "markup": "markdown",
        "html": "<p>Looks good, but please add tests</p>",
    },
    "user": SAMPLE_USER,
    "links": SAMPLE_LINKS,
    "pullrequest": {
        "type": "pullrequest",
        "id": 42,
        "title": "feat: add new endpoint",
        "links": SAMPLE_LINKS,
    },
    "type": "pullrequest_comment",
    "is_resolved": False,
    "resolved_by": None,
    "resolved_on": None,
    "pending": False,
}


# ========== Helper Tests ==========

class TestSlimUser:
    def test_extracts_display_name(self):
        result = _slim_user(SAMPLE_USER)
        assert result["display_name"] == "Philippe LAWSON"
        assert result["nickname"] == "Phil"

    def test_strips_links_uuid_account(self):
        result = _slim_user(SAMPLE_USER)
        assert "links" not in result
        assert "uuid" not in result
        assert "account_id" not in result
        assert "type" not in result

    def test_handles_none(self):
        assert _slim_user(None) is None

    def test_handles_empty(self):
        assert _slim_user({}) is None


class TestSlimPaginated:
    def test_preserves_values_and_metadata(self):
        data = {"values": [1, 2, 3], "size": 100, "page": 1}
        result = _slim_paginated(data, lambda x: x * 10)
        assert result["values"] == [10, 20, 30]
        assert result["count"] == 3
        assert result["page"] == 1
        assert "has_more" not in result

    def test_includes_has_more_as_boolean(self):
        data = {"values": [1], "size": 100, "page": 1, "next": "https://api.bitbucket.org/2.0/...?page=2"}
        result = _slim_paginated(data, lambda x: x)
        assert result["has_more"] is True

    def test_handles_empty_values(self):
        result = _slim_paginated({"values": []}, lambda x: x)
        assert result["values"] == []


# ========== Repository Tests ==========

class TestSlimRepository:
    def test_keeps_essential_fields(self):
        result = slim_repository(SAMPLE_REPOSITORY)
        assert result["slug"] == "my-api"
        assert result["name"] == "My API"
        assert result["full_name"] == "villemontreal/my-api"
        assert result["description"] == "A test API"
        assert result["language"] == "typescript"
        assert result["is_private"] is True
        assert result["project"] == "SN"
        assert result["mainbranch"] == "develop"
        assert result["size"] == 12345

    def test_strips_links(self):
        result = slim_repository(SAMPLE_REPOSITORY)
        assert "links" not in result

    def test_strips_nested_objects(self):
        result = slim_repository(SAMPLE_REPOSITORY)
        assert "owner" not in result
        assert "workspace" not in result
        assert "type" not in result
        assert "scm" not in result
        assert "fork_policy" not in result
        assert "uuid" not in result

    def test_repository_list(self):
        data = {"values": [SAMPLE_REPOSITORY, SAMPLE_REPOSITORY], "size": 100, "page": 1}
        result = slim_repository_list(data)
        assert len(result["values"]) == 2
        assert result["values"][0]["slug"] == "my-api"
        assert "links" not in result["values"][0]

    def test_no_mainbranch(self):
        repo = {**SAMPLE_REPOSITORY, "mainbranch": None}
        result = slim_repository(repo)
        assert result["mainbranch"] is None

    def test_no_project(self):
        repo = {**SAMPLE_REPOSITORY, "project": None}
        result = slim_repository(repo)
        assert result["project"] is None


# ========== Pull Request Tests ==========

class TestSlimPullRequest:
    def test_keeps_essential_fields(self):
        result = slim_pull_request(SAMPLE_PR)
        assert result["id"] == 42
        assert result["title"] == "feat: add new endpoint"
        assert result["description"] == "## Summary\nAdded GET /users endpoint"
        assert result["state"] == "OPEN"
        assert result["draft"] is False
        assert result["author"] == "Philippe LAWSON"
        assert result["source_branch"] == "feature/users"
        assert result["destination_branch"] == "develop"
        assert result["comment_count"] == 3
        assert result["task_count"] == 1

    def test_strips_links(self):
        result = slim_pull_request(SAMPLE_PR)
        assert "links" not in result

    def test_strips_nested_noise(self):
        result = slim_pull_request(SAMPLE_PR)
        assert "type" not in result
        assert "merge_commit" not in result
        assert "closed_by" not in result
        assert "reason" not in result
        assert "summary" not in result

    def test_slim_reviewers(self):
        result = slim_pull_request(SAMPLE_PR)
        assert len(result["reviewers"]) == 1
        assert result["reviewers"][0]["display_name"] == "Philippe LAWSON"
        assert "links" not in result["reviewers"][0]
        assert "uuid" not in result["reviewers"][0]

    def test_slim_participants(self):
        result = slim_pull_request(SAMPLE_PR)
        assert len(result["participants"]) == 1
        assert result["participants"][0]["role"] == "REVIEWER"
        assert result["participants"][0]["approved"] is True
        assert "links" not in result["participants"][0]

    def test_participant_display_name_fallback(self):
        """Bitbucket puts display_name in participant.user, not participant itself."""
        pr = {
            **SAMPLE_PR,
            "participants": [
                {
                    "display_name": None,
                    "role": "REVIEWER",
                    "approved": False,
                    "type": "participant",
                    "user": {
                        "display_name": "Louis-Philippe Chouinard",
                        "links": SAMPLE_LINKS,
                        "type": "user",
                    },
                }
            ],
        }
        result = slim_pull_request(pr)
        assert result["participants"][0]["display_name"] == "Louis-Philippe Chouinard"

    def test_preserves_comment_stats(self):
        pr_with_stats = {**SAMPLE_PR, "comment_stats": {"total": 5, "resolved": 3, "unresolved": 2}}
        result = slim_pull_request(pr_with_stats)
        assert result["comment_stats"] == {"total": 5, "resolved": 3, "unresolved": 2}

    def test_no_comment_stats_if_absent(self):
        result = slim_pull_request(SAMPLE_PR)
        assert "comment_stats" not in result

    def test_empty_reviewers_and_participants(self):
        pr = {**SAMPLE_PR, "reviewers": [], "participants": []}
        result = slim_pull_request(pr)
        assert result["reviewers"] == []
        assert result["participants"] == []

    def test_missing_source_destination(self):
        pr = {**SAMPLE_PR, "source": {}, "destination": {}}
        result = slim_pull_request(pr)
        assert result["source_branch"] is None
        assert result["destination_branch"] is None


class TestSlimPullRequestList:
    def test_no_description_in_list(self):
        data = {"values": [SAMPLE_PR], "size": 1, "page": 1}
        result = slim_pull_request_list(data)
        item = result["values"][0]
        assert "description" not in item
        assert item["id"] == 42
        assert item["title"] == "feat: add new endpoint"

    def test_list_item_has_author_and_branches(self):
        data = {"values": [SAMPLE_PR], "size": 1, "page": 1}
        result = slim_pull_request_list(data)
        item = result["values"][0]
        assert item["author"] == "Philippe LAWSON"
        assert item["source_branch"] == "feature/users"
        assert item["destination_branch"] == "develop"
        assert item["draft"] is False
        assert item["comment_count"] == 3


class TestSlimPullRequestCreated:
    def test_confirmation_fields(self):
        result = slim_pull_request_created(SAMPLE_PR)
        assert result["id"] == 42
        assert result["title"] == "feat: add new endpoint"
        assert result["state"] == "OPEN"
        assert result["url"] == "https://bitbucket.org/villemontreal/my-api/pull-requests/42"
        assert result["source_branch"] == "feature/users"
        assert result["destination_branch"] == "develop"
        assert "description" not in result
        assert "links" not in result

    def test_missing_html_link(self):
        pr = {**SAMPLE_PR, "links": {}}
        result = slim_pull_request_created(pr)
        assert result["url"] is None


# ========== Status Tests ==========

class TestSlimStatus:
    def test_keeps_essential_fields(self):
        result = slim_status(SAMPLE_STATUS)
        assert result["state"] == "SUCCESSFUL"
        assert result["name"] == "Jenkins Build #5"
        assert result["description"] == "Build passed"
        assert result["url"] == "https://jenkins.example.com/job/my-build/5"
        assert result["commit_hash"] == "12185f945803"

    def test_strips_noise(self):
        result = slim_status(SAMPLE_STATUS)
        assert "repository" not in result
        assert "links" not in result
        assert "commit" not in result
        assert "key" not in result
        assert "type" not in result
        assert "refname" not in result

    def test_status_list(self):
        data = {"values": [SAMPLE_STATUS], "size": 1, "page": 1}
        result = slim_status_list(data)
        assert len(result["values"]) == 1
        assert result["values"][0]["state"] == "SUCCESSFUL"
        assert "repository" not in result["values"][0]

    def test_empty_commit_hash(self):
        status = {**SAMPLE_STATUS, "commit": {}}
        result = slim_status(status)
        assert result["commit_hash"] == ""

    def test_missing_commit(self):
        status = {**SAMPLE_STATUS}
        del status["commit"]
        result = slim_status(status)
        assert result["commit_hash"] == ""


# ========== Commit Tests ==========

class TestSlimCommit:
    def test_keeps_essential_fields(self):
        result = slim_commit(SAMPLE_COMMIT)
        assert result["hash"] == "12185f945803"
        assert result["message"] == "feat: add users endpoint\n\nImplemented GET /users with pagination"
        assert result["date"] == "2024-01-15T10:00:00+00:00"
        assert result["author"] == "Philippe LAWSON"

    def test_strips_noise(self):
        result = slim_commit(SAMPLE_COMMIT)
        assert "links" not in result
        assert "summary" not in result
        assert "parents" not in result
        assert "type" not in result

    def test_truncates_hash(self):
        result = slim_commit(SAMPLE_COMMIT)
        assert len(result["hash"]) == 12

    def test_fallback_to_raw_author(self):
        commit_no_user = {
            **SAMPLE_COMMIT,
            "author": {"type": "author", "raw": "Unknown <unknown@example.com>"},
        }
        result = slim_commit(commit_no_user)
        assert result["author"] == "Unknown <unknown@example.com>"

    def test_commit_list(self):
        data = {"values": [SAMPLE_COMMIT, SAMPLE_COMMIT], "size": 2, "page": 1}
        result = slim_commit_list(data)
        assert len(result["values"]) == 2
        assert "links" not in result["values"][0]

    def test_no_author_at_all(self):
        commit = {**SAMPLE_COMMIT, "author": {}}
        result = slim_commit(commit)
        assert result["author"] is None

    def test_short_hash(self):
        commit = {**SAMPLE_COMMIT, "hash": "abc123"}
        result = slim_commit(commit)
        assert result["hash"] == "abc123"


# ========== Diffstat Tests ==========

class TestSlimDiffstat:
    def test_keeps_essential_fields(self):
        result = slim_diffstat_entry(SAMPLE_DIFFSTAT)
        assert result["status"] == "modified"
        assert result["lines_added"] == 45
        assert result["lines_removed"] == 12
        assert result["old_path"] == "src/users.ts"
        assert result["new_path"] == "src/users.ts"

    def test_strips_noise(self):
        result = slim_diffstat_entry(SAMPLE_DIFFSTAT)
        assert "type" not in result
        assert "old" not in result
        assert "new" not in result

    def test_handles_new_file(self):
        new_file = {**SAMPLE_DIFFSTAT, "old": None, "status": "added"}
        result = slim_diffstat_entry(new_file)
        assert result["old_path"] is None
        assert result["new_path"] == "src/users.ts"
        assert result["status"] == "added"

    def test_diffstat_list(self):
        data = {"values": [SAMPLE_DIFFSTAT], "size": 1, "page": 1}
        result = slim_diffstat_list(data)
        assert len(result["values"]) == 1
        assert "type" not in result["values"][0]

    def test_renamed_file(self):
        renamed = {
            **SAMPLE_DIFFSTAT,
            "status": "renamed",
            "old": {**SAMPLE_DIFFSTAT["old"], "path": "src/old_name.ts"},
            "new": {**SAMPLE_DIFFSTAT["new"], "path": "src/new_name.ts"},
        }
        result = slim_diffstat_entry(renamed)
        assert result["status"] == "renamed"
        assert result["old_path"] == "src/old_name.ts"
        assert result["new_path"] == "src/new_name.ts"

    def test_deleted_file(self):
        deleted = {**SAMPLE_DIFFSTAT, "status": "removed", "new": None}
        result = slim_diffstat_entry(deleted)
        assert result["status"] == "removed"
        assert result["old_path"] == "src/users.ts"
        assert result["new_path"] is None


# ========== Comment Tests ==========

class TestSlimComment:
    def test_keeps_essential_fields(self):
        result = slim_comment(SAMPLE_COMMENT)
        assert result["id"] == 12345
        assert result["content"] == "Looks good, but please add tests"
        assert result["author"]["display_name"] == "Philippe LAWSON"
        assert result["is_resolved"] is False

    def test_strips_html_rendition(self):
        result = slim_comment(SAMPLE_COMMENT)
        assert "html" not in str(result.get("content", ""))

    def test_strips_noise(self):
        result = slim_comment(SAMPLE_COMMENT)
        assert "links" not in result
        assert "pullrequest" not in result
        assert "type" not in result

    def test_includes_inline_when_present(self):
        inline_comment = {
            **SAMPLE_COMMENT,
            "inline": {"path": "src/users.ts", "from": None, "to": 42},
        }
        result = slim_comment(inline_comment)
        assert result["inline"]["path"] == "src/users.ts"
        assert result["inline"]["to"] == 42

    def test_no_inline_when_absent(self):
        result = slim_comment(SAMPLE_COMMENT)
        assert "inline" not in result

    def test_includes_parent_id(self):
        reply = {**SAMPLE_COMMENT, "parent": {"id": 999}}
        result = slim_comment(reply)
        assert result["parent_id"] == 999

    def test_resolved_comment(self):
        resolved = {
            **SAMPLE_COMMENT,
            "is_resolved": True,
            "resolved_by": "Philippe LAWSON",
            "resolved_on": "2024-01-16T10:00:00+00:00",
        }
        result = slim_comment(resolved)
        assert result["is_resolved"] is True
        assert result["resolved_by"] == "Philippe LAWSON"
        assert result["resolved_on"] == "2024-01-16T10:00:00+00:00"

    def test_no_parent_when_absent(self):
        result = slim_comment(SAMPLE_COMMENT)
        assert "parent_id" not in result

    def test_comment_list(self):
        data = {"values": [SAMPLE_COMMENT], "size": 1, "page": 1}
        result = slim_comment_list(data)
        assert len(result["values"]) == 1
        assert result["values"][0]["id"] == 12345


# ========== Activity Tests ==========

class TestSlimActivity:
    def test_update_activity(self):
        entry = {
            "pull_request": {"type": "pullrequest", "id": 42, "title": "...", "links": SAMPLE_LINKS},
            "update": {
                "state": "OPEN",
                "draft": False,
                "title": "feat: add new endpoint",
                "description": "Long description...",
                "date": "2024-01-15T10:00:00+00:00",
                "author": SAMPLE_USER,
                "reviewers": [SAMPLE_USER],
                "source": {"branch": {"name": "feature/users"}},
                "destination": {"branch": {"name": "develop"}},
            },
        }
        result = slim_activity_entry(entry)
        assert result["type"] == "update"
        assert result["update"]["state"] == "OPEN"
        assert result["update"]["title"] == "feat: add new endpoint"
        assert "pull_request" not in result
        assert "description" not in result["update"]
        assert "reviewers" not in result["update"]

    def test_comment_activity(self):
        entry = {
            "pull_request": {"type": "pullrequest", "id": 42, "links": SAMPLE_LINKS},
            "comment": SAMPLE_COMMENT,
        }
        result = slim_activity_entry(entry)
        assert result["type"] == "comment"
        assert result["comment"]["id"] == 12345
        assert "pull_request" not in result

    def test_approval_activity(self):
        entry = {
            "pull_request": {"type": "pullrequest", "id": 42, "links": SAMPLE_LINKS},
            "approval": {
                "date": "2024-01-15T10:00:00+00:00",
                "user": SAMPLE_USER,
            },
        }
        result = slim_activity_entry(entry)
        assert result["type"] == "approval"
        assert result["approval"]["user"]["display_name"] == "Philippe LAWSON"
        assert "pull_request" not in result

    def test_unknown_activity_type(self):
        entry = {"pull_request": {"id": 42}, "some_new_type": {"data": "value"}}
        result = slim_activity_entry(entry)
        assert result["type"] == "unknown"

    def test_activity_list(self):
        entries = [
            {"pull_request": {}, "update": {"state": "OPEN", "draft": False, "title": "t", "author": SAMPLE_USER}},
            {"pull_request": {}, "comment": SAMPLE_COMMENT},
        ]
        data = {"values": entries, "size": 2, "page": 1}
        result = slim_activity_list(data)
        assert len(result["values"]) == 2
        assert result["values"][0]["type"] == "update"
        assert result["values"][1]["type"] == "comment"


# ========== Pipeline Tests ==========

class TestSlimPipeline:
    def test_slim_pipeline_run(self):
        run = {
            "type": "pipeline",
            "uuid": "{abc-123}",
            "build_number": 42,
            "state": {"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}},
            "target": {
                "ref_name": "develop",
                "selector": {"pattern": "develop"},
            },
            "trigger": {"name": "push"},
            "duration_in_seconds": 120,
            "created_on": "2024-01-15T10:00:00+00:00",
            "completed_on": "2024-01-15T10:02:00+00:00",
            "links": SAMPLE_LINKS,
            "repository": {"type": "repository", "full_name": "villemontreal/my-api", "links": SAMPLE_LINKS},
        }
        result = slim_pipeline_run(run)
        assert result["uuid"] == "{abc-123}"
        assert result["build_number"] == 42
        assert result["state"] == "COMPLETED"
        assert result["state_result"] == "SUCCESSFUL"
        assert result["target_branch"] == "develop"
        assert result["trigger"] == "push"
        assert result["duration_in_seconds"] == 120
        assert "links" not in result
        assert "repository" not in result
        assert "type" not in result

    def test_pipeline_run_fallback_to_selector_pattern(self):
        run = {
            "uuid": "{abc-123}",
            "build_number": 1,
            "state": {"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}},
            "target": {"selector": {"pattern": "main"}},
            "trigger": {"name": "push"},
            "duration_in_seconds": 60,
            "created_on": "2024-01-15T10:00:00+00:00",
            "completed_on": "2024-01-15T10:01:00+00:00",
        }
        result = slim_pipeline_run(run)
        assert result["target_branch"] == "main"

    def test_pipeline_run_in_progress(self):
        run = {
            "uuid": "{abc-456}",
            "build_number": 2,
            "state": {"name": "IN_PROGRESS"},
            "target": {"ref_name": "develop"},
            "trigger": {"name": "push"},
            "duration_in_seconds": None,
            "created_on": "2024-01-15T10:00:00+00:00",
            "completed_on": None,
        }
        result = slim_pipeline_run(run)
        assert result["state"] == "IN_PROGRESS"
        assert result["state_result"] is None
        assert result["completed_on"] is None

    def test_pipeline_run_list(self):
        run = {
            "uuid": "{abc}",
            "build_number": 1,
            "state": {"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}},
            "target": {"ref_name": "main"},
            "trigger": {"name": "push"},
            "duration_in_seconds": 60,
            "created_on": "2024-01-15T10:00:00+00:00",
            "completed_on": "2024-01-15T10:01:00+00:00",
        }
        data = {"values": [run], "size": 1, "page": 1}
        result = slim_pipeline_run_list(data)
        assert len(result["values"]) == 1
        assert result["values"][0]["uuid"] == "{abc}"
        assert result["count"] == 1

    def test_slim_pipeline_step(self):
        step = {
            "type": "pipeline_step",
            "uuid": "{step-1}",
            "name": "Build",
            "state": {"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}},
            "duration_in_seconds": 60,
            "started_on": "2024-01-15T10:00:00+00:00",
            "completed_on": "2024-01-15T10:01:00+00:00",
            "links": SAMPLE_LINKS,
        }
        result = slim_pipeline_step(step)
        assert result["uuid"] == "{step-1}"
        assert result["name"] == "Build"
        assert result["state"] == "COMPLETED"
        assert result["state_result"] == "SUCCESSFUL"
        assert "links" not in result
        assert "type" not in result

    def test_pipeline_step_list(self):
        step = {
            "uuid": "{step-1}",
            "name": "Build",
            "state": {"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}},
            "duration_in_seconds": 60,
            "started_on": "2024-01-15T10:00:00+00:00",
            "completed_on": "2024-01-15T10:01:00+00:00",
        }
        data = {"values": [step], "size": 1, "page": 1}
        result = slim_pipeline_step_list(data)
        assert len(result["values"]) == 1
        assert result["values"][0]["name"] == "Build"
        assert result["count"] == 1


# ========== Size Reduction Tests ==========

class TestSizeReduction:
    """Verify that transformers actually reduce the response size."""

    def _json_size(self, obj):
        import json
        return len(json.dumps(obj, default=str))

    def test_repository_reduction(self):
        original = self._json_size(SAMPLE_REPOSITORY)
        slimmed = self._json_size(slim_repository(SAMPLE_REPOSITORY))
        reduction = (original - slimmed) / original * 100
        assert reduction > 50, f"Expected >50% reduction, got {reduction:.0f}%"

    def test_status_reduction(self):
        original = self._json_size(SAMPLE_STATUS)
        slimmed = self._json_size(slim_status(SAMPLE_STATUS))
        reduction = (original - slimmed) / original * 100
        assert reduction > 40, f"Expected >40% reduction, got {reduction:.0f}%"

    def test_commit_reduction(self):
        original = self._json_size(SAMPLE_COMMIT)
        slimmed = self._json_size(slim_commit(SAMPLE_COMMIT))
        reduction = (original - slimmed) / original * 100
        assert reduction > 50, f"Expected >50% reduction, got {reduction:.0f}%"

    def test_diffstat_reduction(self):
        original = self._json_size(SAMPLE_DIFFSTAT)
        slimmed = self._json_size(slim_diffstat_entry(SAMPLE_DIFFSTAT))
        reduction = (original - slimmed) / original * 100
        assert reduction > 30, f"Expected >30% reduction, got {reduction:.0f}%"

    def test_comment_reduction(self):
        original = self._json_size(SAMPLE_COMMENT)
        slimmed = self._json_size(slim_comment(SAMPLE_COMMENT))
        reduction = (original - slimmed) / original * 100
        assert reduction > 40, f"Expected >40% reduction, got {reduction:.0f}%"


# ========== Default Reviewers Tests ==========

class TestSlimReviewer:
    def test_slim_reviewer(self):
        from src.utils.transformers import slim_reviewer

        reviewer = {
            "display_name": "John Doe",
            "nickname": "jdoe",
            "uuid": "{abc-123}",
            "reviewer_type": "user",
            "type": "user",
            "links": {"self": {"href": "https://..."}},
            "account_id": "123456",
        }

        result = slim_reviewer(reviewer)

        assert result == {
            "display_name": "John Doe",
            "nickname": "jdoe",
            "uuid": "{abc-123}",
            "type": "user",
        }
