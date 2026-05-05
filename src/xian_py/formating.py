import re

MIN_JSON_INTEGER = -(2**63)
MAX_JSON_INTEGER = 2**64 - 1
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def kwargs_are_formatted(kwargs: dict) -> bool:
    return (
        isinstance(kwargs, dict)
        and all(identifier_is_formatted(key) for key in kwargs)
        and json_value_is_formatted(kwargs)
    )


def json_value_is_formatted(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not json_value_is_formatted(item):
                return False
        return True
    if isinstance(value, list):
        return all(json_value_is_formatted(item) for item in value)
    if type(value) is int:
        return MIN_JSON_INTEGER <= value <= MAX_JSON_INTEGER
    return not isinstance(value, float)


def identifier_is_formatted(s: str) -> bool:
    return isinstance(s, str) and _IDENTIFIER_RE.fullmatch(s) is not None


def number_is_formatted(i: int) -> bool:
    if type(i) is not int:
        return False
    if i < 0:
        return False
    return i <= MAX_JSON_INTEGER


def key_is_formatted(s: str) -> bool:
    return isinstance(s, str) and _HEX_KEY_RE.fullmatch(s) is not None


def cid_id_formatted(s: str) -> bool:
    return isinstance(s, str) and s != ""


TRANSACTION_PAYLOAD_RULES = {
    "sender": key_is_formatted,
    "nonce": number_is_formatted,
    "chi_supplied": number_is_formatted,
    "contract": identifier_is_formatted,
    "function": identifier_is_formatted,
    "kwargs": kwargs_are_formatted,
    "chain_id": cid_id_formatted,
}


def dict_has_keys(d: dict, keys: set) -> bool:
    return set(d) == keys


def format_dictionary(d: dict) -> dict:
    return _format_value(d)


def _format_value(value):
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Non-string key types not allowed.")
            items.append((key, _format_value(item)))
        return dict(sorted(items))
    if isinstance(value, list):
        return [_format_value(item) for item in value]
    return value


def recurse_rules(d: dict, rule: dict) -> bool:
    if callable(rule):
        return rule(d)

    for key, subrule in rule.items():
        arg = d[key]

        if callable(subrule):
            if not subrule(arg):
                return False

        elif type(arg) is dict:
            if not recurse_rules(arg, subrule):
                return False

        elif type(arg) is list:
            for a in arg:
                if not recurse_rules(a, subrule):
                    return False

        else:
            return False

    return True


def check_format_of_payload(d: dict) -> bool:
    rule = TRANSACTION_PAYLOAD_RULES
    expected_keys = set(rule.keys())

    if not dict_has_keys(d, expected_keys):
        return False

    return recurse_rules(d, rule)
