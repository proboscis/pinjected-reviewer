import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable, List, Optional, Tuple, Dict

import loguru
from injected_utils import lzma_sqlite, async_cached
from loguru import logger
from pinjected import *
from pinjected.helper_structure import MetaContext
from pinjected_openai.openrouter.instances import StructuredLLM
from pinjected_openai.openrouter.util import a_openrouter_chat_completion, a_openrouter_chat_completion__without_fix
from pydantic import BaseModel
from tqdm import tqdm

# a_openrouter_chat_completion()

GatherGitDiff = Callable[[], Awaitable[str]]


@dataclass
class FileDiff:
    """
    Information about a specific file diff in the git repository.
    """
    filename: Path
    diff: str
    is_binary: bool = False
    is_new_file: bool = False
    is_deleted: bool = False


@dataclass
class GitInfo:
    """
    Structured representation of git repository information.
    """
    # Current state
    branch: str
    staged_files: List[Path]
    modified_files: List[Path]
    untracked_files: List[Path]

    # Diff content
    diff: str

    # Per-file diffs for staged files
    file_diffs: Dict[Path, FileDiff] = field(default_factory=dict)

    # Repository info
    repo_root: Optional[Path] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None

    @property
    def has_staged_changes(self) -> bool:
        return len(self.staged_files) > 0

    @property
    def has_unstaged_changes(self) -> bool:
        return len(self.modified_files) > 0

    @property
    def has_untracked_files(self) -> bool:
        return len(self.untracked_files) > 0

    @property
    def has_python_changes(self) -> bool:
        return any(f.name.endswith('.py') for f in self.staged_files + self.modified_files)

    @property
    def python_diffs(self) -> Dict[Path, FileDiff]:
        return {k: v for k, v in self.file_diffs.items() if k.name.endswith('.py')}


@dataclass
class Review:
    name: str
    review_text: str
    approved: bool


class Approved(BaseModel):
    result: bool


@injected
async def a_extract_approved(
        a_sllm_for_approval_extraction: StructuredLLM,
        /,
        text: str
) -> Approved:
    prompt = f"""
Please read the following text and extract if the answer of a text is `approved` or `not approved`.
{text}

The answer must be true if it is approved and false if it is not approved.
"""
    return await a_sllm_for_approval_extraction(prompt, response_format=Approved)


@injected
async def a_review_python_diff(
        a_sllm_for_commit_review: StructuredLLM,
        a_extract_approved: Callable[[str], Awaitable[Approved]],
        /,
        diff: FileDiff
):
    assert diff.filename.name.endswith('.py'), "Not a Python file"
    guide_path = Path(__file__).parent.parent / 'review_materials' / 'how_to_use_pinjected.md'
    guide = guide_path.read_text()
    prompt = f"""
Read the following guide to understand how to use Pinjected in your code:
{guide}
Now, please review the following Python code changes.
The review must point out any violations of the guide, with clear reasons with examples.
If any violations are found, you must not approve the changes.
Even tiny violation like missing prefix in naming conventions are not allowed.
However, missing space or adding space can be ignored if it is not a violation of the guide.
Beware @injcted functions must not be directly called unless it is trying to make IProxy object.
@injected function must be requested as a dependency in @instance/@injected function to have dependency resolved.
```diff
{diff.diff}
```
The review must include the final approval status as `approved` or `rejected`.
Example:
Final approval status: approved
"""
    resp: str = await a_sllm_for_commit_review(prompt)
    approved = await a_extract_approved(resp)
    return Review(name=f"Pinjected Coding Style for {diff.filename}", review_text=resp, approved=approved.result)


@instance
async def review_diff__pinjected_code_style(
        a_review_python_diff: Callable[[FileDiff], Awaitable[Review]],
        git_info: GitInfo
) -> Review:
    """
    Reviews staged git changes and provides code style feedback.
    
    Args:
        git_info: Injected GitInfo object containing repository information
    
    Returns:
        Review object with feedback and approval status
    """
    # Check if there are staged changes
    if not git_info.has_staged_changes:
        logger.info("No staged changes to review.")
        return Review(
            name="Code Style",
            review_text="No staged changes to review.",
            approved=True
        )

    # Check if there's diff content
    if not git_info.diff:
        logger.info("No diff content in staged changes.")
        return Review(
            name="Code Style",
            review_text="No diff content in staged changes.",
            approved=True
        )

    logger.info(f"Found {len(git_info.staged_files)} staged files. Reviewing diff...")
    if git_info.has_python_changes:
        python_diffs = git_info.python_diffs
        bar = tqdm(desc="Reviewing Python changes", total=len(python_diffs))

        async def task(diff):
            res = await a_review_python_diff(diff)
            bar.update(1)
            return res

        tasks = [task(diff) for diff in python_diffs.values()]
        reviews = await asyncio.gather(*tasks)
        bar.close()
        approved = all(r.approved for r in reviews)
        rejected_reviews = [r for r in reviews if not r.approved]
        if not approved:
            logger.warning("Code style violations found in Python changes.")
            review_text = ""
            for r in rejected_reviews:
                review_text += f"{r.name}:\n{r.review_text}\n"
        else:
            review_text = "No code style violations found in Python changes."
        return Review(name="Pinjected Coding Style", review_text=review_text, approved=approved)
    else:
        logger.info("No Python changes found in staged files.")
        return Review(
            name="Pinjected Coding Style",
            review_text="No Python changes found in staged files.",
            approved=True
        )


@injected
async def a_system(command: str, *args) -> Tuple[str, str]:
    """
    Generic function to execute system commands asynchronously.
    
    Args:
        command: The command to execute
        *args: Additional arguments for the command
    
    Returns:
        A tuple of (stdout, stderr) as strings
        
    Raises:
        RuntimeError: If the command fails (non-zero return code)
        Exception: Any other exceptions that occur during execution
    """
    cmd = [command]
    if args:
        cmd.extend(args)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    stderr_str = stderr.decode().strip()
    stdout_str = stdout.decode().strip()

    if process.returncode != 0:
        error_msg = f"Command {command} failed with code {process.returncode}: {stderr_str}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    return stdout_str, stderr_str


@instance
async def git_info(a_system) -> GitInfo:
    """
    Provides a GitInfo instance with comprehensive git repository information.
    Using @instance because it returns a value (not a function).
    
    Args:
        a_system: System command execution function
    
    Returns:
        A GitInfo object with repository details, file status, and diff content.
        
    Raises:
        RuntimeError: If a critical git command fails
    """
    # Get repository info
    try:
        stdout, _ = await a_system("git", "rev-parse", "--show-toplevel")
        repo_root = Path(stdout)
    except RuntimeError as e:
        logger.warning(f"Failed to get repository root: {e}")
        # This is critical - we need to know we're in a git repo
        raise RuntimeError("Not in a git repository or git not installed") from e

    # Get current branch
    try:
        stdout, _ = await a_system("git", "rev-parse", "--abbrev-ref", "HEAD")
        branch = stdout
    except RuntimeError as e:
        logger.warning(f"Failed to get current branch: {e}")
        branch = "unknown"

    # Get author info - not critical, can proceed without it
    try:
        stdout, _ = await a_system("git", "config", "user.name")
        author_name = stdout
    except RuntimeError:
        logger.info("Failed to get git user name")
        author_name = None

    try:
        stdout, _ = await a_system("git", "config", "user.email")
        author_email = stdout
    except RuntimeError:
        logger.info("Failed to get git user email")
        author_email = None

    # Get staged files - critical for our purpose
    try:
        stdout, _ = await a_system("git", "diff", "--name-only", "--staged")
        staged_files = [Path(f) for f in stdout.split('\n') if f] if stdout else []
    except RuntimeError as e:
        logger.error(f"Failed to get staged files: {e}")
        raise RuntimeError("Cannot get staged files information") from e

    # Get modified but unstaged files
    try:
        stdout, _ = await a_system("git", "diff", "--name-only")
        modified_files = [Path(f) for f in stdout.split('\n') if f] if stdout else []
    except RuntimeError as e:
        logger.warning(f"Failed to get modified files: {e}")
        modified_files = []

    # Get untracked files
    try:
        stdout, _ = await a_system("git", "ls-files", "--others", "--exclude-standard")
        untracked_files = [Path(f) for f in stdout.split('\n') if f] if stdout else []
    except RuntimeError as e:
        logger.warning(f"Failed to get untracked files: {e}")
        untracked_files = []

    # Get diff content - critical for our purpose
    try:
        stdout, _ = await a_system("git", "diff", "--staged")
        diff = stdout
    except RuntimeError as e:
        logger.error(f"Failed to get diff content: {e}")
        raise RuntimeError("Cannot get diff content") from e

    # Create file_diffs dictionary with per-file diffs
    file_diffs = {}
    for file_path in staged_files:
        try:
            # Check file type
            file_type_output, _ = await a_system("git", "diff", "--staged", "--name-status", "--", str(file_path))
            if file_type_output:
                file_type = file_type_output.split()[0]
                is_new_file = file_type == 'A'
                is_deleted = file_type == 'D'
            else:
                is_new_file = False
                is_deleted = False

            # Get file diff
            file_diff, _ = await a_system("git", "diff", "--staged", "--", str(file_path))

            # Check if it's a binary file
            is_binary = "Binary files" in file_diff

            file_diffs[file_path] = FileDiff(
                filename=file_path,
                diff=file_diff,
                is_binary=is_binary,
                is_new_file=is_new_file,
                is_deleted=is_deleted
            )
        except Exception as e:
            logger.warning(f"Failed to get diff for {file_path}: {e}")
            # Add an empty diff entry
            file_diffs[file_path] = FileDiff(
                filename=file_path,
                diff=f"[Error: {str(e)}]",
                is_binary=False
            )

    return GitInfo(
        branch=branch,
        staged_files=staged_files,
        modified_files=modified_files,
        untracked_files=untracked_files,
        diff=diff,
        file_diffs=file_diffs,
        repo_root=repo_root,
        author_name=author_name,
        author_email=author_email
    )


test_git_info: IProxy = git_info
check_git_info_py: IProxy = git_info.python_diffs
test_review: IProxy = review_diff__pinjected_code_style


@injected
async def a_git_diff(a_system) -> str:
    """
    Gathers the current git diff for staged files.
    
    Args:
        a_system: System command execution function
    
    Returns:
        A string containing the git diff output for staged changes.
        
    Raises:
        RuntimeError: If the git command fails
    """
    stdout, _ = await a_system("git", "diff", "--staged")

    # If no staged changes, return empty string
    if not stdout.strip():
        return ""

    return stdout


@injected
async def a_test_function():
    a_review_python_diff(FileDiff(Path("test.py"), "def test():\n    pass\n"))


__meta_design__ = design(
    overrides=design(
        a_sllm_for_commit_review=async_cached(
            lzma_sqlite(injected('cache_root_path') / 'a_sllm_for_commit_review.sqlite'))(
            Injected.partial(
                a_openrouter_chat_completion,
                model="anthropic/claude-3.7-sonnet:thinking"
            )
        ),
        a_sllm_for_approval_extraction=async_cached(
            lzma_sqlite(injected('cache_root_path') / 'a_sllm_for_approval_extraction.sqlite'))(
            Injected.partial(
                a_openrouter_chat_completion,
                model="google/gemini-2.0-flash-001",
            )
        ),
        a_structured_llm_for_json_fix=async_cached(
            lzma_sqlite(injected('cache_root_path') / 'a_structured_llm_for_json_fix.sqlite'))(
            Injected.partial(
                a_openrouter_chat_completion__without_fix,
                model="openai/gpt-4o-mini"
            )
        ),
        a_llm_for_json_schema_example=async_cached(
            lzma_sqlite(injected('cache_root_path') / 'a_llm_for_json_schema_example.sqlite'))(
            Injected.partial(
                a_openrouter_chat_completion__without_fix,
                model="openai/gpt-4o",
            )
        ),
        cache_root_path=Path("~/.cache/pinjected_reviewer").expanduser(),
        logger=loguru.logger
    )
)

