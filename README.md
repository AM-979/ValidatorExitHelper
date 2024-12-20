
# ValidatorExitHelper

ValidatorExitHelper is a program that facilitates the **exit** of Ethereum Validators from the blockchain network. It supports selecting the number of Validators to exit or choosing all, ensuring a safe exit process with confirmation before execution of irreversible commands. The program also logs important information such as Public Key and URL for future verification.

---

## Purpose
1. Facilitate the safe exit of multiple Validators at once.
2. Reduce human error by confirming actions before executing irreversible commands.
3. Log essential information like Public Key and URL for verifying Validator status after exiting.

---

## Features
- Only supports exiting Validators with `enabled: true` status.
- Allows selecting a specific number of Validators to exit, or exit all Validators.
- Verifies the success of the `lighthouse account validator exit` command and retries if the command fails.
- Logs Public Key and URL to `exited_validators_log.txt`.
- Displays important warnings during the process.

---

## Installation

### 1. Install Dependencies
This program requires Python 3.7 or later and the `PyYAML` library:
```bash
sudo apt update
sudo apt install python3 python3-pip -y
pip install pyyaml
```

### 2. Download the Program Files
To download the program files, run the following command to clone the repository:
```bash
git clone https://github.com/AM-979/ValidatorExitHelper.git && cd ValidatorExitHelper
```
---

## Configuration

Before using **ValidatorExitHelper**, you will need to configure the following settings in the `ValidatorExitHelper.py` script:

1. **File Path for YAML Configuration**
   - The script expects a YAML configuration file containing the list of validators you want to exit. 
   - You need to define the correct path to this YAML file.
   
   To configure it, modify the line in `ValidatorExitHelper.py`:
   ```python
   file_path = "validator_definitions.yml"
   ```

   Replace `"validator_definitions.yml"` with the actual path to your YAML configuration file.
   EX.PATH : /home/USER/.lighthouse/custom/validators/

3. **Set the Testnet Directory**
   - The script also requires a `testnet_dir` for the configuration files.
   
   Modify the line in `ValidatorExitHelper.py`:
   ```python
   TESTNET_DIR = "/path/to/your/testnet/config"
   ```

   Replace `"/path/to/your/testnet/config"` with the actual path to your testnet configuration directory.
   Download from here : https://github.com/jibchain-net/node

Once you have updated these settings, you can proceed to use the script.

---

## Usage

### 1. Prepare `validator_definitions.yml` File
The `validator_definitions.yml` file must be in the same directory as the program and have the following structure:
```yaml
- enabled: true
  voting_public_key: 0x...
  voting_keystore_path: /path/to/keystore.json
  voting_keystore_password: 'password'
```

### 2. Run the Program
To start the program, run the following command:
```bash
python3 ValidatorExitHelper.py
```

### 3. Choose Number of Validators
- Enter the number of Validators to exit.
- Confirm the action by typing **yes** or **no**.

### 4. Check the Log File
After completion, the Public Key and URL of the exited Validators will be logged in `exited_validators_log.txt`:
```plaintext
Public Key: 0x123...
URL: https://dora.jibchain.net/validator/0x123...
```

---

## Caution
1. The `lighthouse account validator exit` command **cannot be undone**.
2. Keep your Lighthouse Validator running until all coins have been returned to your Wallet.

---

## Donate 💖
If you find this program helpful and would like to support it, donations are appreciated via:

- **BTC Native SegWit**: `bc1qlpy59lmup27ylrffe7kg2sp9wj0zfka8q8j9dz`
- **ERC20/BEP20/JIBChain**: `0xba2eab518482c75789a262ce3e4ded6941c36370`

---

**Developer**  
AM979 | [xpool.pw](https://xpool.pw)
