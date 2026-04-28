import re

MIN_JSON_INTEGER = -(2**63)
MAX_JSON_INTEGER = 2**64 - 1


def kwargs_are_formatted(kwargs: dict):
    if not isinstance(kwargs, dict):
        return False
    for key in kwargs.keys():
        if not identifier_is_formatted(key):
            return False
    return json_value_is_formatted(kwargs)


def json_value_is_formatted(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not json_value_is_formatted(item):
                return False
        return True
    if isinstance(value, list):
        return all(json_value_is_formatted(item) for item in value)
    if type(value) is int:
        return MIN_JSON_INTEGER <= value <= MAX_JSON_INTEGER
    if isinstance(value, float):
        return False
    return True


def identifier_is_formatted(s: str):
    try:
        iden = re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", s)
        if iden is None:
            return False
        return True
    except TypeError:
        return False


def number_is_formatted(i: int):
    if type(i) is not int:
        return False
    if i < 0:
        return False
    return i <= MAX_JSON_INTEGER


def key_is_formatted(s: str):
    try:
        int(s, 16)
        if len(s) != 64:
            return False
        return True
    except ValueError:
        return False
    except TypeError:
        return False


def cid_id_formatted(s: str):
    return type(s) is str and s != ""


TRANSACTION_PAYLOAD_RULES = {
    "sender": key_is_formatted,
    "nonce": number_is_formatted,
    "chi_supplied": number_is_formatted,
    "contract": identifier_is_formatted,
    "function": identifier_is_formatted,
    "kwargs": kwargs_are_formatted,
    "chain_id": cid_id_formatted,
}


def dict_has_keys(d: dict, keys: set):
    key_set = set(d.keys())
    return len(keys ^ key_set) == 0


def format_dictionary(d: dict) -> dict:
    for k, v in d.items():
        if type(k) is not str:
            raise TypeError("Non-string key types not allowed.")
        if type(v) is list:
            for i in range(len(v)):
                if isinstance(v[i], dict):
                    v[i] = format_dictionary(v[i])
        elif isinstance(v, dict):
            d[k] = format_dictionary(v)
    return {k: v for k, v in sorted(d.items())}


def recurse_rules(d: dict, rule: dict):
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


def check_format_of_payload(d: dict):
    rule = TRANSACTION_PAYLOAD_RULES
    expected_keys = set(rule.keys())

    if not dict_has_keys(d, expected_keys):
        return False

    return recurse_rules(d, rule)
