# Client deployment (site install)

Deploy the hpcGPT OpenCode CLI on an HPC cluster so users load it via Environment Modules instead of installing into their home directory.

This directory contains:

| File | Purpose |
|------|---------|
| `installer.sh` | Site OpenCode installer (fork of the [official installer](https://opencode.ai/install)) with `--install-dir` and `--no-modify-path` |
| `module.lua` | Lmod/Environment Modules template that sets `PATH`, `OPENCODE_CONFIG`, and `NCSA_LLM_URL` |
| `opencode.jsonc` | Site-Config file for opencode.

### Install the OpenCode binary

Delta uses the `/sw/external/` path for system software so in our example code that is where we are installing. 

Run the installer as a user with permission to write the target directory. Use `--no-modify-path` so user shell configs are not modified on the admin account.

```bash
bash installer.sh \
  --install-dir /sw/external/opencode/bin \
  --no-modify-path
```

Verify:

```bash
/sw/external/opencode/bin/opencode --version
```

### Deploy site configuration

Copy and customize the OpenCode config:

```bash
cp ../opencode.jsonc /sw/external/opencode/delta-opencode.json
```

Edit that file for your center: provider models, MCP server URLs, prompts, and permissions.

### Install the modulefile

Copy `module.lua` into your modules tree, for example:

```bash
mkdir -p /sw/external/modulefiles/opencode
cp module.lua /sw/external/modulefiles/opencode/1.15.13.lua
```

Update the template for your site:

- `root` — software root (e.g. `/sw/external/opencode`)
- `version` — module version string; should match the OpenCode release you installed
- `OPENCODE_CONFIG` — path to your site config JSON/JSONC file
- `NCSA_LLM_URL` — your hosted model endpoint 

Reload the module index if your site requires it (`module use`, `module spider`, etc.).

## End user usage

After the site admin completes the steps above:

```bash
module load opencode/1.15.13
opencode
```

## Installer options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show usage |
| `-v`, `--version <ver>` | Install a specific release (e.g. `1.15.13` or `v1.15.13`) |
| `-d`, `--install-dir <path>` | Directory for the `opencode` binary (default: `~/.opencode/bin`) |
| `-b`, `--binary <path>` | Install from a local binary; skip download |
| `--no-modify-path` | Do not append install dir to shell rc files |

Environment variable `OPENCODE_INSTALL_DIR` is equivalent to `--install-dir` (the flag wins if both are set).

## Upgrading

1. Run `installer.sh` with the new `--version` (or latest if omitted).
2. Update the modulefile version string and filename if you version modules per release.
3. Re-test `opencode` and your `OPENCODE_CONFIG` against the new CLI.

## Per-user install

For development users can install the opencode client themselves in there home directory by following the standard [opencode install instructions](http://opencode.ai) and pointing to there own config with `export OPENCODE_CONFIG=path/to/config`
