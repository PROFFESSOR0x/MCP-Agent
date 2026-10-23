<div align="center">

# 🍯 MCP-Agent

**Turn any chatbot that supports Remote MCP into an AI agent on your computer.**

Read files, search your project, edit content, and run commands through a local MCP server—with explicit access levels and token authentication.

[English](README.md) · [العربية](README_AR.md)

`Single Python file` · `Linux / macOS / Windows` · `Python 3.10+`

</div>

---

## What it does

Run `mcp_agent.py` and connect any client that supports Remote MCP to your computer, including compatible Claude and ChatGPT clients. The server can expose tools to:

- Browse directories and find files.
- Read text files, send image files to vision-capable models, and render selected PDF pages—including scanned pages—as image content.
- Search text using regular expressions.
- Create, edit, and patch files with contextual unified diffs, then move or delete them (depending on access level).
- Run shell commands and Python snippets (unless disabled).
- Expose the MCP endpoint through ngrok, or run locally without a public tunnel.

The interface language can be selected with `--lang` or `-lang`. See [Language selection](#language-selection).

## Persistent settings and logs

MCP-Agent stores user-level settings and logs in `~/.mcp-agent/` (independent of the checkout). Daily logs are written to `~/.mcp-agent/logs/`, rotated at 10 MiB with up to five backups. Tool calls log inputs, outputs, and exceptions with sensitive values redacted and payloads capped.

```bash
# Save a static ngrok domain (requires a domain assigned to your ngrok account)
python mcp_agent.py --save-domain your-name.ngrok-free.app

# Use the saved domain automatically; override it for one run with a random URL
python mcp_agent.py --auto
python mcp_agent.py --random-url

# Inspect configuration (secrets are not displayed) and recent logs
python mcp_agent.py --show-config
python mcp_agent.py --logs
```

The user `.env` file is created with owner-only permissions. Keep it private; it may contain the ngrok authtoken.

## Quick start

Requirements: Python 3.10 or newer. A working ngrok account is needed only when using the public tunnel.

```bash
# Read-only access (default)
python mcp_agent.py

# Read/write and execution tools for one workspace
python mcp_agent.py --access operate --workspace ~/myproject

# Full access to the machine — use with care
python mcp_agent.py --access full

# Local endpoint only; do not start ngrok
python mcp_agent.py --access read-only --no-ngrok

# Arabic interface
python mcp_agent.py --lang ar

# English interface
python mcp_agent.py --lang en
```

On first launch, the program checks its dependencies and installs missing packages, including Pillow for image normalization and PyMuPDF for PDF page rendering. On Linux/macOS, it normally creates a dedicated virtual environment at `~/.claude_agent_mcp/venv` and re-launches itself inside it. This legacy directory name is retained for compatibility with existing installations. If ngrok is enabled and is not configured, follow the prompts to authenticate.

## Language selection

Choose Arabic or English using either spelling of the language option:

```bash
python mcp_agent.py --lang ar
python mcp_agent.py -lang ar

python mcp_agent.py --lang en
python mcp_agent.py -lang en
```

Supported values are `ar` and `en`. If neither option is supplied, the program checks `MCP_AGENT_LANG`, then the system locale, and falls back to English if the locale is not Arabic.

```bash
# Set the default language for this launch
MCP_AGENT_LANG=ar python mcp_agent.py
```

The language option changes the command-line messages and help text. MCP tool names and their descriptions remain in English to preserve compatibility with clients.

## Connect a remote MCP client

1. Start the server and copy the complete Connector URL printed in the terminal. With ngrok it resembles `https://your-domain.ngrok-free.app/<TOKEN>/mcp`.
2. In your MCP client, open its connector or developer settings and add a custom Remote MCP connector. In Claude.ai, this is **Settings → Connectors → Add custom connector**; other clients may use a different setup flow or require specific account settings.
3. Paste the URL as printed. The token is embedded in this URL, so treat the entire URL as a secret.
4. Enable the connector in a conversation and try asking it to list files in your workspace. ChatGPT support depends on the available MCP connector features and account/workspace settings.

Clients that support bearer authorization can instead use the base endpoint ending in `/mcp` with `Authorization: Bearer <TOKEN>`.

## Access levels

| Level | Read | Write | Run commands | Workspace |
|---|---|---|---|---|
| `read-only` (default) | Any file on the machine | No | No | Optional |
| `operate` | Inside workspace | Inside workspace | Yes, unless `--no-exec` | Required |
| `full` | Any file on the machine | Anywhere | Yes, unless `--no-exec` | Optional |

Tools that are not allowed for the selected level are not registered with the MCP server. In `operate`, file operations are restricted to the workspace, including resolved paths and symlinks.

### Important execution warning

**`operate` is not a security sandbox when command execution is enabled.** File tools are restricted to the workspace, but a shell command can still access other paths with the operating-system permissions of the user running this process. For stricter file-only operation, use:

```bash
python mcp_agent.py --access operate --workspace ~/myproject --no-exec
```

Use `full` only when necessary, and run the process under an OS account with only the permissions it needs.

## Available tools

| Tool | Purpose | `read-only` | `operate` | `full` |
|---|---|:---:|:---:|:---:|
| `get_access_info` | Report access level, workspace, OS, and enabled capabilities | Yes | Yes | Yes |
| `list_directory` | List directory entries, optionally recursively | Yes | Yes | Yes |
| `read_file` | Read text files, attach image files as vision content, or render selected PDF pages as images (including scanned PDFs) | Yes | Yes | Yes |
| `find_files` | Find files by name or glob | Yes | Yes | Yes |
| `search_text` | Search text with a regular expression | Yes | Yes | Yes |
| `parallel` | Run up to 8 enabled tools concurrently; results preserve request order | Yes | Yes | Yes |
| `write_file` | Create or overwrite a file | No | Yes | Yes |
| `edit_file` | Replace an exact text segment | No | Yes | Yes |
| `apply_patch` | Apply strict, contextual unified-diff hunks to one existing UTF-8 text file | No | Yes | Yes |
| `make_directory` | Create a directory | No | Yes | Yes |
| `move_path` | Move or rename a path | No | Yes | Yes |
| `delete_path` | Delete a file or directory | No | Yes | Yes |
| `run_command` | Run a shell command | No | Yes* | Yes* |
| `run_python` | Run a Python snippet | No | Yes* | Yes* |

`*` Execution tools are disabled when `--no-exec` is set.

### Visual reads: images and PDFs

`read_file` returns image files as native MCP image content so vision-capable clients can inspect the image directly. For PDFs, it renders pages as images instead of relying only on embedded text; this supports scanned documents, handwriting, tables, and diagrams without a separate OCR dependency. Images are normalized and resized before being attached.

- `read_file(path="scan.png")` — attach an image.
- `read_file(path="scan.pdf", page_start=3)` — render page 3 only.
- `read_file(path="scan.pdf", page_start=3, page_end=6)` — render pages 3–6 inclusive.
- PDF page numbers start at 1; one call can return up to 8 pages. Split larger ranges across calls.
- Inputs are limited to 40 MiB per image and 100 MiB per PDF. PDF output is bounded to 8 pages per call.
- The client/model must support MCP image content and vision to interpret the returned images.

### `parallel`

Use `parallel` for independent tool calls that do not depend on each other's results. Pass a list of objects with `tool` and optional `arguments` fields:

```json
{
  "calls": [
    {"tool": "list_directory", "arguments": {"path": "."}},
    {"tool": "search_text", "arguments": {"path": ".", "pattern": "TODO", "glob": "*.py"}},
    {"tool": "read_file", "arguments": {"path": "README.md", "start_line": 1, "max_lines": 30}}
  ]
}
```

Up to 8 calls execute concurrently; results are presented in the same order as the input. Each call is checked against the tools available at the current access level, and individual failures are reported without discarding other results. Nested `parallel` calls are rejected. Do not run dependent steps in the same batch or concurrently write to the same file. Image results from parallel reads are also returned as image content (up to 12 images per batch); aggregate text output is capped at 30,000 characters.

### `apply_patch`

Use `apply_patch` for code changes that need surrounding context, multiple edits, or precise line-level modifications. It accepts a unified diff for **one existing UTF-8 text file**. Standard `---` / `+++` headers are optional; one or more `@@` hunks are required.

```diff
--- a/example.py
+++ b/example.py
@@ -1,3 +1,4 @@
 def greet(name):
-    return f"Hello {name}"
+    message = f"Hello {name}"
+    return message
```

The tool validates every hunk against the current file and fails without changing the file if any context does not match. It writes through a temporary file and atomic replacement after all hunks validate. It does not create or delete files; use `write_file` for new files. The target path is still checked against the active access level, and the tool is only available in `operate` and `full` modes.

## Command-line options

| Option | Description |
|---|---|
| `--access`, `-access` | `read-only`, `operate`, or `full` (default: `read-only`; `readonly` is also accepted) |
| `--workspace`, `-w` | Default workspace; required with `operate` |
| `--port` | Preferred local port (default: `8765`; another available port is selected if needed) |
| `--token` | Provide an MCP token; otherwise one is generated. Also reads `MCP_AUTH_TOKEN` |
| `--domain` | Optional static ngrok domain |
| `--ngrok-authtoken` | ngrok token; alternatively set `NGROK_AUTHTOKEN` |
| `--no-ngrok` | Run locally without a public tunnel |
| `--no-exec` | Disable shell and Python execution tools |
| `--max-timeout` | Maximum execution timeout in seconds (default: `600`) |
| `--lang`, `-lang` | Interface language: `ar` or `en`; defaults to `MCP_AGENT_LANG` or system locale |

### Useful configurations

```bash
# Fixed domain and a manually supplied token (keep the token secret)
python mcp_agent.py --access operate -w ~/project --domain your-name.ngrok-free.app --token "YOUR_LONG_RANDOM_TOKEN"

# Local-only mode
python mcp_agent.py --access read-only --no-ngrok

# Non-interactive launch
NGROK_AUTHTOKEN=your-ngrok-token python mcp_agent.py --access operate -w /srv/app
```

Avoid placing real secrets directly in shell history, screenshots, issue reports, or public logs.

## How it works

```text
MCP client ── HTTPS ──> ngrok (optional) ──> AuthASGI ──> FastMCP / Streamable HTTP
                                                            │
                                                            └── File and execution tools
```

- Uses the MCP Streamable HTTP transport.
- Accepts the token from the URL path or an `Authorization: Bearer` header.
- Uses `hmac.compare_digest` for token comparisons.
- Logs tool calls to the terminal.
- Exposes tools according to the selected access level and execution setting.

## Security checklist

- Treat the Connector URL and token as credentials. Never publish or share them.
- Start with `read-only`; use `operate` for a specific project when write access is required.
- In `read-only` and `full`, file reads can include sensitive files such as SSH keys and `.env` files.
- Remember that `operate` plus command execution is not a sandbox; use `--no-exec` when shell access is not needed.
- Stop the server with `Ctrl+C` when finished.

## Troubleshooting

| Problem | What to try |
|---|---|
| venv creation fails on Debian/Ubuntu | Install the OS package: `sudo apt install python3-venv` |
| ngrok reports `ERR_NGROK_108` | Another tunnel session may be active; stop it before restarting |
| ngrok asks for an auth token | Configure `NGROK_AUTHTOKEN` or pass `--ngrok-authtoken` |
| The connector cannot connect | Check that the server is running and that the complete URL, including `/<TOKEN>/mcp`, was copied |
| MCP package import fails | The project requires `mcp>=1.10,<2`; remove the project venv and restart to recreate dependencies |
| Tools do not appear in the chat | Enable the connector in the current conversation and check client support for Remote MCP / Streamable HTTP |

## Project files

- [English documentation](README.md)
- [التوثيق باللغة العربية](README_AR.md)
- [Main Python implementation](mcp_agent.py)

---

<div align="center">

Made with care 🍯 · **Powerful access should be granted deliberately.**

**by ProfessorX**

</div>
