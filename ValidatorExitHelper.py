#!/usr/bin/env python3
import os
import time
import yaml
import subprocess
from getpass import getpass

# กำหนดชื่อไฟล์ YAML และตำแหน่ง testnet_dir
FILE_PATH = "/home/USER/.lighthouse/custom/validators/validator_definitions.yml"
TESTNET_DIR = "/home/USER/node/config/"  # แทนที่ด้วยพาธที่ต้องการ https://github.com/jibchain-net/node

# กำหนด path ของ Lighthouse
LIGHTHOUSE_PATH = "/usr/local/bin/lighthouse"  # หรือกำหนด path ที่ต้องการ

# ฟังก์ชันตรวจสอบว่าไฟล์ YAML มีอยู่หรือไม่
def check_file_exists(file_path):
    if not os.path.exists(file_path):
        print(f"Error: The file '{file_path}' does not exist.")
        return False
    return True

# ฟังก์ชันอ่านไฟล์ YAML
def load_validators(file_path):
    with open(file_path, "r") as file:
        return yaml.safe_load(file)

# ฟังก์ชันถามยืนยันการดำเนินการ
def confirm_action(message):
    response = input(f"{message} (yes/no): ").strip().lower()
    return response == "yes"

# ฟังก์ชันบันทึก log
def log_exited_validators(exited_validators):
    with open("exited_validators_log.txt", "w") as file:
        for public_key, url in exited_validators:
            file.write(f"Public Key: {public_key}\n")
            file.write(f"URL: {url}\n")
            file.write("\n")

# ฟังก์ชันจัดการการร้องขอรหัสผ่านสำหรับ sudo
def request_sudo_password():
    # ให้ผู้ใช้กรอกรหัสผ่าน sudo
    password = getpass(prompt="Enter your sudo password: ")
    return password

# ฟังก์ชัน exit validator
def exit_validators(validators, num_to_exit):
    exited_validators = []
    counter = 0

    for validator in validators:
        if validator.get("enabled", False):
            public_key = validator.get("voting_public_key")
            keystore_path = validator.get("voting_keystore_path")
            if not keystore_path:
                continue

            print(f"Exiting validator: {public_key}")
            
            # ขอรหัสผ่านจากผู้ใช้
            sudo_password = request_sudo_password()

            # สร้างคำสั่ง sudo
            command = [
                "echo", sudo_password, "|", "sudo", "-S", LIGHTHOUSE_PATH, "account", "validator", "exit",
                "--keystore", keystore_path,
                "--beacon-node", "https://metrabyte-cl.jibchain.net/",
                f"--testnet-dir={TESTNET_DIR}"
            ]
            
            try:
                # รันคำสั่ง
                subprocess.run(command, check=True, shell=True)
                url = f"https://dora.jibchain.net/validator/{public_key}"
                exited_validators.append((public_key, url))
                print(f"Success: {public_key}")
                time.sleep(1)
                counter += 1
            except subprocess.CalledProcessError as e:
                print(f"Error exiting validator {public_key}: {e}")
            
            # ตรวจสอบจำนวนที่ออกแล้ว
            if num_to_exit != "all" and counter >= int(num_to_exit):
                break

    # บันทึก log
    log_exited_validators(exited_validators)
    print("\n*** Exit process completed ***")
    print("Please review the exited validators in 'exited_validators_log.txt'.")
    print("Do not close your Lighthouse validator until all funds are returned to your wallet (1-2 days).")

# ฟังก์ชันหลัก
def main():
    print("ValidatorExitHelper - Safely Exit Your Validators")
    print("-------------------------------------------------\n")

    print("Donate to support further development:")
    print("BTC (Native SegWit): bc1qlpy59lmup27ylrffe7kg2sp9wj0zfka8q8j9dz")
    print("ERC20/BEP20/POL/JIBChain: 0xba2eab518482c75789a262ce3e4ded6941c36370\n")

    if not check_file_exists(FILE_PATH):
        return

    validators = load_validators(FILE_PATH)
    enabled_validators = [v for v in validators if v.get("enabled", False)]
    print(f"Total enabled validators: {len(enabled_validators)}\n")

    num_to_exit = input("Enter the number of validators to exit or type 'all': ").strip()
    if num_to_exit != "all" and not num_to_exit.isdigit():
        print("Invalid input. Please enter a valid number or 'all'.")
        return

    if not confirm_action(f"Are you sure you want to exit {num_to_exit} validators? This action cannot be undone."):
        print("Operation canceled.")
        return

    exit_validators(enabled_validators, num_to_exit)

if __name__ == "__main__":
    main()
