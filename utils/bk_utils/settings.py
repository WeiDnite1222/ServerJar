"""
bk_core

Copyright (c) 2024~2025 Techarerm/TedKai
Copyright (c) 2026 Kitee Contributors. All rights reserved.
"""
import contextlib
import copy
import json
from pathlib import Path


def validation_rule(
    default=None,
    *,
    children=None,
    write_back_if_not_exist=False,
    recover_missing_items=False,
):
    rule = {
        "writeBackIfNotExist": write_back_if_not_exist,
        "recoverMissingItems": recover_missing_items,
    }

    if children is not None:
        rule["children"] = children
    else:
        rule["default"] = default

    return rule


def required_value(default, *, recover_missing_items=False):
    return validation_rule(
        default,
        write_back_if_not_exist=True,
        recover_missing_items=recover_missing_items,
    )


def required_section(children):
    return validation_rule(children=children, write_back_if_not_exist=True)


class FileSettings:
    """
    Simple Settings Object
    IMPORTANT: Settings always use self.data as the main operate data, NOT FROM disk settings file!!!

    Usage:
    FileSettings.create() -> Create settings file (path is self.path)
    FileSettings.load() - > Load settings file
    FileSettings.save() -> Save settings file
    FileSettings.edit() -> Edit settings file (Auto save when with block completes)

    Example:
    with FileSettings.edit() as settings:
        settings["hello"] = "world"
    """
    def __init__(self, path, default, validation_rules=None,
                dumps_func=json.dumps, load_func=json.load,
                 settings_change_callback=None):
        self.data = copy.deepcopy(default)
        self.default = copy.deepcopy(default)
        self.path: Path = Path(path)
        self.validation_rules = validation_rules
        self.dumps_func = dumps_func
        self.load_func = load_func
        self.settings_change_callback = settings_change_callback

    def reset(self):
        """Replace self.data with self.default and save"""
        self.data = copy.deepcopy(self.default)
        self.save()

        if callable(self.settings_change_callback):
            self.settings_change_callback(self.data)

    def __repr__(self):
        return f"<FileSettings At {self.path.as_posix()}>"

    def create(self, exist_ok=False):
        """
        Create settings file (path is self.path, data use default value)
        :param exist_ok: If not True, raise exception if file already exists
        :return:
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if not exist_ok and self.path.exists():
            raise FileExistsError(f'{self.path} already exists')

        self.path.write_text(self._dumps(self.default))

    def read_from_exist(self):
        self.data = self.load()

    def mload(self):
        """Get data from memory"""
        return copy.deepcopy(self.data)

    def load(self):
        """
        Load settings file data into self.data (path is self.path)
        :return:
        """
        if not self.path.exists():
            raise FileNotFoundError(f'{self.path} does not exist')

        with self.path.open("rb") as settings_file:
            data = self.load_func(settings_file)

        if isinstance(self.validation_rules, dict):
            data = self.validate_data(data, self.default, self.validation_rules)

        return data

    def save(self):
        """
        Save self.data (data in memory) into settings file
        :return:
        """
        if not self.path.exists():
            raise FileNotFoundError(f'{self.path} does not exist. Create it before saving.')

        self.path.write_text(self._dumps(self.data))

    def get(self, key, default=None):
        return self.data.get(key, default)

    def dget(self, key, default=None): # dget -> get_default
        return self.default.get(key, default)

    def exists(self):
        return self.path.exists()

    @contextlib.contextmanager
    def edit(self):
        """
        Edit settings (With auto save)
        :return:
        """
        if not self.exists():
            self.create()
        yield self

        self.save()

        if callable(self.settings_change_callback):
            self.settings_change_callback(self)

    def validate_data(self, data, default, rules):
        """
        Validates data by validating rules.
        :param data: dict data
        :param default: default sample
        :param rules: rules of all keys
        :return:
        """
        if not isinstance(data, dict):
            data = {}

        if not isinstance(default, dict):
            default = {}

        if not isinstance(rules, dict):
            return copy.deepcopy(data)

        validated = copy.deepcopy(data)

        for key, rule in rules.items():
            rule_default, options = self._parse_validation_rule(rule)
            default_value = copy.deepcopy(default.get(key, rule_default))

            if key not in validated:
                if options.get("writeBackIfNotExist"):
                    validated[key] = self._validate_value(
                        default_value,
                        default_value,
                        rule_default,
                        options,
                    )
                continue

            validated[key] = self._validate_value(
                validated[key],
                default_value,
                rule_default,
                options,
            )

        return validated

    def update(self, settings):
        """Update self.data with new settings values."""
        if not isinstance(settings, dict):
            raise TypeError("settings must be a dict")

        def update_inner(new, old):
            if not isinstance(old, dict):
                return

            for n_k, n_v in new.items():
                if isinstance(n_v, dict) and (n_k in old and isinstance(old[n_k], dict)):
                    update_inner(n_v, old[n_k])
                else:
                    old[n_k] = copy.deepcopy(n_v)

        update_inner(settings, self.data)

        if callable(self.settings_change_callback):
            self.settings_change_callback(self)

    def update_new_settings(self, new_default_settings):
        """Add missing settings to self.default and self.data."""
        if not isinstance(new_default_settings, dict):
            raise TypeError("new_default_settings must be a dict")

        def add_missing(new, old):
            if not isinstance(old, dict):
                return

            for n_k, n_v in new.items():
                if isinstance(n_v, dict) and (n_k in old and isinstance(old[n_k], dict)):
                    add_missing(n_v, old[n_k])
                if n_k not in old:
                    old[n_k] = copy.deepcopy(n_v)

        add_missing(new_default_settings, self.default)
        add_missing(new_default_settings, self.data)

        if callable(self.settings_change_callback):
            self.settings_change_callback(self)

    @staticmethod
    def _parse_validation_rule(rule):
        if isinstance(rule, dict) and ("default" in rule or "children" in rule):
            options = {
                "writeBackIfNotExist": rule.get("writeBackIfNotExist", False),
                "recoverMissingItems": rule.get("recoverMissingItems", False), # Recover missing item (only for list)
            }

            if "children" in rule:
                return rule["children"], options

            return rule.get("default"), options

        if (
            isinstance(rule, (list, tuple))
            and len(rule) == 2
            and isinstance(rule[1], dict)
        ):
            return rule[0], rule[1]

        return rule, {}

    def _validate_value(self, value, default_value, rule_default, options):
        if isinstance(rule_default, dict):
            if not isinstance(value, dict):
                value = {}

            if not isinstance(default_value, dict):
                default_value = {}

            return self.validate_data(value, default_value, rule_default)

        if isinstance(default_value, list):
            if not isinstance(value, list):
                return copy.deepcopy(default_value)

            validated = copy.deepcopy(value)

            if options.get("recoverMissingItems"):
                for item in default_value:
                    if item not in validated:
                        validated.append(copy.deepcopy(item))

            return validated

        if default_value is None:
            return value

        if type(value) is not type(default_value):
            return copy.deepcopy(default_value)

        return value

    def _dumps(self, data):
        if not callable(self.dumps_func):
            raise TypeError(f"dumps_func must be callable")

        return self.dumps_func(data)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

        if callable(self.settings_change_callback):
            self.settings_change_callback(self)

    def __eq__(self, other):
        if isinstance(other, FileSettings):
            return self.path == other.path and self.data == other.data

        if isinstance(other, dict):
            return self.data == other

        return NotImplemented
