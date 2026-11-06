<p align="center">
  <img src="68747470733a2f2f7374617469632e726173746174696e672e636f6d2f696d616765732f70676134646563727970742e706e67.png">
</p>

# pga4decrypt

Recover the plain-text credentials of PostgreSQL servers stored in a pgAdmin 4
configuration database.

This is a fork of [rastating/pga4decrypt](https://github.com/rastating/pga4decrypt)
(the upstream project, which targets pgAdmin 4 databases from around 2019).
This fork keeps the same purpose but adds support for modern pgAdmin releases,
current storage formats, Docker deployments and an interactive interface.

* This fork: <https://github.com/ajafov98/pga4decrypt>
* Upstream: <https://github.com/rastating/pga4decrypt>

## Disclaimer

This tool is intended for **personal use** — recovering credentials from your
own pgAdmin installation — and for **authorised security research, forensics
and penetration testing**.

Do **not** use it against databases, containers or systems that you do not own
or do not have explicit written permission to test. Accessing, decrypting or
disclosing credentials without authorisation may be illegal in your
jurisdiction and may violate the terms of service of the affected systems.

You are solely responsible for how you use this software and for protecting
any recovered plaintext credentials. The authors and contributors accept no
liability for misuse, damage or legal consequences. The software is provided
"as is", without warranty of any kind, under the GNU GPL v3 (see
`LICENSE.txt`).

## What is new in this fork

- **Modern pgAdmin storage format.** pgAdmin 7.0+ stores encrypted values as
  `hex(base64(iv + ciphertext))`; older versions used plain base64. Both are
  decoded automatically.
- **Modern key sources.** In addition to the legacy key stored in
  `user.password`, the tool can use:
  - the desktop master key from the OS keyring,
  - a master password,
  - a pgAdmin login password (server mode / Docker),
  - a key supplied with `--key` or `--key-file`.
- **Key validation.** When pgAdmin's `masterpass_check` is present, the key is
  verified before any password is shown, so you get an error instead of
  garbage output.
- **Automatic database discovery.** Finds `pgadmin4.db` in the usual desktop
  and server locations, or takes an explicit path.
- **Docker and Docker Compose support.** Copies the database out of a
  container using SQLite's online backup, so a running pgAdmin is not
  corrupted. Compose services are resolved through Docker labels, so no
  compose file or project directory is needed.
- **Interactive wizard.** `-i` walks through database selection, key source,
  results and saving.
- **Shared servers.** Reads pgAdmin's `sharedserver` table as well as
  `server`.
- **Safer output.** `-o` writes files with mode `600`; the configuration
  database is opened read-only.
- **`uv` support.** Dependencies are declared inline (PEP 723), so
  `uv run ./pga4decrypt ...` works without a manual install.
- **New tests.** The suite covers legacy and modern storage, key handling,
  diagnostics, the interactive wizard and Docker command construction.

## How it works

pgAdmin encrypts saved server passwords with AES-256-CFB8. The key depends on
how pgAdmin runs:

| pgAdmin setup | Encryption key |
| --- | --- |
| Desktop 7.2+ (default) | Random key stored in the OS keyring (`pgAdmin4` / `pgadmin4-master-password`) |
| Desktop, master password enabled | The master password you chose |
| Desktop, master password and OS secret storage disabled | `user.password` from the config database (legacy behaviour) |
| Server mode, internal or LDAP auth | The password you type when logging into pgAdmin |
| Server mode, OAuth2/Kerberos/webserver auth | Master password, or the output of `MASTER_PASSWORD_HOOK` |

If no key is available anywhere, the database cannot be decrypted. That is a
deliberate pgAdmin security feature, not a limitation of this tool.

## Requirements

- Python 3.9 or newer
- `cryptography` >= 43
- `keyring` >= 24 (optional but needed for desktop keyring access)
- Docker CLI (optional, only for `--docker` / `--compose-service`)

## Installation with pip and a virtual environment

Linux / macOS:

```
git clone https://github.com/ajafov98/pga4decrypt.git
cd pga4decrypt

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

./pga4decrypt --help
```

Windows (PowerShell / cmd):

```
git clone https://github.com/ajafov98/pga4decrypt.git
cd pga4decrypt

py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python pga4decrypt --help
```

To leave the environment later:

```
deactivate
```

## Installation and use with uv

No manual installation is needed. The script declares its dependencies inline
(PEP 723), so `uv` creates an isolated environment on first use:

```
git clone https://github.com/ajafov98/pga4decrypt.git
cd pga4decrypt

uv run ./pga4decrypt --help
uv run ./pga4decrypt --compose-service pgadmin --login-password
uv run ./pga4decrypt /path/to/pgadmin4.db -o creds.json -f json
```

The first run downloads `cryptography` and `keyring`; later runs reuse uv's
cache. You can also force script mode explicitly with
`uv run --no-project ./pga4decrypt ...`.

## Usage

```
./pga4decrypt [options] [path]
```

`path` (or `--db PATH`) is the pgAdmin configuration database. If omitted, the
tool searches:

- `SQLITE_PATH` and `PGADMIN_SQLITE_PATH` environment variables,
- `./pgadmin4.db`,
- `~/.pgadmin/pgadmin4.db`,
- `~/.pgadmin4/pgadmin4.db`,
- `/var/lib/pgadmin/pgadmin4.db`,
- `%APPDATA%\pgAdmin\pgadmin4.db` on Windows,
- `~/Library/Application Support/pgAdmin/pgadmin4.db` on macOS.

Keys are tried in this order:

1. `--key` / `--key-file`
2. the desktop master key from the OS keyring
3. the legacy key in `user.password`
4. a prompted master password or login password

`--master-password` and `--login-password` force the corresponding prompt.

### Common examples

Legacy database (key stored in `user.password`):

```
./pga4decrypt test/pgadmin4.db
```

Default desktop install (key in the OS keyring):

```
./pga4decrypt
```

Master password enabled:

```
./pga4decrypt --master-password
```

Server mode / Docker with internal authentication:

```
./pga4decrypt --login-password
```

Explicit key or key file:

```
./pga4decrypt --key 'the-key'
./pga4decrypt --key-file ~/.config/pga4decrypt.key
```

Save the output as JSON with mode `600`:

```
./pga4decrypt -o credentials.json -f json
```

Inspect a database without decrypting anything:

```
./pga4decrypt --inspect
```

## All options

| Option | Description |
| --- | --- |
| `path` | Positional path to `pgadmin4.db`. Optional; auto-detected when omitted. |
| `--db PATH` | Same as the positional path. |
| `--key KEY` | Use this encryption key directly. Note that it can appear in shell history and process listings. |
| `--key-file PATH` | Read the encryption key from a file (whitespace is stripped). |
| `--master-password` | Prompt for the pgAdmin master password. |
| `--login-password` | Prompt for the pgAdmin login password (server mode / Docker). |
| `--inspect` | Print database metadata (version, users, master-password check, server and saved-password counts, storage format) and exit. |
| `--docker CONTAINER` | Copy the database from a Docker container (name or ID). |
| `--compose-service SERVICE` | Copy the database from a Docker Compose service, resolved by Docker labels. |
| `--compose-project PROJECT` | Disambiguate `--compose-service` when the same service name exists in several compose projects. |
| `--compose-file PATH` | Optional compose file used when resolving the service (Docker labels are used otherwise). |
| `--docker-path PATH` | Path to the database inside the container. Default: `/var/lib/pgadmin/pgadmin4.db`. |
| `-i`, `--interactive` | Start the interactive wizard. |
| `-f {text,json}` | Output format used with `-o`. Default: `text`. |
| `-o PATH` | Write the recovered credentials to a file (created with mode `600`). |
| `-h`, `--help` | Show help and exit. |

## Interactive mode

```
./pga4decrypt -i
```

The wizard:

1. lists auto-detected databases and offers to enter a path or copy from a
   running Docker container,
2. offers key sources: automatic, OS keyring, master password, login password,
   pasted key, or key file,
3. shows the recovered credentials,
4. optionally saves them as text or JSON,
5. optionally decrypts another database.

## Docker and Docker Compose

A containerised pgAdmin runs in **server mode**, so saved passwords are
encrypted with your pgAdmin **login password** — the email/username is not
part of the key. (OAuth2/Kerberos/webserver deployments use the master
password instead.)

Use a mounted volume directly:

```
./pga4decrypt ./pgadmin-data/pgadmin4.db --login-password
```

Or let the tool copy the database out of a running container:

```
./pga4decrypt --docker pgadmin4_container --login-password
./pga4decrypt --compose-service pgadmin --login-password
```

`--compose-service` resolves the service to its container through the
`com.docker.compose.service` label, so it works from any directory and does
not need the compose file. If the same service name exists in multiple
compose projects:

```
./pga4decrypt --compose-service pgadmin --compose-project myproject \
    --login-password
```

Defaults and behaviour:

- The database path inside the container is `/var/lib/pgadmin/pgadmin4.db`;
  override it with `--docker-path`.
- The tool uses SQLite's online backup inside the container, which is safe
  while pgAdmin is running, then copies the backup out. If that fails (for
  example a stopped container without `python3`), it falls back to a direct
  `docker cp`.
- The temporary copy is created with mode `600` and removed when the tool
  exits.

## Fixing the key in pgAdmin

If decryption fails, first check what is actually in the database:

```
./pga4decrypt --compose-service pgadmin --inspect
```

Example output:

```
Database diagnostics:
  ConfigDB version: 52
  Users: 1 (1 with a stored password hash) [you@example.com]
  Master password check set: yes
  Servers: 1 (0 with saved passwords)
```

Interpretation:

- **`0 with saved passwords`** — the password was never stored. In pgAdmin,
  open the server's **Properties → Connection**, enter the password and tick
  **Save password**. Save, connect once, then run the tool again.
- **`Master password check set: yes`** — the master password (or, in server
  mode with internal auth, the login password) is required. Try
  `--master-password` or `--login-password`.
- **Saved passwords exist but the key is rejected** — the password must be
  the one that currently logs into the pgAdmin web UI.
  `PGADMIN_DEFAULT_PASSWORD` is only used when the configuration database is
  first created; an existing container or volume keeps its old password.
- **No volume in your compose file** — pgAdmin stores everything in the
  container's writable layer, so `docker compose down`/recreation loses saved
  servers. Mount a volume:

```yaml
services:
  pgadmin:
    image: dpage/pgadmin4:latest
    environment:
      PGADMIN_DEFAULT_EMAIL: you@example.com
      PGADMIN_DEFAULT_PASSWORD: change-me
    volumes:
      - pgadmin-data:/var/lib/pgadmin

volumes:
  pgadmin-data:
```

## Security notes

- The output contains **plaintext credentials**. Treat it as sensitive.
- `-o` creates the file with mode `600`, but the terminal output is still
  visible to anyone who can see your screen.
- Prefer `--key-file` or the interactive prompt over `--key`, which can be
  captured in shell history or process listings.
- The configuration database is opened read-only. Docker copies are temporary
  and deleted on exit.
- Only decrypt databases you are authorised to access.

## Limitations

- SQLite configuration databases only; a PostgreSQL-hosted pgAdmin config
  database (`CONFIG_DATABASE_URI`) is not read directly.
- Server passwords are recovered; SSH tunnel passwords and other secrets are
  not exported.
- A database without its key (no keyring entry, no master/login password, and
  no legacy key) cannot be decrypted. This is intentional in modern pgAdmin.
- `test/pgadmin4.db` is a public upstream **test fixture** containing dummy
  accounts, dummy hosts and test keys. Never use it as a real pgAdmin
  configuration database.

## Development

Run the tests after installing the dependencies:

```
python -m unittest -b
```

or:

```
make spec
```

## Credits and license

- Original project: [rastating/pga4decrypt](https://github.com/rastating/pga4decrypt)
- This fork: [ajafov98/pga4decrypt](https://github.com/ajafov98/pga4decrypt)
- The AES-CFB8 implementation is derived from pgAdmin 4's
  `pgadmin/utils/crypto.py`.
- Licensed under the GNU General Public License v3. See `LICENSE.txt`.
