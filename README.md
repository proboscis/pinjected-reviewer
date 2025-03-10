# Pinjected Reviewer

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

### Manual Code Review

You can also manually run the code review without committing:

```bash
rye run python -m pinjected_reviewer review
```

### Uninstalling the Hook

To remove the pre-commit hook:

```bash
rye run python -m pinjected_reviewer uninstall
```

## How it Works

The reviewer checks all staged Python files for pinjected coding style compliance, including:

- Proper use of `@injected` and `@instance` decorators
- Correct dependency injection patterns
- Proper function structure and argument handling
- Appropriate use of IProxy objects
- And other pinjected coding guidelines

If any violations are found, the commit is rejected and detailed feedback is provided to help fix the issues.

## License

[Your license information here]