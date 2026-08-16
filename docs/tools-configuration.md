# Tool Configuration

Tools can be enabled or disabled via configuration. This allows you to restrict access to destructive operations or experimental features.

## Enable/Disable Tools

Edit `configs/tools.json`:

```json
{
  "tools": {
    "pull_requests": {
      "merge_pull_request": {
        "enabled": false,
        "description": "Merge a pull request"
      }
    }
  }
}
```

## Runtime Override via Environment Variable

Set `BITBUCKET_TOOLS_CONFIG` to point to a custom JSON file without modifying the bundled config:

```bash
export BITBUCKET_TOOLS_CONFIG=/path/to/my-tools.json
```

**Fallback chain**: `BITBUCKET_TOOLS_CONFIG` → `configs/tools.json` (built-in default)

**Error handling**: An explicit path that is missing or invalid raises a hard error at startup.

## Configuration for Prompts

MCP Prompts are configured under a separate `prompts` key in `configs/tools.json` (not under `tools`). This keeps the configuration clean and does not pollute tool annotations.

```json
{
  "prompts": {
    "review_pull_request": {
      "enabled": true
    }
  }
}
```
