# HUD Server Tests

This directory contains test suites for the HUD Server component.

## Running Tests

All tests should be executed from the project root directory (`wingman-ai/`) using the module syntax.

### Quick Integration Test

To run a quick connectivity and basic functionality check:

```bash
python -m hud_server.tests.run_tests
```

### Running Specific Test Suites

You can run specific functional test suites using command line arguments:

```bash
# Run all test suites
python -m hud_server.tests.run_tests --all

# Run message overlay tests
python -m hud_server.tests.run_tests --messages

# Run progress bar tests
python -m hud_server.tests.run_tests --progress

# Run persistent info display tests
python -m hud_server.tests.run_tests --persistent

# Run chat window tests
python -m hud_server.tests.run_tests --chat

# Run layout manager unit tests (no server needed)
python -m hud_server.tests.run_tests --layout

# Run visual layout tests with actual HUD windows
python -m hud_server.tests.run_tests --layout-visual
```

## detailed Test Files

- `run_tests.py`: Main entry point and test runner utility.
- `test_runner.py`: Contains `TestContext` manager for handling test sessions.
- `test_messages.py`: Tests for transient overlay messages (titles, content).
- `test_progress.py`: Tests for progress bar creation, updates, and removal.
- `test_persistent.py`: Tests for persistent info boxes (key-value pairs).
- `test_chat.py`: Tests for chat window visibility and content updates.
- `test_session.py`: Tests for session management (connection/disconnection).
- `test_multiuser.py`: Tests for handling multiple client connections.
- `test_layout.py`: Unit tests for the layout manager (automatic stacking and collision prevention).
- `test_layout_visual.py`: Visual integration tests that display actual HUD windows to verify layout.
