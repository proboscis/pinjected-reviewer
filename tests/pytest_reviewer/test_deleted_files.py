import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pinjected import design, AsyncResolver

from pinjected_reviewer.pytest_reviewer.inspect_code import a_detect_misuse_of_pinjected_proxies
from pinjected_reviewer.pytest_reviewer.coding_rule_plugin_impl import changed_python_files_in_project


class TestDeletedFiles:
    """Tests for handling of deleted files in the code reviewer."""

    @pytest.fixture
    def temp_python_file(self, tmp_path):
        # Create a temporary Python file
        file_path = tmp_path / "temp_file.py"
        file_path.write_text("def test_function():\n    return 'hello'")
        return file_path

    @pytest.mark.asyncio
    async def test_detect_misuse_with_nonexistent_file(self):
        # Create a resolver with necessary dependencies
        nonexistent_path = Path("/non/existent/path.py")
        
        # Create mock dependencies
        mock_ast = MagicMock()
        mock_metadata_getter = MagicMock()
        
        resolver = AsyncResolver(design(
            a_ast=mock_ast,
            a_symbol_metadata_getter=mock_metadata_getter
        ))
        
        # Call the function
        result = await resolver.provide(a_detect_misuse_of_pinjected_proxies(nonexistent_path))
        
        # Verify result
        assert isinstance(result, list)
        assert len(result) == 0
        
        # Verify we never tried to read the file
        mock_ast.assert_not_called()
        mock_metadata_getter.assert_not_called()

    @pytest.mark.asyncio
    async def test_detect_misuse_with_deleted_file(self, temp_python_file):
        # First check that file exists
        assert temp_python_file.exists()
        
        # Create mock dependencies
        mock_ast = MagicMock()
        mock_metadata_getter = MagicMock()
        
        resolver = AsyncResolver(design(
            a_ast=mock_ast,
            a_symbol_metadata_getter=mock_metadata_getter
        ))
        
        # Now delete the file
        os.unlink(temp_python_file)
        
        # Verify file doesn't exist anymore
        assert not temp_python_file.exists()
        
        # Call the function
        result = await resolver.provide(a_detect_misuse_of_pinjected_proxies(temp_python_file))
        
        # Should return an empty list without raising exceptions
        assert isinstance(result, list)
        assert len(result) == 0
        
        # Verify we never tried to read the file
        mock_ast.assert_not_called()
        mock_metadata_getter.assert_not_called()

    @pytest.mark.asyncio
    async def test_changed_python_files_skips_deleted(self):
        # Create a mock GitInfo with a deleted file
        class MockGitInfo:
            def __init__(self):
                self.staged_files = [Path("file1.py"), Path("deleted.py")]
                self.modified_files = [Path("file2.py")]
                self.untracked_files = [Path("file3.py")]
                self.file_diffs = {
                    Path("file1.py"): type("FileDiff", (), {"is_deleted": False}),
                    Path("deleted.py"): type("FileDiff", (), {"is_deleted": True})
                }
        
        # Create a mock logger
        mock_logger = MagicMock()
        
        # Create a mock pytest session
        class MockSession:
            class Config:
                rootpath = "/mock/rootpath"
            config = Config()
        
        # Set up the resolver
        resolver = AsyncResolver(design(
            logger=mock_logger,
            pytest_session=MockSession(),
            git_info=MockGitInfo()
        ))
        
        # Patch Path.exists to return True for all files except deleted.py
        def mock_exists(self):
            return "deleted" not in str(self)
        
        # Patch Path.__lt__ to make set operations work with mocked Path objects
        def mock_lt(self, other):
            return str(self) < str(other)
        
        # Run the test
        with patch('pathlib.Path.exists', mock_exists), \
             patch('pathlib.Path.__lt__', mock_lt):
            
            # Call the function
            result = await resolver.provide(changed_python_files_in_project)
            
            # Verify deleted file is not in the result
            assert isinstance(result, list)
            # We should see files file1.py, file2.py, and file3.py (3 files)
            assert len(result) == 3
            assert all("deleted" not in str(path) for path in result)