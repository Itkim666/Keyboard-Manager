from keyboard_shortcuts.rules import Rule, compile_config, default_rules, find_conflict

def test_default_rules():
    assert [(r.source, r.target) for r in default_rules()] == [
        (("ShiftLeft", key), (output,)) for key, output in
        zip("DFJK", ("ArrowLeft", "ArrowUp", "ArrowDown", "ArrowRight"))
    ]

def test_application_priority_and_scope():
    global_rule = default_rules()[0]
    scoped = Rule(global_rule.source, ("Home",), r"C:\测试 [1]\edit.exe")
    assert find_conflict(scoped, [global_rule]) is None
    assert find_conflict(Rule(scoped.source, ("End",), r"c:\测试 [1]\EDIT.exe"), [scoped]) == 0
    config = compile_config([global_rule, scoped, Rule(("A",), ("B",), enabled=False)])
    assert config.index(">> !Any Home") < config.index(">> !Any ArrowLeft")
    assert r"^C:\\测试\ \[1\]\\edit\.exe$" in config
    assert " >> B" not in config


