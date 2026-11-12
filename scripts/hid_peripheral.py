#!/usr/bin/env python3
"""Advertise this laptop as a BLE keyboard so an iPhone will bond with it.

Run with:  sudo python3 scripts/hid_peripheral.py

Why: an iPhone refuses to bond with a generic Linux host, so its rotating BLE
address can never be resolved. But it *does* bond with HID keyboards, and the
bonding exchange hands over the phone's Identity Resolving Key (IRK). BlueZ then
stores that IRK and resolves every later rotating address to the phone's stable
identity — which is exactly what the phone-proximity factor needs.

Nothing here functions as a keyboard; we only need the bond. If iOS later drops
the "broken" keyboard, re-run and re-pair, and the IRK it re-issues is the same.

Requires the system dbus-python (python3-dbus) and root, because registering
GATT applications and advertisements is a privileged BlueZ operation.
"""

import struct
import sys

import dbus
import dbus.exceptions
import dbus.service
from gi.repository import GLib

BUS = dbus.SystemBus()
BLUEZ = "org.bluez"
ADAPTER_PATH = "/org/bluez/hci0"
BASE = "/org/lockdown"

# Appearance: Keyboard (Bluetooth SIG assigned number)
APPEARANCE_KEYBOARD = 0x03C1

# Standard 8-key-byte keyboard report descriptor
REPORT_MAP = bytes([
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x06,  # Usage (Keyboard)
    0xA1, 0x01,  # Collection (Application)
    0x85, 0x01,  #   Report ID (1)
    0x05, 0x07,  #   Usage Page (Key Codes)
    0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01,
    0x75, 0x01, 0x95, 0x08, 0x81, 0x02,  #   modifier keys
    0x95, 0x01, 0x75, 0x08, 0x81, 0x01,  #   reserved byte
    0x95, 0x05, 0x75, 0x01, 0x05, 0x08,
    0x19, 0x01, 0x29, 0x05, 0x91, 0x02,  #   LED output
    0x95, 0x01, 0x75, 0x03, 0x91, 0x01,
    0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65,
    0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00,  #   key array
    0xC0,
])

LOCAL_NAME = "Lockdown Key"


class InvalidArgs(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class NotSupported(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


class NotPermitted(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotPermitted"


class Advertisement(dbus.service.Object):
    """org.bluez.LEAdvertisement1"""

    PATH = f"{BASE}/advert0"

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return {self.PATH: self._props()}

    def _props(self):
        return {
            "org.bluez.LEAdvertisement1": {
                "Type": dbus.String("peripheral"),
                "ServiceUUIDs": dbus.Array(["180f", "1812"], signature="s"),
                "LocalName": dbus.String(LOCAL_NAME),
                "Appearance": dbus.UInt16(APPEARANCE_KEYBOARD),
                "Includes": dbus.Array(["tx-power"], signature="s"),
            }
        }

    @dbus.service.method("org.bluez.LEAdvertisement1", in_signature="", out_signature="")
    def Release(self):
        print("[advert] released")


class Application(dbus.service.Object):
    """org.bluez.GattApplication1 — aggregate of all services/characteristics."""

    PATH = f"{BASE}/app0"

    def __init__(self, objects):
        self._objects = objects
        super().__init__(BUS, self.PATH)

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return self._objects


class Characteristic(dbus.service.Object):
    def __init__(self, path, uuid, service_path, value, flags=("read",)):
        self._uuid = uuid
        self._service = dbus.ObjectPath(service_path)
        self._value = value
        self._flags = list(flags)
        super().__init__(BUS, path)

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="a{sv}",
                         out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array(self._value, signature="y")

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="aya{sv}")
    def WriteValue(self, value, options):
        pass

    def props(self):
        d = {
            "org.bluez.GattCharacteristic1": {
                "UUID": dbus.String(self._uuid),
                "Service": self._service,
                "Flags": dbus.Array(self._flags, signature="s"),
            }
        }
        if self._value is not None and "read" in self._flags:
            d["org.bluez.GattCharacteristic1"]["Value"] = dbus.Array(self._value, signature="y")
        return d


class Descriptor(dbus.service.Object):
    def __init__(self, path, uuid, char_path, value, flags=("read",)):
        self._uuid = uuid
        self._char = dbus.ObjectPath(char_path)
        self._value = value
        self._flags = list(flags)
        super().__init__(BUS, path)

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array(self._value, signature="y")

    def props(self):
        return {
            "org.bluez.GattDescriptor1": {
                "UUID": dbus.String(self._uuid),
                "Characteristic": self._char,
                "Value": dbus.Array(self._value, signature="y"),
                "Flags": dbus.Array(self._flags, signature="s"),
            }
        }


class Agent(dbus.service.Object):
    """org.bluez.Agent1 — NoInputNoOutput so iOS pairs without a passkey."""

    PATH = f"{BASE}/agent0"

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass

    @dbus.service.method("org.bluez.Agent1", in_signature="s", out_signature="s")
    def RequestPinCode(self, device):
        print(f"[agent] pin code requested for {device}")
        return "000000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        print(f"[agent] passkey {passkey:06d} for {device}")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pin):
        print(f"[agent] pin {pin} for {device}")

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"[agent] confirming {passkey:06d} for {device}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        print(f"[agent] passkey entry requested for {device}")
        raise NotSupported("cannot enter passkeys")

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"[agent] authorising {uuid} on {device}")

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def Cancel(self):
        pass


def build_objects():
    objects = {}
    chars = []

    def svc(path, uuid):
        objects[path] = {
            "org.bluez.GattService1": {
                "UUID": dbus.String(uuid),
                "Primary": dbus.Boolean(True),
            }
        }

    def char(path, uuid, service_path, value, flags=("read",)):
        c = Characteristic(path, uuid, service_path, value, flags)
        chars.append(c)
        objects[path] = c.props()

    def desc(path, uuid, char_path, value):
        d = Descriptor(path, uuid, char_path, value)
        chars.append(d)
        objects[path] = d.props()

    # --- HID over GATT (keyboard) ---
    hid = f"{BASE}/service1812"
    svc(hid, "1812")

    char(f"{hid}/char2a4a", "2a4a", hid, struct.pack("<HBB", 0x0101, 0x00, 0x02))
    char(f"{hid}/char2a4b", "2a4b", hid, REPORT_MAP)
    char(f"{hid}/char2a4c", "2a4c", hid, bytes([0]), flags=("write-without-response",))
    char(f"{hid}/char2a4d", "2a4d", hid, bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
         flags=("read", "notify"))
    desc(f"{hid}/char2a4d/desc2908", "2908", f"{hid}/char2a4d", bytes([0x01, 0x01]))
    char(f"{hid}/char2a4e", "2a4e", hid, bytes([0x01]), flags=("read", "write-without-response"))

    # --- Battery ---
    bat = f"{BASE}/service180f"
    svc(bat, "180f")
    char(f"{bat}/char2a19", "2a19", bat, bytes([0x64]))

    # --- Device Information ---
    dis = f"{BASE}/service180a"
    svc(dis, "180a")
    # PnP ID: vendor id source 0x02 (Bluetooth SIG), vendor, product, version
    char(f"{dis}/char2a50", "2a50", dis, bytes([0x02, 0xFF, 0xFF, 0x01, 0x00, 0x01, 0x00]))

    return objects, chars


def main():
    agent = Agent(BUS, Agent.PATH)
    agent_props = dbus.Dictionary(
        {"Capability": dbus.String("NoInputNoOutput")}, signature_type_check=False
    )
    aggr = dbus.Interface(BUS.get_object(BLUEZ, ADAPTER_PATH), "org.bluez.Adapter1")
    try:
        aggr.RegisterAgent(dbus.ObjectPath(Agent.PATH), "NoInputNoOutput")
        aggr.RequestDefaultAgent(dbus.ObjectPath(Agent.PATH))
        print("[agent] registered as default (NoInputNoOutput)")
    except dbus.exceptions.DBusException as exc:
        print(f"[agent] registration failed: {exc}")

    objects, chars = build_objects()
    app = Application(objects)
    advert = Advertisement(BUS, Advertisement.PATH)

    gatt_mgr = dbus.Interface(BUS.get_object(BLUEZ, ADAPTER_PATH), "org.bluez.GattManager1")
    adv_mgr = dbus.Interface(BUS.get_object(BLUEZ, ADAPTER_PATH), "org.bluez.LEAdvertisingManager1")

    try:
        gatt_mgr.RegisterApplication(dbus.ObjectPath(app.PATH), {}, reply_handler=lambda *a: None,
                                     error_handler=lambda e: print(f"[gatt] {e}"))
        adv_mgr.RegisterAdvertisement(dbus.ObjectPath(advert.PATH), {},
                                      reply_handler=lambda *a: None,
                                      error_handler=lambda e: print(f"[advert] {e}"))
    except dbus.exceptions.DBusException as exc:
        print(f"registration failed: {exc}")
        return 1

    GLib.timeout_add(2000, lambda: print_status(app, advert))
    print(f"advertising as '{LOCAL_NAME}' (keyboard, HID 0x1812).")
    print("On the iPhone: Settings > Bluetooth, look for it, tap to pair.")
    print("Ctrl-C to stop.")
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            adv_mgr.UnregisterAdvertisement(dbus.ObjectPath(advert.PATH))
        except Exception:
            pass
        try:
            gatt_mgr.UnregisterApplication(dbus.ObjectPath(app.PATH))
        except Exception:
            pass
    return 0


def print_status(app, advert):
    # Periodic nudge so it is obvious the process is alive while pairing.
    print("… still advertising")
    return True


if __name__ == "__main__":
    sys.exit(main())
