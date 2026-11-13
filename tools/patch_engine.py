"""Patch the pinned keymapper source tree copied for the product build."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
stage = root / "src/runtime/Stage.cpp"
source = stage.read_text(encoding="utf-8")
old = """      if (get_trigger_key(k.trigger) == key) {"""
new = """      if (const auto* sequence = std::get_if<const KeySequence*>(&k.trigger)) {
        // A chord stops holding its output when any required key is released.
        if (std::any_of((*sequence)->begin(), (*sequence)->end(),
              [key](const KeyEvent& event) {
                return event.key == key && event.state == KeyState::Down;
              }))
          return false;
      }
      if (get_trigger_key(k.trigger) == key) {"""
if new not in source:
    if source.count(old) != 1:
        raise SystemExit("Unexpected keymapper source")
    stage.write_text(source.replace(old, new), encoding="utf-8")


devices = root / "src/server/windows/Devices.cpp"
source = devices.read_text(encoding="utf-8")
source = source.replace(
    "  auto instance_id = get_string(&CM_Get_Device_Interface_PropertyW,",
    """  using InterfaceProperty = CONFIGRET (WINAPI *)(LPCWSTR, const DEVPROPKEY*,
      DEVPROPTYPE*, PBYTE, PULONG, ULONG);
  auto get_interface_property = reinterpret_cast<InterfaceProperty>(
    GetProcAddress(GetModuleHandleW(L"cfgmgr32.dll"), "CM_Get_Device_Interface_PropertyW"));
  if (!get_interface_property)
    return;
  auto instance_id = get_string(get_interface_property,""",
)
devices.write_text(source, encoding="utf-8")

for relative, old, new in [
    ("src/control/main.cpp", "absolute(filename, error)", "absolute(std::filesystem::u8path(filename), error)"),
    ("src/control/main.cpp", "send_set_config_file(absolute.string())", "send_set_config_file(absolute.u8string())"),
    ("src/client/ClientState.cpp", "if (load_config(filename))", "if (load_config(std::filesystem::u8path(filename)))"),
]:
    path = root / relative
    contents = path.read_text(encoding="utf-8")
    if new not in contents:
        if old not in contents:
            raise SystemExit(f"Unexpected keymapper source: {relative}")
        path.write_text(contents.replace(old, new), encoding="utf-8")

source = devices.read_text(encoding="utf-8")
source = source.replace("#include <hidsdi.h>", 'extern "C" {\n#include <hidsdi.h>\n}')
devices.write_text(source, encoding="utf-8")

control = root / "src/control/main.cpp"
source = control.read_text(encoding="utf-8")
old = """    return to_result(read_virtual_key_state(timeout));
  }
  
  Result request_next_key_info"""
new = """    const auto [result, state] = read_virtual_key_state(timeout);
    return result != Result::yes ? result :
      (state == KeyState::Up ? Result::yes : Result::no);
  }
  
  Result request_next_key_info"""
if new not in source:
    if old not in source:
        raise SystemExit("Unexpected keymapper acknowledgement")
    control.write_text(source.replace(old, new), encoding="utf-8")

source = devices.read_text(encoding="utf-8")
source = source.replace('m_module(LoadLibraryA("interception.dll"))', 'm_module(nullptr)')
devices.write_text(source, encoding="utf-8")
