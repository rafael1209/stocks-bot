"""Set (or change) the dashboard PIN. Run it yourself – the PIN never leaves this machine.

    python3 set_pin.py            # asks for the PIN twice, writes web.env
then restart the dashboard:  docker compose up -d web

Changing the PIN also logs out every browser (a new session key is generated).
"""
import getpass
import secrets
import sys
from pathlib import Path

from auth import hash_pin

ENV = Path(__file__).resolve().parent / "web.env"

pin = getpass.getpass("New PIN (at least 6 digits): ").strip()
if not (pin.isdigit() and len(pin) >= 6):
    sys.exit("The PIN must be at least 6 digits.")
if getpass.getpass("Repeat the PIN: ").strip() != pin:
    sys.exit("The two PINs do not match – nothing changed.")

ENV.write_text(f"DASHBOARD_PIN_HASH={hash_pin(pin)}\nDASHBOARD_SECRET={secrets.token_hex(32)}\n")
ENV.chmod(0o600)
print(f"PIN saved (hash only) to {ENV}. Now run:  docker compose up -d web")
