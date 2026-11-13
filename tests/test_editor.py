from keyboard_shortcuts.windows import event_key

class NativeEvent:
    def __init__(self, scan, vk=0):
        self.scan = scan
        self.vk = vk

    def nativeScanCode(self):
        return self.scan

    def nativeVirtualKey(self):
        return self.vk


def test_left_and_right_modifiers_are_distinct():
    assert event_key(NativeEvent(0x2A)) == "ShiftLeft"
    assert event_key(NativeEvent(0x36)) == "ShiftRight"
    assert event_key(NativeEvent(0x11D)) == "ControlRight"
    assert event_key(NativeEvent(0x138)) == "AltRight"

