import ast
import contextlib
import symtable
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Protocol, Union

from injected_utils import async_cached
from loguru import logger
from pinjected import injected, IProxy, Injected, instance


@contextlib.contextmanager
def suppress_logs():
    """Context manager to temporarily suppress logging."""
    # Save current logger level
    # handler_ids = logger.configure(handlers=[{"sink": lambda _: None, "level": "ERROR"}])
    try:
        yield
    finally:
        # Restore logger configuration
        # for hid in handler_ids:
        #     logger.remove(hid)
        pass


@dataclass
class SymbolMetadata:
    is_injected: bool
    is_instance: bool
    is_class: bool
    is_injected_pytest: bool
    module: str

    @property
    def is_iproxy(self):
        return self.is_injected or self.is_instance


@async_cached(Injected.dict())
@injected
async def a_ast(src: str) -> ast.AST:
    # assert isinstance(src_file, Path), "src_file must be a Path instance."
    # source_code = src_file.read_text()
    return ast.parse(src)


@injected
async def a_collect_symbol_metadata(
        a_ast: callable,
        /,
        src_path: Path
) -> Dict[str, SymbolMetadata]:
    # Check if file exists
    if not src_path.exists():
        logger.warning(f"File does not exist for symbol metadata collection: {src_path}")
        return {}
        
    try:
        # Read file content and parse AST
        file_content = src_path.read_text()
        tree = await a_ast(file_content)
        
        metadata = {}
        module_name = src_path.stem
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbol_name = node.name
                symbol_info = SymbolMetadata(
                    is_injected=False,
                    is_instance=False,
                    is_injected_pytest=False,
                    is_class=isinstance(node, ast.ClassDef),
                    module=module_name
                )
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Name):
                            if dec.id == "injected":
                                symbol_info.is_injected = True
                            elif dec.id == "instance":
                                symbol_info.is_instance = True
                            elif dec.id == "injected_pytest":
                                symbol_info.is_injected_pytest = True
                        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                            # Handle decorator calls like @injected_pytest()
                            if dec.func.id == "injected_pytest":
                                symbol_info.is_injected_pytest = True
                metadata[f"{module_name}.{symbol_name}"] = symbol_info
        return metadata
    except Exception as e:
        logger.error(f"Error collecting symbol metadata for {src_path}: {e}")
        return {}


@injected
async def a_collect_imported_symbol_metadata(
        a_collect_symbol_metadata: callable,
        a_ast: callable,
        /,
        src_path: Path
) -> Dict[str, SymbolMetadata]:
    # Check if file exists
    if not src_path.exists():
        logger.warning(f"File does not exist for imported symbol metadata collection: {src_path}")
        return {}
        
    try:
        # For simplicity, we'll only handle direct module imports in the same directory
        # This is a simplified version focused on error handling for deleted files
        file_content = src_path.read_text()
        tree = await a_ast(file_content)
        
        # Disable pinjected_reviewer logging
        logger.disable('pinjected_reviewer')
        
        # Find import statements
        import_nodes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                import_nodes.append(node)
                
        # A simplified approach
        imported_metadata = {}
        base_dir = src_path.parent
        
        # External packages to skip
        external_packages = {
            'dataclasses', 'pathlib', 'typing', 'loguru', 'ast', 'os', 'sys',
            'collections', 're', 'json', 'time', 'datetime', 'logging',
            'pinjected'
        }
        
        # Process imports
        for node in import_nodes:
            # Skip external packages
            if node.module in external_packages or (node.module and node.module.split('.')[0] in external_packages):
                continue
                
            # Handle relative imports
            if node.level > 0:
                # Walk up directories based on level
                target_dir = src_path.parent
                for _ in range(node.level - 1):
                    target_dir = target_dir.parent
                    
                # If module specified, append it
                if node.module:
                    module_path = target_dir / f"{node.module}.py"
                    if module_path.exists():
                        module_metadata = await a_collect_symbol_metadata(module_path)
                        imported_metadata.update(module_metadata)
                    
                    # Also check for __init__.py in package
                    init_path = target_dir / node.module / "__init__.py"
                    if init_path.exists():
                        module_metadata = await a_collect_symbol_metadata(init_path)
                        imported_metadata.update(module_metadata)
            else:
                # Absolute import - try as a local module 
                module_path = base_dir / f"{node.module}.py"
                if module_path.exists():
                    module_metadata = await a_collect_symbol_metadata(module_path)
                    imported_metadata.update(module_metadata)
                    
                # Also check for __init__.py in package
                init_path = base_dir / node.module / "__init__.py"
                if init_path.exists():
                    module_metadata = await a_collect_symbol_metadata(init_path)
                    imported_metadata.update(module_metadata)
            
        return imported_metadata
    except Exception as e:
        logger.error(f"Error collecting imported symbol metadata for {src_path}: {e}")
        return {}


@dataclass(frozen=True)
class Misuse:
    user_function: str
    used_proxy: str
    line_number: int
    misuse_type: str
    src_node: ast.AST = None


@dataclass
class SymbolMetadataGetter:
    symbol_metadata: dict[str, SymbolMetadata]
    imported_symbol_metadata: dict[str, SymbolMetadata]
    tree: ast.AST
    src_path: Path

    def __post_init__(self):
        self.all_metadata = {**self.symbol_metadata, **self.imported_symbol_metadata}
        # 各関数定義と返り値の型アノテーションを記録する辞書
        function_returns = {}
        # 最初に全関数の返り値型を収集
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                returns_iproxy = False
                # IProxy型の返り値かどうかをチェック
                if node.returns:
                    if isinstance(node.returns, ast.Name) and node.returns.id == "IProxy":
                        returns_iproxy = True
                    elif isinstance(node.returns, ast.Subscript) and getattr(node.returns.value, "id", "") == "IProxy":
                        returns_iproxy = True

                function_returns[node.name] = returns_iproxy
        self.function_returns = function_returns

    def func_returns_iproxy(self, func_name: str) -> bool:
        return self.function_returns.get(func_name, False)

    # シンボル情報を取得する関数
    def get_symbol_info(self, name) -> tuple[Optional[SymbolMetadata], Optional[str]]:
        module_name = self.src_path.stem
        qualified_name = f"{module_name}.{name}"
        symbol_info = self.all_metadata.get(qualified_name)

        if not symbol_info:
            symbol_info = self.all_metadata.get(name)

            if not symbol_info:
                for full_name, info in self.all_metadata.items():
                    if full_name.endswith(f".{name}"):
                        return info, full_name

        return symbol_info, qualified_name if symbol_info else None


@injected
async def a_symbol_metadata_getter(
        a_collect_symbol_metadata: callable,
        a_collect_imported_symbol_metadata: callable,
        a_ast: callable,
        /,
        src_path: Path
):
    # Check if file exists
    if not src_path.exists():
        logger.warning(f"File does not exist for metadata collection: {src_path}")
        # Return empty metadata
        return SymbolMetadataGetter(
            symbol_metadata={},
            imported_symbol_metadata={},
            tree=ast.parse(""),  # Empty AST
            src_path=src_path
        )
        
    try:
        # Read file content
        file_content = src_path.read_text()
        
        local_metadata = await a_collect_symbol_metadata(src_path)
        imported_metadata = await a_collect_imported_symbol_metadata(src_path)
        tree = await a_ast(file_content)

        return SymbolMetadataGetter(
            symbol_metadata=local_metadata,
            imported_symbol_metadata=imported_metadata,
            tree=tree,
            src_path=src_path
        )
    except Exception as e:
        logger.error(f"Error collecting metadata for {src_path}: {e}")
        # Return empty metadata on error
        return SymbolMetadataGetter(
            symbol_metadata={},
            imported_symbol_metadata={},
            tree=ast.parse(""),  # Empty AST
            src_path=src_path
        )


@injected
async def a_detect_misuse_of_pinjected_proxies(
        a_symbol_metadata_getter: callable,
        a_ast,
        /,
        src_path: Path
) -> List[Misuse]:
    with logger.contextualize(tag="a_detect_misuse"):
        # Check if file exists
        if not src_path.exists():
            logger.warning(f"File does not exist: {src_path}")
            return []
            
        try:
            # Read file content
            file_content = src_path.read_text()
        except Exception as e:
            logger.error(f"Failed to read file {src_path}: {e}")
            return []
            
        try:
            # Process file for misuses
            detector = MisuseDetector(await a_symbol_metadata_getter(src_path))
            detector.visit(await a_ast(file_content))
            misuse = detector.misuses
            return list(sorted(misuse, key=lambda x: x.line_number))
        except Exception as e:
            logger.error(f"Error detecting misuses in {src_path}: {e}")
            return []


@dataclass
class FuncStack:
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    injection_keys: set[str]


class MisuseDetector(ast.NodeVisitor):
    def __init__(self, symbol_metadata_getter):
        self.symbol_metadata_getter:SymbolMetadataGetter = symbol_metadata_getter
        self.injection_stack: list[FuncStack] = []
        self.misuses = []

    def _get_injection_keys(self, node):
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                if dec.id == "injected":
                    return {arg.arg for arg in node.args.posonlyargs}
                if dec.id == "instance":
                    return {arg.arg for arg in node.args.args}
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                if dec.func.id == "injected_pytest":
                    return {arg.arg for arg in node.args.args}
        return {}

    def is_key_injected(self, key):
        for stack in self.injection_stack:
            if key in stack.injection_keys:
                return True
        return False

    def _push_function(self, node):
        self.injection_stack.append(FuncStack(node=node, injection_keys=self._get_injection_keys(node)))

    def _pop_function(self):
        self.injection_stack.pop()

    def visit_FunctionDef(self, node):
        self._push_function(node)
        self.generic_visit(node)
        self._pop_function()

    def visit_AsyncFunctionDef(self, node):
        self._push_function(node)
        self.generic_visit(node)
        self._pop_function()

    def _outermost_function(self):
        if not self.injection_stack:
            return None
        return self.injection_stack[-1]

    def _innermost_function(self):
        if not self.injection_stack:
            return None
        return self.injection_stack[0]

    def visit_Name(self, node):
        """
        Now we can check if a key is actually injected, or not.
        :param node:
        :return:
        """
        info, name = self.symbol_metadata_getter.get_symbol_info(node.id)
        info: SymbolMetadata
        if info and info.is_iproxy and not self.is_key_injected(node.id):
            if innermost := self._innermost_function():
                if not self.symbol_metadata_getter.func_returns_iproxy(innermost.node.name):
                    if outermost := self._outermost_function():
                        self.misuses.append(Misuse(
                            user_function=outermost.node.name,
                            used_proxy=node.id,
                            line_number=node.lineno,
                            misuse_type="Direct access to IProxy detected. You must request the dependency, by placing it in the function arguments.",
                            src_node=node
                        ))
        self.generic_visit(node)




from pinjected import design
import pinjected_reviewer.examples

test_collect_current_file: IProxy = a_collect_symbol_metadata(
    Path(pinjected_reviewer.examples.__file__)
)

test_collect_imported_file: IProxy = a_collect_imported_symbol_metadata(
    Path(pinjected_reviewer.examples.__file__)
)
# - Symbol a_pytest_plugin_impl/inspect_code.a_pytest_plugin_impl not found in metadata.
# That is too right, it must be coding_rule_plugin.
test_detect_misuse: IProxy = a_detect_misuse_of_pinjected_proxies(
    Path(pinjected_reviewer.examples.__file__)
)
import pinjected_reviewer.entrypoint

test_detect_misuse_2: IProxy = a_detect_misuse_of_pinjected_proxies(
    Path(pinjected_reviewer.entrypoint.__file__)
)
test_not_detect_imports: IProxy = a_detect_misuse_of_pinjected_proxies(
    Path(pinjected_reviewer.__file__).parent.parent / '__package_for_tests__' / 'valid_module.py'
)


@injected
async def a_symtable(src_path: Path):
    tbl = symtable.symtable((src_path.read_text()), src_path.name, 'exec')
    return tbl


check_symtable: IProxy = a_symtable(Path(pinjected_reviewer.examples.__file__)).get_identifiers()


# please run this test by
# `rye run python -m pinjected run pinjected_reviewer.pytest_reviewer.inspect_code.test_not_detect_imports`


class DetectMisuseOfPinjectedProxies(Protocol):
    async def __call__(self, src_path: Path) -> List[Misuse]:
        ...


__meta_design__ = design(

)