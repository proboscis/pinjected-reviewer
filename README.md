# Pinjected Reviewer

[![Version](https://img.shields.io/badge/version-0.4.0-blue.svg)](https://github.com/proboscis/pinjected-reviewer)

A git pre-commit hook that validates code against pinjected coding style guidelines.

## Features

- Automated code review for pinjected coding style compliance
- Git pre-commit hook integration
- Easy installation and uninstallation
- Uses LLM to provide detailed feedback on code style violations
- Caches results for faster subsequent reviews

## Installation

### As a dependency in a Rye project

Add the dependency to your Rye project:

```bash
rye add pinjected-reviewer --git "https://github.com/proboscis/pinjected-reviewer.git"
```

Install the pre-commit hook:

```bash
rye run python -m pinjected_reviewer install
```

### As a standalone package

Clone the repository:

```bash
git clone https://github.com/proboscis/pinjected-reviewer.git
cd pinjected-reviewer
```

Install dependencies using Rye:

```bash
rye sync
```

Install the pre-commit hook:

```bash
rye run python -m pinjected_reviewer install
```

## Usage

Once installed, the pre-commit hook will automatically run whenever you attempt to make a git commit. If your code doesn't follow the pinjected coding style guidelines, the commit will be rejected with detailed feedback.

### Using the CLI

The package installs a command-line tool that you can use directly:

```bash
# Review code
pinjected-reviewer review

# Install the pre-commit hook
pinjected-reviewer install

# Uninstall the pre-commit hook
pinjected-reviewer uninstall
```

### Using the Python Module

You can also run commands through the Python module:

```bash
# Review code
rye run python -m pinjected_reviewer review

# Install the pre-commit hook
rye run python -m pinjected_reviewer install

# Uninstall the pre-commit hook
rye run python -m pinjected_reviewer uninstall
```

### Integration with Pytest

The package comes with a pytest plugin that automatically checks your code for pinjected compliance when running tests:

```bash
# Run tests with pinjected-reviewer (enabled by default)
pytest

# Disable pinjected-reviewer
pytest --no-pinjected-reviewer

# Run tests even if pinjected-reviewer finds errors
pytest --pinjected-continue-on-error
```

The plugin provides several options:

- The plugin is automatically enabled when the package is installed
- Use `--no-pinjected-reviewer` to disable the code review
- Use `--pinjected-continue-on-error` to run tests even if code review finds errors

When enabled, the plugin:
1. Scans your project's Python files for pinjected usage issues
2. Reports all issues in the terminal summary after tests complete
3. Fails the test run if error-level issues are found (unless overridden)
4. Color-codes issues by severity (errors in red, warnings in yellow, etc.)

## How it Works

The reviewer checks all staged Python files for pinjected coding style compliance, including:

- Proper use of `@injected` and `@instance` decorators
- Correct dependency injection patterns
- Proper function structure and argument handling
- Appropriate use of IProxy objects
- And other pinjected coding guidelines

If any violations are found, the commit is rejected and detailed feedback is provided to help fix the issues.

## Changelog

### 0.4.0 (2025-03-13)
- Added comprehensive CLAUDE.md file with code style guidelines and commands
- Fixed Python version compatibility to ">= 3.10" (was 3.12)
- Updated documentation with correct pinjected import statements
- Improved developer experience with detailed style guides

### 0.3.0 (2025-03-11)
- Added pytest plugin integration for code review during tests
- Option to enable/disable plugin with `--no-pinjected-reviewer`
- Option to continue tests despite errors with `--pinjected-continue-on-error`
- Improved project file detection, filtering out libraries and virtual environments
- Comprehensive color-coded reporting in test output

### 0.2.1 (2025-03-11)
- Minor code cleanup
- Updated documentation

### 0.2.0 (2025-03-11)
- Improved command-line interface with better output formatting
- Simplified logging for cleaner output
- Added better error handling for missing resources
- Enhanced file loading for better package distribution
- Fixed package structure for proper installation

### 0.1.0
- Initial release with basic functionality
- Git pre-commit hook support
- Review command for validating staged changes

# TODOs
- [ ] Only review files that are modified from current git HEAD.
- [ ] Show prices consumed
- [ ] Show the reviewing filenames while reviewing.

## License

[Your license information here]