import ast
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Protocol

from injected_utils import async_cached
from pinjected import injected, IProxy, instance, Injected
from loguru import logger


@contextlib.contextmanager
def suppress_logs():
    """Context manager to temporarily suppress logging."""
    # Save current logger level
    handler_ids = logger.configure(handlers=[{"sink": lambda _: None, "level": "ERROR"}])
    try:
        yield
    finally:
        # Restore logger configuration
        for hid in handler_ids:
            logger.remove(hid)


@dataclass
class SymbolMetadata:
    is_injected: bool
    is_instance: bool
    is_class: bool
    module: str


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
    tree = await a_ast(src_path.read_text())
    metadata = {}
    module_name = src_path.stem
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol_name = node.name
            symbol_info = SymbolMetadata(
                is_injected=False,
                is_instance=False,
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
            metadata[f"{module_name}.{symbol_name}"] = symbol_info
    return metadata


@injected
async def a_collect_imported_symbol_metadata(
        a_collect_symbol_metadata: callable,
        a_ast: callable,
        /,
        src_path: Path
) -> Dict[str, SymbolMetadata]:
    # Use context manager to suppress logging
    with suppress_logs():
        logger.debug(f"a_collect_imported_symbol_metadata が呼び出されました: {src_path}")
        tree = await a_ast(src_path.read_text())
        imported_metadata = {}
        base_dir = src_path.parent
        logger.debug(f"基準ディレクトリ: {base_dir}")

        # サードパーティパッケージと標準ライブラリのリスト（必要に応じて更新）
        external_packages = {
            'dataclasses', 'pathlib', 'typing', 'loguru', 'ast', 'os', 'sys',
            'collections', 're', 'json', 'time', 'datetime', 'logging',
            'pinjected'  # 外部パッケージとして追加
        }

        def is_same_package_import(module_name: str, current_path: Path) -> bool:
            """同一パッケージ内のインポートかどうかを判定"""
            parts = current_path.parts
            if 'src' in parts:
                src_index = parts.index('src')
                package_parts = parts[src_index + 1:]
                package_path = '.'.join(package_parts[:-1])  # ファイル名を除く
                return module_name.startswith(package_path)
            return False

        def find_project_root(start_dir: Path) -> tuple[Path, Optional[Path]]:
            """プロジェクトルートとsrcディレクトリを探す"""
            logger.debug(f"プロジェクトルート検索開始: {start_dir}")
            current = start_dir
            src_dir = None

            while current != Path('/'):
                logger.debug(f"  ディレクトリチェック中: {current}")
                if (current / 'setup.py').exists() or (current / 'pyproject.toml').exists():
                    logger.debug(f"  setup.py/pyproject.toml を発見: {current}")
                    if (current / 'src').exists() and (current / 'src').is_dir():
                        src_dir = current / 'src'
                        logger.debug(f"  src ディレクトリを発見: {src_dir}")
                    break
                if (current / 'src').exists() and (current / 'src').is_dir():
                    logger.debug(f"  src ディレクトリを発見: {current}/src")
                    src_dir = current / 'src'
                    break
                current = current.parent

            if current == Path('/'):
                logger.debug("  プロジェクトルートが見つかりませんでした。現在のディレクトリを使用します。")
                return start_dir, src_dir

            return current, src_dir

        def module_path_calc(node: ast.ImportFrom, current_path: Path) -> Optional[Path]:
            """モジュールの実際のファイルパスを計算する"""
            logger.debug(
                f"module_path_calc 呼び出し: module={node.module}, level={node.level}, current_path={current_path}")

            # 外部パッケージならスキップ
            if node.module in external_packages or node.module.split('.')[0] in external_packages:
                logger.debug(f"  外部パッケージをスキップ: {node.module}")
                return None

            if node.level == 0:  # 絶対インポート
                logger.debug(f"  絶対インポートの処理: {node.module}")

                # プロジェクトルートとsrcディレクトリを探す
                project_root, src_dir = find_project_root(base_dir)
                logger.debug(f"  プロジェクトルート: {project_root}")
                logger.debug(f"  src ディレクトリ: {src_dir}")

                # 同じパッケージ内のインポートか確認
                if is_same_package_import(node.module, current_path):
                    logger.debug(f"  同一パッケージ内のインポートと判断: {node.module}")

                    # パッケージ名を含まないシンプルなモジュール名を取得
                    module_parts = node.module.split('.')
                    simple_module_name = module_parts[-1]

                    # 同じディレクトリ内のモジュールとして検索
                    simple_path = current_path.parent / f"{simple_module_name}.py"
                    logger.debug(f"  同一ディレクトリ内のモジュールを確認: {simple_path}")
                    if simple_path.exists():
                        logger.debug(f"  同一ディレクトリ内にモジュールが見つかりました: {simple_path}")
                        return simple_path

                # モジュールパスの構築試行
                # 可能性のあるすべてのベースディレクトリのリスト
                base_dirs = []

                # 1. 現在のディレクトリ
                base_dirs.append(base_dir)

                # 2. srcディレクトリが見つかった場合
                if src_dir:
                    base_dirs.append(src_dir)

                # 3. プロジェクトルートディレクトリ
                if project_root != base_dir:
                    base_dirs.append(project_root)

                logger.debug(f"  検索対象のベースディレクトリ: {base_dirs}")

                # 各ディレクトリでパスを試す
                for directory in base_dirs:
                    # 直接の.pyファイル
                    mod_path = directory / Path(node.module.replace('.', '/') + '.py')
                    logger.debug(f"  試行 - {directory} からのパス: {mod_path}")
                    if mod_path.exists():
                        logger.debug(f"  成功: ファイルが存在します: {mod_path}")
                        return mod_path

                    # __init__.pyファイル
                    init_path = directory / Path(node.module.replace('.', '/')) / "__init__.py"
                    logger.debug(f"  試行 - {directory} からの__init__パス: {init_path}")
                    if init_path.exists():
                        logger.debug(f"  成功: __init__.pyファイルが存在します: {init_path}")
                        return init_path

                # より単純なアプローチでsrcディレクトリ内のパスを試行
                if src_dir:
                    # モジュール名の最後の部分だけを使用
                    module_parts = node.module.split('.')
                    simple_name = module_parts[-1]

                    # プロジェクトのsrcディレクトリを再帰的に検索
                    logger.debug(f"  src内をモジュール{simple_name}で再帰的に検索")

                    found_paths = []
                    for path in src_dir.glob(f"**/{simple_name}.py"):
                        found_paths.append(path)

                    if found_paths:
                        logger.debug(f"  見つかったパス: {found_paths}")
                        # 最も近いと思われるパスを返す（仮の実装）
                        logger.debug(f"  最も近いと思われるパスを使用: {found_paths[0]}")
                        return found_paths[0]

                logger.debug(f"  絶対インポートのパス解決に失敗: {node.module}")
                return None
            else:  # 相対インポート
                logger.debug(f"  相対インポートの処理: level={node.level}, module={node.module}")

                # 現在のファイルの親ディレクトリから開始
                relative_path = current_path.parent
                logger.debug(f"  開始ディレクトリ: {relative_path}")

                # レベルに合わせて上に移動
                original_level = node.level
                for i in range(node.level - 1):
                    prev_path = relative_path
                    relative_path = relative_path.parent
                    logger.debug(f"  レベル {i + 1}/{original_level - 1}: {prev_path} -> {relative_path}")

                # モジュールが指定されている場合は追加
                final_path = relative_path
                if node.module:
                    module_parts = node.module.split('.')
                    for i, part in enumerate(module_parts):
                        prev_path = final_path
                        final_path = final_path / part
                        logger.debug(f"  モジュール部分 {i + 1}/{len(module_parts)}を追加: {prev_path} -> {final_path}")

                # モジュールファイルが存在するか確認
                module_file = final_path.with_suffix('.py')
                logger.debug(f"  モジュールファイルをチェック: {module_file}")
                if module_file.exists():
                    logger.debug(f"  モジュールファイルが存在します")
                    return module_file

                # パッケージの場合は__init__.pyを確認
                init_file = final_path / '__init__.py'
                logger.debug(f"  __init__.pyファイルをチェック: {init_file}")
                if init_file.exists():
                    logger.debug(f"  __init__.pyファイルが存在します")
                    return init_file

                logger.debug(f"  相対インポートのパス解決に失敗: level={node.level}, module={node.module}")
                return None

        # インポート文を収集
        import_nodes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                import_nodes.append(node)

        # インポート情報のログ出力
        logger.debug(f"ファイル {src_path} から {len(import_nodes)} 個のインポート文を検出")
        for i, node in enumerate(import_nodes):
            logger.debug(
                f"インポート #{i + 1}: from {node.module} import {[name.name for name in node.names]} (level={node.level})")

        # 実際の処理
        for i, node in enumerate(import_nodes):
            logger.debug(f"インポート #{i + 1} を処理中: {node.module} (level={node.level})")
            module_path = module_path_calc(node, src_path)

            if module_path and module_path.exists():
                logger.debug(f"  モジュールパスが見つかりました: {module_path}")
                logger.debug(f"  シンボルメタデータを収集中...")
                module_metadata = await a_collect_symbol_metadata(module_path)
                logger.debug(f"  {len(module_metadata)} 個のシンボルメタデータを収集しました")
                imported_metadata.update(module_metadata)
            elif node.module and node.module not in external_packages and node.module.split('.')[
                0] not in external_packages:
                logger.debug(
                    f"  モジュール {node.module} のパスを解決できませんでした。external_packagesリストに追加を検討してください。")

        logger.debug(f"合計 {len(imported_metadata)} 個のインポートされたシンボルメタデータを収集しました")
        return imported_metadata


@dataclass(frozen=True)
class Misuse:
    user_function: str
    used_proxy: str
    line_number: int
    misuse_type: str
    src_node: ast.AST = None


@injected
async def a_detect_misuse_of_pinjected_proxies(
        a_collect_symbol_metadata: callable,
        a_collect_imported_symbol_metadata: callable,
        a_ast: callable,
        /,
        src_path: Path
) -> List[Misuse]:
    with logger.contextualize(tag="a_detect_misuse"):
        local_metadata = await a_collect_symbol_metadata(src_path)
        imported_metadata = await a_collect_imported_symbol_metadata(src_path)
        all_metadata = {**local_metadata, **imported_metadata}

        tree = await a_ast(src_path.read_text())
        module_name = src_path.stem

        # 各関数定義と返り値の型アノテーションを記録する辞書
        function_returns = {}

        # シンボル情報を取得する関数
        def get_symbol_info(name):
            qualified_name = f"{module_name}.{name}"
            symbol_info = all_metadata.get(qualified_name)

            if not symbol_info:
                symbol_info = all_metadata.get(name)

                if not symbol_info:
                    for full_name, info in all_metadata.items():
                        if full_name.endswith(f".{name}"):
                            return info, full_name

            return symbol_info, qualified_name if symbol_info else None

        # 最初に全関数の返り値型を収集
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                returns_iproxy = False
                # IProxy型の返り値かどうかをチェック
                if node.returns:
                    if isinstance(node.returns, ast.Name) and node.returns.id == "IProxy":
                        returns_iproxy = True
                    elif isinstance(node.returns, ast.Subscript) and getattr(node.returns.value, "id", "") == "IProxy":
                        returns_iproxy = True

                function_returns[node.name] = returns_iproxy

        misuse = await _find_misues(function_returns, get_symbol_info, tree)
        return list(sorted(misuse, key=lambda x: x.line_number))


async def _find_misues(function_returns, get_symbol_info, tree):
    misuse = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # this args change depending on if it's @injected or @instance.
            #logger.info(f"loop start for {node.name}")
            function_meta,_ = get_symbol_info(node.name)
            if function_meta.is_instance:
                #logger.warning(f"instance function detected: {node.name}")
                args = {arg.arg for arg in node.args.args}
                #logger.warning(f"args for instance function: {args}")
            elif function_meta.is_injected:
                args = {arg.arg for arg in node.args.posonlyargs}
                #logger.warning(f"args for injected function; {args}")
            else:
                # the function is not decorated, so we can't really know what it's doing
                #logger.warning(f"using empty args for node:{node.name}")
                args = set()
            #logger.info(f"args for {node.name}: {args}")



            # 現在の関数がIProxyを返す型かどうか
            returns_iproxy = function_returns.get(node.name, False)

            # 関数内での呼び出しを追跡
            for subnode in ast.walk(node):
                # 処理しないケース
                if isinstance(subnode, ast.Name) and (subnode.id == node.name or subnode.id in args):
                    continue

                accessed_name = None
                misuse_type = None
                msg_direct_use = 'Direct access to IProxy detected. You must request the dependency, by placing it in the function arguments.'

                # 変数への代入をチェック
                if isinstance(subnode, ast.Assign) and isinstance(subnode.value, ast.Name):
                    accessed_name = subnode.value.id
                    misuse_type = msg_direct_use

                # 関数呼び出しをチェック
                elif isinstance(subnode, ast.Call) and isinstance(subnode.func, ast.Name):
                    accessed_name = subnode.func.id
                    misuse_type = msg_direct_use

                # 単純な名前参照をチェック
                elif isinstance(subnode, ast.Name):
                    # 親ノードが関数呼び出しでないことを確認（変数参照のみ）
                    parent_nodes = [p for p in ast.iter_child_nodes(node) if
                                    hasattr(p, 'lineno') and p.lineno == subnode.lineno]
                    is_call_arg = any(isinstance(p, ast.Call) and subnode in p.args for p in parent_nodes)

                    if not is_call_arg:
                        accessed_name = subnode.id
                        misuse_type = msg_direct_use

                # 検出されたアクセス名の処理
                if accessed_name and misuse_type:
                    symbol_info, qualified_name = get_symbol_info(accessed_name)

                    if symbol_info and (symbol_info.is_injected or symbol_info.is_instance):
                        if accessed_name not in args and not returns_iproxy:
                            logger.warning(f"detected misuse of pinjected proxy: {accessed_name} in {node.name},{args}")
                            # we need to check if it's @injected and making mistake by not using `/`
                            if function_meta.is_injected:
                                wrong_args_set = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
                                logger.warning(f"checking if {accessed_name} is in {wrong_args_set}")
                                if accessed_name in wrong_args_set:
                                    misuse_type = 'dependency in non_pos_only argument (Dependencies should be placed before `/`. No `/` means the args are not injected.)'
                            misuse.append(Misuse(
                                user_function=node.name,
                                used_proxy=qualified_name,
                                line_number=subnode.lineno,
                                misuse_type=misuse_type,
                                src_node=node
                            ))

    return misuse


@instance
async def dummy_config():
    return dict()


@injected
async def a_misuse_of_injected():
    print(dummy_config)  # mistake, dummy_config is IProxy object so it should be requested (not detected)
    print(dummy_config())  # mistake, dummy_config is IProxy object so it cannot be requested (now detected)
    from pinjected_reviewer.pytest_reviewer.coding_rule_plugin_impl import a_pytest_plugin_impl
    print(a_pytest_plugin_impl)
    print(a_pytest_plugin_impl())


@instance
async def another_misuse():
    print(dummy_config)  # mistake, dummy_config is IProxy object so it should be requested (not detected)
    print(dummy_config())  # mistake, dummy_config is IProxy object so it cannot be requested (now detected)


async def yet_another_misuse():
    print(dummy_config)  # mistake, dummy_config is IProxy object so it should be requested (not detected)
    print(dummy_config())  # mistake, dummy_config is IProxy object so it cannot be requested (now detected)


def correct_use() -> IProxy:
    return dummy_config


from pinjected import design

test_collect_current_file: IProxy = a_collect_symbol_metadata(
    Path(__file__)
)

test_collect_imported_file: IProxy = a_collect_imported_symbol_metadata(
    Path(__file__)
)
# - Symbol a_pytest_plugin_impl/inspect_code.a_pytest_plugin_impl not found in metadata.
# That is too right, it must be coding_rule_plugin.
test_detect_misuse: IProxy = a_detect_misuse_of_pinjected_proxies(
    Path(__file__)
)
import pinjected_reviewer.entrypoint
test_detect_misuse:IProxy = a_detect_misuse_of_pinjected_proxies(
    Path(pinjected_reviewer.entrypoint.__file__)
)


class DetectMisuseOfPinjectedProxies(Protocol):
    async def __call__(self, src_path: Path) -> List[Misuse]:
        ...


__meta_design__ = design(

)
