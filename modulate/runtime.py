"""A small, bounded interpreter for generated number-display programs.

This is a deliberately limited Python-shaped language, not a Python sandbox.
Only this module's AST interpreter runs: generated source is never compiled,
evaluated, imported, or given access to Python objects or device APIs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import random
import re


MAX_SOURCE_LENGTH = 6000
MAX_OPERATIONS = 200
MAX_INTEGER = 1_000_000_000
MAX_DISPLAY_NUMBER = 999_999
MAX_LABEL_LENGTH = 24
_MAX_AST_NODES = 800
_MAX_AST_DEPTH = 32
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z", re.ASCII)
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z", re.ASCII)
_FUNCTIONS = frozenset({"randint", "abs", "min", "max"})
_RESERVED = _FUNCTIONS | {"show"}
_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)
_COMPARISONS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_RNG = random.SystemRandom()


class ValidationError(ValueError):
    """The program is outside the language or exceeds a runtime bound."""


@dataclass(frozen=True)
class Frame:
    number: int
    label: str = ""
    foreground: str = "#FFFFFF"
    background: str = "#000000"

    def as_dict(self) -> dict[str, int | str]:
        return {
            "number": self.number,
            "label": self.label,
            "foreground": self.foreground,
            "background": self.background,
        }


def _integer(value: object) -> int:
    if type(value) is not int or abs(value) > MAX_INTEGER:
        raise ValidationError(f"Integers must be between {-MAX_INTEGER} and {MAX_INTEGER}")
    return value


def _identifier(name: str) -> None:
    if not _NAME.fullmatch(name) or "__" in name or name in _RESERVED:
        raise ValidationError(f"Invalid or reserved variable name: {name!r}")


def _style(call: ast.Call) -> dict[str, str]:
    result: dict[str, str] = {}
    for keyword in call.keywords:
        name = keyword.arg
        if name not in {"label", "foreground", "background"} or name in result:
            raise ValidationError("show accepts each of label, foreground, background once")
        if not isinstance(keyword.value, ast.Constant) or type(keyword.value.value) is not str:
            raise ValidationError("show style arguments must be literal strings")
        value = keyword.value.value
        if name == "label":
            if len(value) > MAX_LABEL_LENGTH or any(not 32 <= ord(char) <= 126 for char in value):
                raise ValidationError("Labels must contain at most 24 printable ASCII characters")
        elif not _COLOR.fullmatch(value):
            raise ValidationError("Colors must use #RRGGBB hexadecimal notation")
        result[name] = value
    return result


class _Validator:
    def __init__(self) -> None:
        self.operations = 0

    def charge(self) -> None:
        self.operations += 1
        if self.operations > MAX_OPERATIONS:
            raise ValidationError("Program exceeds the 200-operation budget")

    def block(self, statements: list[ast.stmt], names: set[str]) -> set[str]:
        names = set(names)
        for statement in statements:
            self.charge()
            if isinstance(statement, ast.Assign):
                if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                    raise ValidationError("Assignments require one simple variable name")
                name = statement.targets[0].id
                _identifier(name)
                self.expression(statement.value, names)
                names.add(name)
            elif isinstance(statement, ast.If):
                self.comparison(statement.test, names)
                yes = self.block(statement.body, names)
                no = self.block(statement.orelse, names)
                names = yes & no
            else:
                raise ValidationError("Only assignments and if comparisons may precede final show")
        return names

    def comparison(self, node: ast.AST, names: set[str]) -> None:
        self.charge()
        if not isinstance(node, ast.Compare) or not all(isinstance(op, _COMPARISONS) for op in node.ops):
            raise ValidationError("if requires an integer comparison")
        self.expression(node.left, names)
        for operand in node.comparators:
            self.expression(operand, names)

    def expression(self, node: ast.AST, names: set[str]) -> None:
        self.charge()
        if isinstance(node, ast.Constant):
            _integer(node.value)
        elif isinstance(node, ast.Name):
            _identifier(node.id)
            if node.id not in names:
                raise ValidationError(f"Variable is not assigned on every path: {node.id}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            self.expression(node.operand, names)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, _BINOPS):
            self.expression(node.left, names)
            self.expression(node.right, names)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise ValidationError("Only randint, abs, min, and max are numeric functions")
            if node.keywords:
                raise ValidationError("Numeric functions accept positional arguments only")
            count = len(node.args)
            valid_count = {"randint": count == 2, "abs": count == 1,
                           "min": 2 <= count <= 8, "max": 2 <= count <= 8}
            if not valid_count[node.func.id]:
                raise ValidationError("randint needs 2 arguments, abs 1, and min/max 2–8")
            for argument in node.args:
                self.expression(argument, names)
        else:
            raise ValidationError(f"Unsupported numeric expression: {type(node).__name__}")

    def program(self, tree: ast.Module) -> None:
        if not tree.body:
            raise ValidationError("Program must end with exactly one show call")
        last = tree.body[-1]
        if (not isinstance(last, ast.Expr) or not isinstance(last.value, ast.Call)
                or not isinstance(last.value.func, ast.Name) or last.value.func.id != "show"):
            raise ValidationError("Program must end with exactly one top-level show call")
        names = self.block(tree.body[:-1], set())
        self.charge()
        if len(last.value.args) != 1:
            raise ValidationError("show requires exactly one positional number")
        self.expression(last.value.args[0], names)
        _style(last.value)


def _parse(source: str) -> ast.Module:
    if type(source) is not str or len(source) > MAX_SOURCE_LENGTH:
        raise ValidationError("Source must be a string of at most 6000 characters")
    if not source.isascii():
        raise ValidationError("Source must use ASCII characters")
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ValidationError("Invalid program syntax") from error
    pending: list[tuple[ast.AST, int]] = [(tree, 0)]
    nodes = 0
    while pending:
        node, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_AST_NODES or depth > _MAX_AST_DEPTH:
            raise ValidationError("Program is too large or deeply nested")
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    _Validator().program(tree)
    return tree


def validate(source: str) -> None:
    """Check all syntax, branches, names, and static bounds without running code.

    Arithmetic, random-range, and final numeric-output bounds are also checked
    during run(), since they may depend on computed values. Each statement and
    numeric expression counts toward the static budget, including both branches.
    """
    _parse(source)


class _Interpreter:
    def __init__(self) -> None:
        self.names: dict[str, int] = {}
        self.operations = 0

    def charge(self) -> None:
        self.operations += 1
        if self.operations > MAX_OPERATIONS:
            raise ValidationError("Execution exceeds the 200-operation budget")

    def expression(self, node: ast.expr) -> int:
        self.charge()
        if isinstance(node, ast.Constant):
            return _integer(node.value)
        if isinstance(node, ast.Name):
            return self.names[node.id]
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand)
            return _integer(-value if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BinOp):
            left, right = self.expression(node.left), self.expression(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.FloorDiv):
                if right == 0:
                    raise ValidationError("Division by zero")
                value = left // right
            else:
                if right == 0:
                    raise ValidationError("Modulo by zero")
                value = left % right
            return _integer(value)
        if isinstance(node, ast.Call):
            arguments = [self.expression(argument) for argument in node.args]
            name = node.func.id
            if name == "randint":
                low, high = arguments
                if low > high or high - low > MAX_INTEGER:
                    raise ValidationError("randint requires an ordered range spanning at most 1000000000")
                return _integer(_RNG.randint(low, high))
            if name == "abs":
                return _integer(abs(arguments[0]))
            return _integer(min(arguments) if name == "min" else max(arguments))
        raise ValidationError("Unsupported expression")

    def comparison(self, node: ast.Compare) -> bool:
        self.charge()
        left = self.expression(node.left)
        for operator, operand in zip(node.ops, node.comparators):
            right = self.expression(operand)
            if isinstance(operator, ast.Eq):
                matches = left == right
            elif isinstance(operator, ast.NotEq):
                matches = left != right
            elif isinstance(operator, ast.Lt):
                matches = left < right
            elif isinstance(operator, ast.LtE):
                matches = left <= right
            elif isinstance(operator, ast.Gt):
                matches = left > right
            else:
                matches = left >= right
            if not matches:
                return False
            left = right
        return True

    def block(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self.charge()
            if isinstance(statement, ast.Assign):
                self.names[statement.targets[0].id] = self.expression(statement.value)
            else:
                branch = statement.body if self.comparison(statement.test) else statement.orelse
                self.block(branch)

    def program(self, tree: ast.Module) -> Frame:
        self.block(tree.body[:-1])
        self.charge()
        call = tree.body[-1].value
        number = self.expression(call.args[0])
        if not -MAX_DISPLAY_NUMBER <= number <= MAX_DISPLAY_NUMBER:
            raise ValidationError("Displayed number must be between -999999 and 999999")
        return Frame(number=number, **_style(call))


def run(source: str) -> Frame:
    """Validate then interpret one program, returning its single bounded frame."""
    return _Interpreter().program(_parse(source))
