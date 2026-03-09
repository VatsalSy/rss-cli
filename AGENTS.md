# rss-cli

CLI tool for reading RSS feeds and scrubbing the latest entries into normalized output.

## Structure

```text
rss-cli/
├── literature-rss-plan.md  # Initial product and integration notes
├── README.md               # Project overview
└── .gitignore              # Local/dev ignore rules
```

## Development

This repository is currently at the scaffolding stage.

Planned Python-oriented workflow:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
```

## Guidelines

- Treat Python as the primary implementation language unless the user redirects the project.
- Keep the CLI small, scriptable, and safe for cron or launchd execution.
- Preserve raw feed metadata when possible, but scrub outputs into a stable schema.
- Avoid network-heavy or stateful behavior in import-time code.
