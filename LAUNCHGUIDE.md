# mcp-creator

## Tagline
Create, build, and publish Python MCP servers to PyPI — conversationally.

## Description
MCP Creator is a meta-tool that helps anyone create their own MCP servers. Install it, add it to your AI assistant, and the assistant walks you through the entire process: naming your package, checking PyPI availability, scaffolding a complete project with FastMCP, building, and publishing. Zero configuration required — just describe what you want to build and it handles the rest. Perfect for beginners who want to create and share their own MCP tools.

## Setup Requirements
No environment variables required. Just install and add to your MCP config.

## Category
Developer Tools

## Features
- Check PyPI package name availability before you start
- Scaffold a complete, runnable MCP server project from a description and tool definitions
- Generated projects use FastMCP, hatchling, and follow Python packaging best practices
- Add new tools to existing projects without manual wiring
- Build and publish to PyPI directly from your AI assistant
- Generate LAUNCHGUIDE.md for MCP Marketplace submission
- Zero external dependencies beyond mcp[cli] — installs instantly

## Getting Started
- "Create an MCP server that translates text between languages"
- "I want to build an MCP that checks domain name availability"
- "Help me make an MCP server for managing my Notion pages"
- Tool: check_pypi_name — Verify your package name is available on PyPI
- Tool: scaffold_server — Generate a complete project from tool definitions
- Tool: add_tool — Add new tools to an existing project
- Tool: build_package — Build with uv
- Tool: publish_package — Publish to PyPI
- Tool: generate_launchguide — Create marketplace submission file

## Tags
mcp, developer-tools, scaffolding, python, pypi, code-generation, fastmcp

## Documentation URL
https://pypi.org/project/mcp-creator/
