import ast
from enum import Enum, auto


class XianStandard(Enum):
    XSC001 = auto()
    # XSC002 = auto()  # Future standards


class ValidatorBase(ast.NodeVisitor):
    def validate(self) -> tuple[bool, list[str]]:
        raise NotImplementedError


def _is_name_call(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def _metadata_assignment_key(stmt: ast.stmt) -> str | None:
    if not isinstance(stmt, ast.Assign):
        return None

    for target in stmt.targets:
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "metadata"
            and isinstance(target.slice, ast.Constant)
            and isinstance(target.slice.value, str)
        ):
            return target.slice.value
    return None


class ValidatorXSC001(ValidatorBase):
    def __init__(self):
        self.required_variables = {"balances", "approvals", "metadata"}
        self.required_functions = {
            "change_metadata": ("key", "value"),
            "transfer": ("amount", "to"),
            "approve": ("amount", "to"),
            "transfer_from": ("amount", "to", "main_account"),
            "balance_of": ("address",),
        }
        self.found_variables: set[str] = set()
        self.found_functions: dict[str, tuple[str, ...]] = {}
        self.has_constructor = False
        self.is_hash_type: dict[str, bool] = {}
        self.metadata_fields = {
            "token_name",
            "token_symbol",
            "token_logo_url",
            "token_logo_svg",
            "token_website",
        }
        self.found_metadata_fields: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
            var_name = target.id
            self.found_variables.add(var_name)
            self.is_hash_type[var_name] = _is_name_call(node.value, "Hash")

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        func_name = node.name
        args = tuple(arg.arg for arg in node.args.args)
        self.found_functions[func_name] = args

        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "construct":
                self.has_constructor = True

        if func_name == "seed":
            for stmt in node.body:
                metadata_key = _metadata_assignment_key(stmt)
                if metadata_key is not None:
                    self.found_metadata_fields.add(metadata_key)

        self.generic_visit(node)

    def validate(self) -> tuple[bool, list[str]]:
        errors = []

        missing_vars = self.required_variables - self.found_variables
        if missing_vars:
            errors.append(f"Missing required variables: {missing_vars}")

        errors.extend(
            f"Variable {var} must be of type Hash"
            for var in self.required_variables
            if var in self.found_variables and not self.is_hash_type.get(var)
        )

        for func, required_args in self.required_functions.items():
            if func not in self.found_functions:
                errors.append(f"Missing required function: {func}")
            elif self.found_functions[func] != required_args:
                found_args = self.found_functions[func]
                errors.append(
                    f"Function {func} has incorrect arguments. "
                    f"Expected {required_args}, got {found_args}"
                )

        if not self.has_constructor:
            errors.append("Missing constructor (@construct decorator)")

        missing_metadata = self.metadata_fields - self.found_metadata_fields
        if missing_metadata:
            errors.append(
                f"Missing required metadata fields: {missing_metadata}"
            )

        return not errors, errors


class ValidatorFactory:
    @staticmethod
    def get_validator(standard: XianStandard) -> ValidatorBase:
        if standard == XianStandard.XSC001:
            return ValidatorXSC001()
        raise ValueError(f"Unsupported standard: {standard}")


def validate_contract(
    contract_code: str, standard: XianStandard = XianStandard.XSC001
) -> tuple[bool, list[str]]:
    """
    Validates if a contract follows the specified token standard
    Args:
        contract_code: String containing the contract code
        standard: TokenStandard enum specifying which standard to validate
            against
    Returns:
        Tuple of (is_valid: bool, errors: List[str])
    """
    try:
        tree = ast.parse(contract_code)
        validator = ValidatorFactory.get_validator(standard)
        validator.visit(tree)
        return validator.validate()
    except SyntaxError as e:
        return False, [f"Syntax error in contract: {e}"]
    except Exception as e:
        return False, [f"Error validating contract: {e}"]
