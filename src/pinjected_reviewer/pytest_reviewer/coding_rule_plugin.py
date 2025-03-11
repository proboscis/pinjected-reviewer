import asyncio
from pathlib import Path

import pytest

from pinjected_reviewer.pytest_reviewer.coding_rule_plugin_impl import Diagnostic


def pytest_addoption(parser):
    group = parser.getgroup("pinjected-reviewer")
    group.addoption(
        "--pinjected-reviewer",
        action="store_true",
        dest="pinjected_reviewer",
        default=True,
        help="Enable pinjected code style review (enabled by default)",
    )
    group.addoption(
        "--no-pinjected-reviewer",
        action="store_false",
        dest="pinjected_reviewer",
        help="Disable pinjected code style review",
    )
    group.addoption(
        "--pinjected-continue-on-error",
        action="store_true",
        dest="pinjected_continue_on_error",
        default=False,
        help="Continue test execution even if pinjected code review finds errors",
    )


async def run_review_for_pytest(session: pytest.Session):
    from pinjected_reviewer.pytest_reviewer.coding_rule_plugin_impl import a_pytest_plugin_impl
    from pinjected import design
    from pinjected import AsyncResolver
    from pinjected.helper_structure import MetaContext
    from loguru import logger
    
    mc = await MetaContext.a_gather_from_path(Path(__file__))
    d = await mc.a_final_design + design(
        pytest_session=session
    )
    resolver = AsyncResolver(d)
    diagnostics: list[Diagnostic] = await resolver.provide(a_pytest_plugin_impl())
    
    # Store diagnostics for reporting at the end
    session.config.pinjected_diagnostics = diagnostics
    
    # Fail the session if there are error-level diagnostics
    has_errors = any(d.level == 'error' for d in diagnostics)
    
    if has_errors and not session.config.getoption("pinjected_continue_on_error"):
        # Register hook to add errors as failed tests
        error_count = len([d for d in diagnostics if d.level == 'error'])
        session.shouldfail = f"pinjected-reviewer found {error_count} errors"
        
        for diagnostic in [d for d in diagnostics if d.level == 'error']:
            file_path = str(diagnostic.file.relative_to(session.config.rootpath))
            line_info = f":{diagnostic.line}" if diagnostic.line else ""
            
            # Log the error
            logger.error(f"{file_path}{line_info} - {diagnostic.name}: {diagnostic.message}")


def pytest_sessionstart(session: pytest.Session):
    if session.config.getoption("pinjected_reviewer"):
        asyncio.run(run_review_for_pytest(session))
    else:
        # We'll handle this in the terminal summary hook
        pass


def pytest_terminal_summary(terminalreporter):
    """Report pinjected diagnostics in the terminal summary."""
    config = terminalreporter.config
    
    if not config.getoption("pinjected_reviewer"):
        terminalreporter.write_line("pinjected-reviewer: Disabled by --no-pinjected-reviewer option")
        return
        
    if not hasattr(config, 'pinjected_diagnostics') or not config.pinjected_diagnostics:
        terminalreporter.write_line("pinjected-reviewer: No issues found")
        return
    
    diagnostics = config.pinjected_diagnostics
    
    # Count by level
    counts = {
        'error': len([d for d in diagnostics if d.level == 'error']),
        'warning': len([d for d in diagnostics if d.level == 'warning']),
        'suggest': len([d for d in diagnostics if d.level == 'suggest']),
        'approve': len([d for d in diagnostics if d.level == 'approve']),
    }
    
    # Report header
    terminalreporter.section("Pinjected Code Review Results")
    
    # Report counts
    terminalreporter.write_line(f"Found {len(diagnostics)} issues:")
    if counts['error'] > 0:
        terminalreporter.write_line(f"  Errors: {counts['error']}", red=True)
    if counts['warning'] > 0:
        terminalreporter.write_line(f"  Warnings: {counts['warning']}", yellow=True)
    if counts['suggest'] > 0:
        terminalreporter.write_line(f"  Suggestions: {counts['suggest']}", cyan=True)
    if counts['approve'] > 0:
        terminalreporter.write_line(f"  Approvals: {counts['approve']}", green=True)
    
    # List all issues
    terminalreporter.write_line("\nDetailed issues:")
    for diagnostic in diagnostics:
        file_path = str(diagnostic.file.relative_to(config.rootpath))
        line_info = f":{diagnostic.line}" if diagnostic.line else ""
        location = f"{file_path}{line_info}"
        
        if diagnostic.level == 'error':
            terminalreporter.write_line(f"ERROR: {location} - {diagnostic.name}", red=True)
        elif diagnostic.level == 'warning':
            terminalreporter.write_line(f"WARNING: {location} - {diagnostic.name}", yellow=True)
        elif diagnostic.level == 'suggest':
            terminalreporter.write_line(f"SUGGESTION: {location} - {diagnostic.name}", cyan=True)
        elif diagnostic.level == 'approve':
            terminalreporter.write_line(f"APPROVED: {location} - {diagnostic.name}", green=True)
        
        # Add message with proper indentation
        message_lines = diagnostic.message.strip().split('\n')
        for line in message_lines:
            terminalreporter.write_line(f"    {line}")