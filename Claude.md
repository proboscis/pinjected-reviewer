# Notes for Claude - pinjected-reviewer

## Build/Test/Lint Commands
- Use rye for Python management: `rye run python <script>`
- Run all tests: `rye run pytest`
- Run a single test: `rye run pytest tests/pytest_reviewer/test_coding_rule_plugin_impl.py::test_check_if_file_should_be_ignored`
- Run the CLI: `rye run python -m pinjected_reviewer <command>` or `rye run pinjected-reviewer <command>`

## Code Style Guidelines
- **Imports**: Group standard library, third-party, and local imports separated by blank lines
- **Async functions**: Prefix with `a_` (e.g., `a_review_python_pinjected`)
- **Pinjected Decorators**:
  - Use `@instance` for objects/values (returns `IProxy[T]`)
  - Use `@injected` for functions (returns `IProxy[Callable[[non_injected], T]]`)
  - Place `/` after dependency params in `@injected` functions
- **Types**: Use type annotations and Protocol classes for interfaces
- **Error Handling**: Use specific exceptions rather than generic ones
- **Documentation**: Include docstrings with descriptions, args, and return values
- **Testing**: Prefer `@injected_pytest` for tests of pinjected code
- **Proxy File Tags**: Add `# pinjected-reviewer: ignore` to files that should be skipped

## Plugin Specific
- To disable plugin in pytest: `--no-pinjected-reviewer`
- To continue tests despite errors: `--pinjected-continue-on-error`