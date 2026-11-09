"""Safe, dependency-free helpers for user-facing utility commands."""

from __future__ import annotations

import ast
import math
import re


_DURATION_TOKEN = re.compile(
    r"(?P<amount>\d+)(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|"
    r"days?|d|weeks?|w)",
    re.IGNORECASE,
)
_DURATION_SECONDS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}
_BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.FloorDiv: lambda left, right: left // right,
    ast.Mod: lambda left, right: left % right,
    ast.Pow: lambda left, right: left**right,
}
_UNARY_OPERATORS = {
    ast.UAdd: lambda value: value,
    ast.USub: lambda value: -value,
}


def parse_duration_seconds(value: str) -> int:
    """Parse compact or spaced durations such as '1h 30m' into bounded seconds."""
    compact = re.sub(r"\s+", "", value.strip().lower())
    if not compact:
        raise ValueError("Enter a duration such as `10m`, `2h`, or `1d`.")
    seconds = 0
    position = 0
    for match in _DURATION_TOKEN.finditer(compact):
        if match.start() != position:
            raise ValueError("Use whole-number units such as `s`, `m`, `h`, `d`, or `w`.")
        amount = int(match.group("amount"))
        seconds += amount * _DURATION_SECONDS[match.group("unit").lower()]
        position = match.end()
    if position != len(compact) or seconds <= 0:
        raise ValueError("Enter a valid duration greater than zero.")
    if seconds > 365 * 24 * 60 * 60:
        raise ValueError("Reminders can be scheduled up to one year ahead.")
    return seconds


def calculate(expression: str) -> int | float:
    """Evaluate a small arithmetic expression without eval or arbitrary code."""
    if not expression.strip() or len(expression) > 120:
        raise ValueError("Enter an arithmetic expression under 120 characters.")
    try:
        root = ast.parse(expression, mode="eval")
        result = _evaluate_node(root.body)
    except (SyntaxError, ZeroDivisionError, OverflowError, TypeError) as exc:
        raise ValueError("That is not a valid, supported calculation.") from exc
    try:
        finite = math.isfinite(float(result))
    except OverflowError as exc:
        raise ValueError("That calculation is outside the supported numeric range.") from exc
    if not finite or abs(result) > 1e100:
        raise ValueError("That calculation is outside the supported numeric range.")
    return result


def _evaluate_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            raise ValueError("Boolean values are not supported.")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponents must be between -12 and 12.")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))
    raise ValueError("Only numeric literals and basic arithmetic are supported.")
