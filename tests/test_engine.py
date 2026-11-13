from keyboard_shortcuts.engine import EngineController
from keyboard_shortcuts.rules import default_rules

def test_release_binary_accepts_generated_rules(tmp_path):
    engine = EngineController(tmp_path)
    engine.check(default_rules())
    engine.check([])

