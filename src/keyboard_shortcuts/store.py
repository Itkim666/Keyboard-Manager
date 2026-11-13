from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .rules import Rule, default_rules, find_conflict

DEFAULT_CAPTURE_HOTKEY = "Ctrl+S"


@dataclass(frozen=True)
class Settings:
    theme: str = "system"
    start_on_login: bool = True
    close_to_tray: bool = True
    pause_hotkey: str = ""
    capture_hotkey: str = DEFAULT_CAPTURE_HOTKEY

    def __post_init__(self):
        if self.theme not in ("system", "light", "dark"):
            raise ValueError("主题设置无效。")
        if type(self.start_on_login) is not bool or type(self.close_to_tray) is not bool:
            raise ValueError("开关设置无效。")
        if not isinstance(self.pause_hotkey, str) or len(self.pause_hotkey) > 60:
            raise ValueError("暂停快捷键无效。")
        if not isinstance(self.capture_hotkey, str) or len(self.capture_hotkey) > 60:
            raise ValueError("截图快捷键无效。")


@dataclass(frozen=True)
class Config:
    rules: list[Rule]
    settings: Settings = field(default_factory=Settings)


def load_config(path: Path, *, first_run: bool = True) -> Config:
    if first_run and not path.exists():
        return Config(default_rules())
    try:
        with path.open(encoding="utf-8-sig") as stream:
            data = json.load(stream)
        if data["version"] != 1 or not isinstance(data["rules"], list):
            raise ValueError("配置文件格式或版本不受支持。")
        rules = []
        for row in data["rules"]:
            if not isinstance(row["source"], list) or not isinstance(row["target"], list):
                raise ValueError("按键列表格式无效。")
            rule = Rule(tuple(row["source"]), tuple(row["target"]), row["app_path"], row["enabled"])
            if find_conflict(rule, rules) is not None:
                raise ValueError("文件包含重复规则。")
            rules.append(rule)
        return Config(rules, Settings(**data.get("settings", {})))
    except (TypeError, AttributeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("配置文件格式无效。") from error


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as stream:
        pending = Path(stream.name)
    try:
        pending.write_text(content, encoding="utf-8")
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def save_config(path: Path, config: Config) -> None:
    atomic_write(path, json.dumps({"version": 1, **asdict(config)}, ensure_ascii=False, indent=2))


def merge_config(old: Config, incoming: Config, replace: bool, include_settings: bool) -> Config:
    rules = [] if replace else old.rules.copy()
    for rule in incoming.rules:
        index = find_conflict(rule, rules)
        if index is None:
            rules.append(rule)
        else:
            rules[index] = rule
    return Config(rules, incoming.settings if include_settings else old.settings)

