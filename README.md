# mcp-creator

Create, build, and publish Python MCP servers to PyPI — conversationally.

Install `mcp-creator`, add it to your AI assistant, and it walks you through the entire process: naming your package, scaffolding a complete project, building, and publishing to PyPI.

## Install

```bash
pip install mcp-creator
```

## Setup

Add to Claude Code (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "mcp-creator": {
      "command": "mcp-creator",
      "args": []
    }
  }
}
```

Or for Cursor (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "mcp-creator": {
      "command": "mcp-creator",
      "args": []
    }
  }
}
```

## Tools

| Tool | What it does |
|------|-------------|
| `get_creator_profile` | Load your persistent profile — setup status, project history. Called first every session. |
| `update_creator_profile` | Save setup state, usernames, and project history across sessions |
| `check_setup` | Detect what's installed (uv, git, gh, PyPI token) — only walks through missing steps |
| `check_pypi_name` | Check if a package name is available on PyPI |
| `scaffold_server` | Create a complete MCP server project from a name + description + tool definitions |
| `add_tool` | Add a new tool to an existing scaffolded project |
| `build_package` | Run `uv build` on the project |
| `publish_package` | Run `uv publish` to PyPI |
| `setup_github` | Initialize git, create a GitHub repo, and push the code |
| `generate_launchguide` | Create LAUNCHGUIDE.md for marketplace submission |

## How It Works

1. **Tell your AI what you want to build**: "I want an MCP server that checks the weather"
2. **It checks the name**: calls `check_pypi_name` to verify availability on PyPI
3. **It scaffolds the project**: calls `scaffold_server` with your tool definitions — generates a complete, runnable project
4. **You fill in the logic**: replace the TODO stubs in `services/` with your real API calls
5. **Build & publish**: `build_package` → `publish_package` → live on PyPI
6. **Push to GitHub**: `setup_github` creates a repo and pushes your code
7. **Submit to marketplace**: `generate_launchguide` creates the submission file with your repo URL

## What Gets Generated

For a project named `my-weather-mcp` with a `get_weather` tool:

```
my-weather-mcp/
├── pyproject.toml         ← hatchling build, mcp[cli] dep, CLI entry point
├── README.md              ← install instructions + MCP config JSON
├── .gitignore
├── src/my_weather_mcp/
│   ├── __init__.py
│   ├── server.py          ← FastMCP + @mcp.tool() for each tool
│   ├── transport.py
│   ├── tools/
│   │   ├── __init__.py
│   │   └── get_weather.py
│   └── services/
│       ├── __init__.py
│       └── get_weather_service.py  ← TODO: your logic here
└── tests/
    ├── test_server.py
    └── test_get_weather.py
```

The generated server runs immediately — stub services return placeholder data so you can test before implementing real logic.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (for building and publishing)

## Development

```bash
git clone https://github.com/gmoneyn/mcp-creator.git
cd mcp-creator
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -v
```
