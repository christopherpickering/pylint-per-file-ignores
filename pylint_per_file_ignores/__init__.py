import re
from pathlib import Path
from typing import List, Optional

from pylint import utils
from pylint.checkers import BaseChecker
from pylint.exceptions import UnknownMessageError
from pylint.lint import PyLinter

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


def find_pyproject(src) -> Optional[Path]:
    """Search upstream for a pyproject.toml file."""
    for directory in Path(src).parents:
        pyproject = directory / "pyproject.toml"

        if pyproject.is_file():
            return pyproject


def get_checker_by_msg(linter, msg):
    for checker in linter.get_checkers():
        for key, value in checker.msgs.items():
            if msg in [key, value[1]]:
                return checker

    return None


class Suppress:
    def __init__(self, linter):
        self._linter = linter
        self._suppress = []
        self._messages_to_append = []

    def __enter__(self):
        self._orig_add_message = self._linter.add_message
        self._linter.add_message = self.add_message
        return self

    def add_message(self, *args, **kwargs):
        self._messages_to_append.append((args, kwargs))

    def suppress(self, *symbols):
        for symbol in symbols:
            self._suppress.append(symbol)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._linter.add_message = self._orig_add_message
        for to_append_args, to_append_kwargs in self._messages_to_append:
            if to_append_args[0] in self._suppress:
                continue
            self._linter.add_message(*to_append_args, **to_append_kwargs)


class DoSuppress:
    def __init__(self, linter: PyLinter, message_id_or_symbol, test_func):
        self.linter = linter
        self.message_id_or_symbol = message_id_or_symbol
        self.test_func = test_func
        self.resolved_symbols = None

    def __call__(self, chain, node):
        with Suppress(self.linter) as s:
            if self.test_func(node):
                s.suppress(*self.symbols)
            chain()

    @property
    def symbols(self) -> List:
        # At some point, pylint started preferring message symbols to message IDs.
        # However, this is not done consistently or uniformly
        #   - occasionally there are some message IDs with no matching symbols.
        # We try to work around this here by suppressing both the ID and the symbol.
        # This also gives us compatability with a broader range of pylint versions.

        # Similarly, between version 1.2 and 1.3 changed where the messages are stored
        # - see:
        #   https://bitbucket.org/logilab/pylint/commits/0b67f42799bed08aebb47babdc9fb0e761efc4ff#chg-reporters/__init__.py
        # Therefore here, we try the new attribute name, and fall back to the old
        # version for compatability with <=1.2 and >=1.3

        if self.resolved_symbols is not None:
            return self.resolved_symbols
        try:
            pylint_messages = self.get_message_definitions(self.message_id_or_symbol)
            the_symbols = [
                symbol
                for pylint_message in pylint_messages
                for symbol in (pylint_message.msgid, pylint_message.symbol)
                if symbol is not None
            ]
        except UnknownMessageError:
            # This can happen due to mismatches of pylint versions and plugin
            # expectations of available messages
            the_symbols = [self.message_id_or_symbol]
        self.resolved_symbols = the_symbols
        return the_symbols

    def get_message_definitions(self, message_id_or_symbol):
        msgs_store = getattr(self.linter, "msgs_store", self.linter)

        if hasattr(msgs_store, "check_message_id"):
            return [msgs_store.check_message_id(message_id_or_symbol)]
        # pylint 2.0 renamed check_message_id to get_message_definition in:
        # https://github.com/PyCQA/pylint/commit/5ccbf9eaa54c0c302c9180bdfb745566c16e416d
        if hasattr(msgs_store, "get_message_definition"):
            return [msgs_store.get_message_definition(message_id_or_symbol)]
        # pylint 2.3.0 renamed get_message_definition to get_message_definitions in:
        # https://github.com/PyCQA/pylint/commit/da67a9da682e51844fbc674229ff6619eb9c816a
        if hasattr(msgs_store, "get_message_definitions"):
            return msgs_store.get_message_definitions(message_id_or_symbol)

        msg = "pylint.utils.MessagesStore does not have a " "get_message_definition(s) method"
        raise ValueError(msg)


class AugmentFunc:
    def __init__(self, old_method, augmentation_func):
        self.old_method = old_method
        self.augmentation_func = augmentation_func

    def __call__(self, node):
        self.augmentation_func(Chain(self.old_method, node), node)


class Chain:
    def __init__(self, old_method, node):
        self.old_method = old_method
        self.node = node

    def __call__(self):
        self.old_method(self.node)


def get_message_definitions(linter, message_id_or_symbol):
    """
    Lookup that onverts a symbol or message string into a unified message.
    """
    msgs_store = getattr(linter, "msgs_store", linter)

    if hasattr(msgs_store, "check_message_id"):
        return [msgs_store.check_message_id(message_id_or_symbol)]
    # pylint 2.0 renamed check_message_id to get_message_definition in:
    # https://github.com/PyCQA/pylint/commit/5ccbf9eaa54c0c302c9180bdfb745566c16e416d
    if hasattr(msgs_store, "get_message_definition"):
        return [msgs_store.get_message_definition(message_id_or_symbol)]
    # pylint 2.3.0 renamed get_message_definition to get_message_definitions in:
    # https://github.com/PyCQA/pylint/commit/da67a9da682e51844fbc674229ff6619eb9c816a
    if hasattr(msgs_store, "get_message_definitions"):
        return msgs_store.get_message_definitions(message_id_or_symbol)

    msg = "pylint.utils.MessagesStore does not have a get_message_definition(s) method"
    raise ValueError(msg)


def augment_all_visit(linter, message_id_or_symbol, augmentation):
    """
    Augmenting a visit enables additional errors to be raised (although that case is
    better served using a new checker) or to suppress all warnings in certain
    circumstances.
    Augmenting functions should accept a 'chain' function, which runs the checker
    method and possibly any other augmentations, and secondly an Astroid node.
    "chain()" can be called at any point to trigger the continuation of other
    checks, or not at all to prevent any further checking.
    """
    checker = get_checker_by_msg(linter, message_id_or_symbol)

    for method in dir(checker):
        if method.startswith("visit"):
            old_method = getattr(checker, method)
            setattr(checker, method, AugmentFunc(old_method, augmentation))


def augment_add_message(linter, message_id_or_symbol, test_func):
    """
    Rather than augmenting all visit method,
    this override the checker.add_message method
    to cover all possible source of warnings.
    @returns True if checker.add_message method override is successful.
    """
    checker = get_checker_by_msg(linter, message_id_or_symbol)
    if not hasattr(checker, "add_message"):
        return False

    add_message_method = getattr(checker, "add_message")

    def add_message(*args, **kwargs):
        if test_func(None) and get_message_definitions(linter, args[0]) == get_message_definitions(
            linter, message_id_or_symbol
        ):
            return
        add_message_method(*args, **kwargs)

    setattr(checker, "add_message", add_message)

    return True


def disable_message(linter, message_id, test_func):
    """
    This wrapper allows the suppression of a message if the supplied test function
    returns True.
    """
    if augment_add_message(linter, message_id, test_func):
        return
    augment_all_visit(linter, message_id, DoSuppress(linter, message_id, test_func))


class IsFile:
    def __init__(self, file_string, linter):
        self.file_string = file_string
        self.linter = linter

    def __call__(self, node):
        return bool(
            re.search(self.file_string, Path(self.linter.current_file).as_posix(), re.VERBOSE)
        )


class PerFileIgnoresChecker(BaseChecker):
    # Just to register custom config option
    options = (
        (
            "per-file-ignores",
            {
                "default": "",
                "type": "string",
                "metavar": "<str>",
                "help": "Newline-separated list of ignores",
            },
        ),
    )


def register(linter: PyLinter) -> None:
    linter.register_checker(PerFileIgnoresChecker(linter))


def parse_string(input_string: str) -> list[str]:
    # For backward compatybility
    if "\n" in input_string:
        return utils._splitstrip(input_string, sep="\n")

    parts = input_string.split(",")

    result = []
    current_file = None
    current_errors = []
    for part in parts:
        if ":" in part:
            if current_file is not None:
                result.append(f"{current_file}:{','.join(current_errors)}")

            current_file, error = part.split(":", 1)
            current_errors = [error]
        else:
            current_errors.append(part)

    if current_file is not None:
        result.append(f"{current_file}:{','.join(current_errors)}")

    return result


def load_configuration(linter: PyLinter) -> None:
    # Loading configuration from native pylint configuration mechanism
    if isinstance(linter.config.per_file_ignores, str):
        linter.config.per_file_ignores = dict(
            config_item.split(":") for config_item in parse_string(linter.config.per_file_ignores)
        )
    elif not isinstance(linter.config.per_file_ignores, dict):
        linter.config.per_file_ignores = dict(
            config_item.strip().split(":") for config_item in linter.config.per_file_ignores
        )
    # else: assert isinstance(linter.config.per_file_ignores, dict)

    for file_path, rules in linter.config.per_file_ignores.items():
        for rule in rules.split(","):
            disable_message(linter, rule.strip(), IsFile(file_path, linter))

    # Loading custom pyproject.toml
    pyproject_file = find_pyproject(linter.current_file)
    if pyproject_file:
        with open(pyproject_file, "rb") as pyproject_file_object:
            content = tomllib.load(pyproject_file_object)
            ignores = {**content.get("tool", {}).get("pylint-per-file-ignores", {})}

        for file_path, rules in ignores.items():
            for rule in rules.split(","):
                disable_message(linter, rule.strip(), IsFile(file_path, linter))
