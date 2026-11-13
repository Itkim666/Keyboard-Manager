import pytest
from keyboard_shortcuts.rules import default_rules, Rule
from keyboard_shortcuts.store import Config, load_config, save_config, merge_config

def test_first_start_and_empty_config(tmp_path):
    path = tmp_path / "settings.json"
    assert load_config(path).rules == default_rules()
    save_config(path, Config([]))
    assert load_config(path).rules == []

def test_invalid_data_does_not_load(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"version":99,"rules":[]}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)

def test_merge_replaces_only_matching_scope():
    old = Config(default_rules())
    candidate = Rule(old.rules[0].source, ("Home",))
    scoped = Rule(candidate.source, ("End",), r"C:\apps\note.exe")
    assert merge_config(old, Config([candidate, scoped]), False, False).rules == [
        candidate, *old.rules[1:], scoped
    ]

