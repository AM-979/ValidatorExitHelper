# ValidatorExitHelper

ValidatorExitHelper submits voluntary exits for multiple Lighthouse validators while adding preflight validation, an explicit irreversible-operation confirmation, shell-free process execution, and an append-only audit log.

The default endpoint and explorer target **Jibchain**, but the Lighthouse executable, validator definitions, custom-network directory, beacon node, explorer, and log path are configurable.

> [!CAUTION]
> A validator voluntary exit is irreversible. Test the exact configuration with `--dry-run` first, verify every public key shown before confirmation, and keep each validator online until its exit epoch.

## Safety properties

- Processes only entries with `enabled: true` and `type: local_keystore`.
- Validates YAML structure, public keys, duplicate keys, keystore files, password files, Lighthouse, and the custom-network directory before submitting an exit.
- Rejects an exit count of `0`, negative/invalid input, and counts larger than the available validator set.
- Shows every selected public key, keystore path, and explorer URL before execution.
- Requires the exact phrase `EXIT N VALIDATOR(S)` before the irreversible operation.
- Calls Lighthouse with an argument list and `shell=False`; it never constructs a shell pipeline or places passwords in command arguments.
- Uses Lighthouse without `--no-wait`, so an exit is recorded as `confirmed` only after Lighthouse observes an exiting/exited validator state.
- Appends mode-`0600` JSON Lines records instead of overwriting previous history.
- Supports a non-destructive `--dry-run` mode.

The script intentionally does **not** retry failed exits automatically. Before retrying, check the validator explorer and audit log to avoid submitting an operation whose prior state is uncertain.

## Requirements

- Linux or another operating system supported by Lighthouse
- Python 3.8 or later
- Lighthouse installed and executable
- A synchronized beacon-node HTTP API for the same network as the supplied custom-network configuration
- Local EIP-2335 voting keystores referenced by `validator_definitions.yml`

## Installation

```bash
git clone https://github.com/AM-979/ValidatorExitHelper.git
cd ValidatorExitHelper

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Lighthouse validator definitions

The script reads Lighthouse's existing `validator_definitions.yml`. A current local-keystore entry normally resembles:

```yaml
---
- enabled: true
  voting_public_key: "0x87a580d31d7bc69069b55f5a01995a610dd391a26dc9e36e81057a17211983a79266800ab8531f21f1083d7d84085007"
  type: local_keystore
  voting_keystore_path: /home/user/.lighthouse/custom/validators/0x87a5.../voting-keystore.json
  voting_keystore_password_path: /home/user/.lighthouse/custom/secrets/0x87a5...
```

`voting_keystore_password_path` is preferred. If only `voting_keystore_password` is present, ValidatorExitHelper copies it to a temporary mode-`0600` file, passes that file to Lighthouse, and deletes it immediately afterward. If neither password field is present, Lighthouse inherits the terminal and prompts for the keystore password.

Enabled `web3signer` entries are skipped because this command requires access to the local voting keystore.

## Default configuration

| Setting | Default |
|---|---|
| Validator definitions | `~/.lighthouse/custom/validators/validator_definitions.yml` |
| Jibchain custom-network directory | `~/node/config` |
| Lighthouse executable | `lighthouse` from `PATH` |
| Beacon node | `https://metrabyte-cl.jibchain.net/` |
| Explorer | `https://dora.jibchain.net/validator/` |
| Audit log | `./exited_validators_log.jsonl` |

Every setting can be supplied as a command-line option or environment variable.

## Recommended workflow

### 1. Validate without exiting

```bash
python3 ValidatorExitHelper.py --count all --dry-run
```

Review:

- the number of validated validators;
- every selected public key;
- every keystore path;
- the Lighthouse commands displayed by the dry run;
- warnings about skipped validators or inline passwords.

### 2. Exit a specific number

```bash
python3 ValidatorExitHelper.py --count 2
```

The script displays the exact validator list and requires:

```text
EXIT 2 VALIDATORS
```

For one validator, the required phrase is `EXIT 1 VALIDATOR`.

### 3. Exit all validated local validators

```bash
python3 ValidatorExitHelper.py --count all
```

When `--count` is omitted, the script prompts for a positive integer or `all`.

## Custom paths and endpoint

```bash
python3 ValidatorExitHelper.py \
  --validator-definitions /home/jbc/.lighthouse/custom/validators/validator_definitions.yml \
  --testnet-dir /home/jbc/node/config \
  --lighthouse /usr/local/bin/lighthouse \
  --beacon-node https://metrabyte-cl.jibchain.net/ \
  --count 2
```

Equivalent environment variables are:

```bash
export VALIDATOR_DEFINITIONS_PATH=/home/jbc/.lighthouse/custom/validators/validator_definitions.yml
export TESTNET_DIR=/home/jbc/node/config
export LIGHTHOUSE_PATH=/usr/local/bin/lighthouse
export BEACON_NODE=https://metrabyte-cl.jibchain.net/
export EXPLORER_BASE=https://dora.jibchain.net/validator/
export EXIT_LOG_FILE=/secure/path/exited_validators_log.jsonl
```

## Options

```text
--validator-definitions PATH  Lighthouse validator_definitions.yml
--testnet-dir PATH            Custom-network configuration directory
--lighthouse PATH             Lighthouse executable name or path
--beacon-node URL              Beacon Node HTTP API
--explorer-base URL            Validator explorer base URL
--log-file PATH                Append-only JSON Lines audit log
--count N|all                  Number of validators to exit
--dry-run                      Validate and display commands only
--stop-on-error                Stop after the first Lighthouse failure
--delay SECONDS                Delay between exits; default 1 second
```

## Audit log

Each processed validator produces one JSON object per line:

```json
{"beacon_node":"https://metrabyte-cl.jibchain.net/","explorer_url":"https://dora.jibchain.net/validator/0x...","keystore_path":"/home/user/.../voting-keystore.json","message":"Lighthouse confirmed the voluntary exit state.","public_key":"0x...","status":"confirmed","timestamp_utc":"2026-07-17T05:00:00+00:00"}
```

Possible statuses:

- `confirmed`: Lighthouse returned success after observing an exiting/exited state.
- `failed`: Lighthouse or process execution failed.
- `dry-run`: no voluntary exit was submitted.
- `interrupted`: the user interrupted processing of that validator.

The log is append-only and forced to mode `0600`. It contains keystore paths and validator public keys, so keep it private.

## Withdrawal timing

Do not assume funds will arrive within a fixed one- or two-day window. Timing depends on the network's exit queue, withdrawability delay, withdrawal credentials, and withdrawal sweep. The validator must remain online and continue performing duties until its exit epoch to avoid penalties.

An exit does not by itself repair withdrawal credentials. Verify that the configured withdrawal address and credential type are correct before exiting.

## Tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q ValidatorExitHelper.py tests
```

GitHub Actions runs the same checks on supported Python versions.

## Donations

- **BTC Native SegWit:** `bc1qlpy59lmup27ylrffe7kg2sp9wj0zfka8q8j9dz`
- **ERC20 / BEP20 / POL / Jibchain:** `0xba2eab518482c75789a262ce3e4ded6941c36370`

## Developer

AM979 — [xpool.pw](https://xpool.pw)
