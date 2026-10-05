# mcp-creator

## Tagline
Create, build, and publish Python MCP servers to PyPI — conversationally.

## Description
MCP Creator is a meta-tool that helps anyone create their own MCP servers. Install it, add it to your AI assistant, and the assistant walks you through the entire process: naming your package, checking PyPI availability, scaffolding a complete project with FastMCP, building, publishing, and pushing to GitHub. It remembers your setup across sessions so returning creators skip straight to building. Zero configuration required — just describe what you want to build and it handles the rest. Perfect for beginners who want to create and share their own MCP tools.

## Setup Requirements
No environment variables required. Just install and add to your MCP config.

## Category
Developer Tools

## Features
- Persistent creator profile — remembers your setup, usernames, and project history across sessions
- Detects installed tools (uv, git, gh, PyPI token) and only walks through what's missing
- Check PyPI package name availability before you start
- Scaffold a complete, runnable MCP server project from a description and tool definitions
- Generated projects use FastMCP, hatchling, and follow Python packaging best practices
- Add new tools to existing projects without manual wiring
- Build and publish to PyPI directly from your AI assistant
- Initialize git, create a GitHub repo, and push code in one step
- Generate LAUNCHGUIDE.md for MCP Marketplace submission
- Zero external dependencies beyond mcp[cli] — installs instantly

## Getting Started
- "Create an MCP server that translates text between languages"
- "I want to build an MCP that checks domain name availability"
- "Help me make an MCP server for managing my Notion pages"
- Tool: get_creator_profile — Load your profile and project history
- Tool: update_creator_profile — Save setup state and project history across sessions
- Tool: check_setup — Detect what's installed and skip setup you've already done
- Tool: check_pypi_name — Verify your package name is available on PyPI
- Tool: scaffold_server — Generate a complete project from tool definitions
- Tool: add_tool — Add new tools to an existing project
- Tool: build_package — Build with uv
- Tool: publish_package — Publish to PyPI
- Tool: setup_github — Create a GitHub repo and push your code
- Tool: generate_launchguide — Create marketplace submission file

## Tags
mcp, developer-tools, scaffolding, python, pypi, code-generation, fastmcp, github, publishing

## Documentation URL
https://github.com/gmoneyn/mcp-creator
