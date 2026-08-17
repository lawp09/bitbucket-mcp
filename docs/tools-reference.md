# MCP Tools Reference

The bitbucket-mcp server provides 96 tools (plus 4 prompts), declared in `configs/tools.json`. The catalog below groups them by theme; the JSON groups them into 11 configuration categories.

## Tools by Category

| Category | Tools |
|----------|-------|
| **Repositories** | `list_repositories`, `get_repository`, `get_repository_tags` |
| **Pull Requests** | `get_pull_requests`, `get_pull_request`, `create_pull_request`, `update_pull_request`, `approve_pull_request`, `unapprove_pull_request`, `request_changes_pull_request`, `unrequest_changes_pull_request`, `decline_pull_request`, `merge_pull_request` |
| **Comments** | `get_pull_request_comments`, `add_pull_request_comment`, `get_pull_request_comment`, `update_pull_request_comment`, `delete_pull_request_comment`, `resolve_pull_request_comment`, `reopen_pull_request_comment`, `get_pull_request_activity` |
| **Tasks PR** | `get_pull_request_tasks`, `get_pull_request_task`, `create_pull_request_task`, `update_pull_request_task`, `delete_pull_request_task` |
| **Diff / Review** | `get_pull_request_diff`, `get_pull_request_patch`, `get_pull_request_diffstat`, `get_pull_request_commits` |
| **PR Discovery** | `get_pull_requests_pending_review` |
| **Build / CI** | `get_pull_request_statuses`, `get_commit_statuses` |
| **Pipelines** | `list_pipeline_runs`, `get_pipeline_run`, `get_pipeline_steps`, `get_pipeline_step_logs`, `run_pipeline`, `stop_pipeline` |
| **Pipelines Config** | `get_pipeline_config`, `list_pipeline_variables`, `get_pipeline_variable`, `create_pipeline_variable`, `update_pipeline_variable`, `delete_pipeline_variable`, `list_pipeline_schedules`, `get_pipeline_schedule`, `list_pipeline_schedule_executions`, `create_pipeline_schedule`, `update_pipeline_schedule`, `delete_pipeline_schedule`, `list_pipeline_caches`, `delete_pipeline_cache` |
| **Reviewers** | `get_effective_default_reviewers`, `suggest_pull_request_reviewers` |
| **Draft PR** | `create_draft_pull_request`, `publish_draft_pull_request`, `convert_pull_request_to_draft` |
| **Batch Review** | `submit_pull_request_batch_review` |
| **Review Summary** | `get_pull_request_review_summary` |
| **Issues** | `list_issues`, `get_issue`, `create_issue`, `update_issue`, `delete_issue`, `get_issue_comments`, `get_issue_comment`, `add_issue_comment`, `update_issue_comment`, `delete_issue_comment` |
| **Commits** | `list_commits`, `get_commit`, `get_commit_comments`, `get_commit_comment`, `add_commit_comment` |
| **Source** | `get_file_content`, `list_directory` |
| **Deployments** | `list_environments`, `get_environment`, `create_environment`, `delete_environment`, `list_deployments`, `get_deployment`, `list_deployment_variables`, `create_deployment_variable`, `update_deployment_variable`, `delete_deployment_variable` |
| **Branch Restrictions** | `list_branch_restrictions`, `get_branch_restriction`, `create_branch_restriction`, `update_branch_restriction`, `delete_branch_restriction` |
| **Workspace** | `list_workspace_members`, `get_workspace_member`, `list_workspace_permissions`, `list_repository_permissions` |

## Tool Annotations (MCP 2025)

Every tool advertises behavioural hints:
- **`readOnlyHint`**: Tool does not modify state
- **`destructiveHint`**: Tool may delete or merge data
- **`idempotentHint`**: Tool can be safely retried
- **`openWorldHint`**: Tool may access external data (always `False` — closed domain)

Clients use these hints to auto-enable read-only tools and warn before destructive operations.

**They are never declared at the decorator site.** `conditional_tool` derives them from the
tool's name prefix (`get_`/`list_` → read-only, `delete_` → destructive…), with
`_ANNOTATION_OVERRIDES` for atypical verbs (`suggest_*` is read-only, toggles are
idempotent, `merge_`/`decline_`/`stop_pipeline` are destructive) and `_TITLE_OVERRIDES` for
the human-readable `title`. Adding a tool whose name matches no prefix means adding an
override — a test asserts every registered tool is covered.

## Disabled by Default

**Safety**: `merge_pull_request`, `stop_pipeline`, `delete_issue`, `delete_issue_comment`

**Write ops**: `add_commit_comment`, `create_pipeline_variable`, `update_pipeline_variable`, `delete_pipeline_variable`, `create_pipeline_schedule`, `update_pipeline_schedule`, `delete_pipeline_schedule`, `delete_pipeline_cache`, `create_environment`, `delete_environment`, `create_deployment_variable`, `update_deployment_variable`, `delete_deployment_variable`, `create_branch_restriction`, `update_branch_restriction`, `delete_branch_restriction`

**API limitations**: `get_pull_request_patch` (use `get_pull_request_diff` for AI review), `convert_pull_request_to_draft` (not supported by Bitbucket API)

## Token Optimization

**`get_pull_request_diff` accepts an optional `path` parameter** to filter the diff to a single file, reducing token usage by ~95% on large PRs:

```python
get_pull_request_diff(repo_slug="my-repo", pull_request_id="42", path="src/services/myService.ts")
```
