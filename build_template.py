"""Build a custom E2B template with Claude Agent SDK and Python pre-installed.

This eliminates runtime npm install delays on every sandbox creation.

Usage:
    uv run python build_template.py

Requires E2B_API_KEY in .env or environment.
"""

import os
import sys

from dotenv import load_dotenv
from e2b import Template

from sandstorm.sandbox import SDK_VERSION

load_dotenv()

TEMPLATE_ALIAS = "sandstorm"

template = (
    Template()
    .from_node_image("24")
    .apt_install(["curl", "git", "ripgrep", "python3", "python3-pip", "poppler-utils", "qpdf"])
    # Pre-install Python packages for document processing skills (pdf, docx, pptx)
    .run_cmd("pip3 install pypdf==6.7.2 pdfplumber==0.11.9 reportlab==4.4.10 markitdown==0.1.5", user="root")
    # Install Agent SDK locally so ESM imports resolve correctly
    .run_cmd(
        "mkdir -p /opt/agent-runner"
        " && cd /opt/agent-runner"
        " && npm init -y"
        f" && npm install @anthropic-ai/claude-agent-sdk@{SDK_VERSION}"
        " && chmod -R 777 /opt/agent-runner",
        user="root",
    )
    # Bake document skills (pdf, docx, pptx) into the template
    .copy(
        ".claude/skills",
        "/home/user/.claude/skills",
    )
)


def on_log(log):
    print(f"[{log.level}] {log.message}")


print(f"Building template '{TEMPLATE_ALIAS}'...")
print("This may take a few minutes on first build.\n")

api_key = os.environ.get("E2B_API_KEY")
if not api_key:
    print(
        "Error: E2B_API_KEY not set. Copy .env.example to .env and fill in your key.",
        file=sys.stderr,
    )
    sys.exit(1)

Template.build(
    template,
    alias=TEMPLATE_ALIAS,
    cpu_count=2,
    memory_mb=2048,
    on_build_logs=on_log,
    api_key=api_key,
)

print(f"\nTemplate '{TEMPLATE_ALIAS}' built successfully!")
print(f"Use it with: AsyncSandbox.create(template='{TEMPLATE_ALIAS}', ...)")
