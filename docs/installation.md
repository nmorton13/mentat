# Installation

Mentat 0.8 supports a clone-and-run source workflow. Run it from the repository
checkout so the project-local configuration, database, runtime settings, and
Markdown paths stay together. Portable wheel installation is not yet supported.
Normal setup installs runtime dependencies only; test tooling remains in an
explicit contributor dependency group.

## Requirements

- Git
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Python 3.12, which `uv` can install and manage for you
- An LLM route: OpenRouter, native Ollama, or another OpenAI-compatible endpoint

OpenRouter requires an API key. Ollama and other local routes can be used
without a hosted-provider account. OpenAI or xAI credentials are only needed
when you explicitly configure those providers or their realtime voice support.

## Install Mentat

Install `uv` using its official installer or your platform package manager. For
example:

```bash
# macOS or Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then clone Mentat and create its Python 3.12 environment:

```bash
git clone https://github.com/nmorton13/mentat.git
cd mentat
uv python install 3.12
uv sync --python 3.12
```

To install the exact 0.8.0 release rather than the moving `main` branch:

```bash
git clone --branch v0.8.0 --depth 1 https://github.com/nmorton13/mentat.git
cd mentat
uv python install 3.12
uv sync --python 3.12
```

## Configure And Run

Run the guided configuration flow:

```bash
uv run mentat config init
```

It creates or safely updates the checkout's ignored `.env` file, configures a
hosted or local route, and activates the selected model. Inspect the effective
configuration and test the route with:

```bash
uv run mentat config show
uv run mentat config doctor
```

`config doctor` may contact the configured provider or local model server. It
masks sensitive values in its output.

Start Mentat with:

```bash
uv run mentat
```

For advanced provider, helper-route, voice, export, and storage settings, see
[Configuration](configuration.md) and the documented placeholders in
[`.env.example`](../.env.example). Never commit your real `.env` file.

## Optional Voice Support

Voice uses PyAudio, which binds to the native PortAudio library. Install the
platform prerequisite before syncing the `voice` extra.

### macOS

```bash
brew install portaudio
uv sync --python 3.12 --extra voice
```

Building PyAudio on macOS may also require the Xcode Command Line Tools.

### Ubuntu Or Debian

```bash
sudo apt-get update
sudo apt-get install --yes portaudio19-dev python3-all-dev
uv sync --python 3.12 --extra voice
```

### Windows

PyAudio publishes Python 3.12 wheels for Windows that include PortAudio:

```powershell
uv sync --python 3.12 --extra voice
```

After installation, set the realtime provider credentials and voice settings
through `mentat config init` or [Configuration](configuration.md), then start
Mentat and use `/voice`.

## Verify The Installation

```bash
uv run python --version
uv run mentat --version
uv run mentat config doctor
```

The first command should report Python 3.12.x, and the second should report
Mentat 0.8.0. The doctor result depends on the provider or local server you
selected.

## Troubleshooting

### Wrong Python Version

Recreate the project environment explicitly with Python 3.12:

```bash
uv python install 3.12
uv sync --python 3.12 --reinstall
```

### PyAudio Or PortAudio Build Failure

Install the native dependency for macOS or Ubuntu/Debian above, then rerun:

```bash
uv sync --python 3.12 --extra voice --reinstall
```

### Provider Or API-Key Failure

Rerun the guided setup and doctor rather than placing credentials in shell
commands or issue reports:

```bash
uv run mentat config init
uv run mentat config doctor
```

When reporting a problem, include the masked doctor output and the error message,
but never include an API key, `.env` file, database, or personal memory.

## Next Steps

1. Start with [Capture This, Skip That](examples.md#capture-this-skip-that).
2. Review the [Command Reference](commands.md).
3. Use [Configuration](configuration.md) for advanced routing.
4. Read [Temporal Search](temporal-search.md) for the evidence boundary on time-based answers.
