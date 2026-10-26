"""Notification listing and the emulator-only fakes."""

import pytest

from mobiletester.android import extras
from mobiletester.android.adb import AdbError

# Shaped like `dumpsys notification --noredact` on Android 14.
RECORD = ("    NotificationRecord(0x0a1b2c3d: pkg=com.example.pantry user=UserHandle{0} id=12 tag=null "
          "importance=3 key=0|com.example.pantry|12|null|10123: Notification(channel=orders))")
DUMPSYS = f"""Current Notification Manager state:
  Notification List:
{RECORD}
      uid=10123 userId=0
      extras={{
        android.title=String (Your order is on its way)
        android.text=String (Arrives today between 18:00 and 19:00)
      }}
      actions={{
        [0] "Track" -> PendingIntent{{1a2b: PendingIntentRecord{{3c4d com.example.pantry broadcastIntent}}}}
        [1] "Contact driver" -> PendingIntent{{5e6f: PendingIntentRecord{{7a8b startActivity}}}}
      }}
    NotificationRecord(0x0e0f1011: pkg=com.android.systemui user=UserHandle{{0}} id=7 tag=null importance=2 key=x)
      extras={{
        android.title=String (USB debugging connected)
      }}
"""


def test_notifications_with_title_text_and_actions():
    assert extras.parse_notifications(DUMPSYS) == [
        {"package": "com.example.pantry", "title": "Your order is on its way",
         "text": "Arrives today between 18:00 and 19:00", "actions": ["Track", "Contact driver"]},
        {"package": "com.android.systemui", "title": "USB debugging connected", "text": "", "actions": []}]
    assert [n["package"] for n in extras.parse_notifications(DUMPSYS, "com.example.pantry")] == ["com.example.pantry"]


class _Adb:
    def __init__(self, serial):
        self.serial, self.calls = serial, []

    def run(self, *args, timeout=30, check=True):
        self.calls.append(" ".join(args))
        return b"OK"


def test_location_and_fingerprint_only_on_emulators():
    emulator = _Adb("emulator-5554")
    extras.set_location(emulator, 52.37, 4.89)
    extras.fingerprint(emulator, match=False)
    assert emulator.calls == ["emu geo fix 4.89 52.37", "emu finger touch 99"]
    with pytest.raises(AdbError, match="only be faked on an emulator"):
        extras.set_location(_Adb("3B181JEHN10205"), 52.37, 4.89)
