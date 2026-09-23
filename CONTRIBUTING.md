# Contributing to Wingman AI

Thanks for your interest in contributing! This document explains how to submit changes and report issues.

## Getting Started

1. Fork the repository
2. Create a feature or fix branch from `develop`
3. Make your changes
4. Open a pull request against `develop`

## Pull Request Rules

- **Link an issue if there is one.** Reference it in the PR description using `Closes #123`, `Fixes #123`, or `Resolves #123`.
- **Target the `develop` branch.** Do not open PRs against `main`.
- **Rebase onto `develop`** before requesting a review. We require linear history — merge commits are not allowed.
- **All commits are squash-merged.** Your PR title and description become the final commit message, so make them clear and descriptive.
- **At least one approving review is required** before a PR can be merged.

## Reporting Bugs

Open an [issue](https://github.com/ShipBit/wingman-ai/issues/new). It helps us most if you include:

- Your Wingman AI version
- Your `Wingman.yaml` configuration file
- Your `settings.yaml` file
- A log file from the session where the bug occurred
- Clear steps to reproduce the issue

> **Never include your `secrets.yaml` file.** It contains API keys and other sensitive credentials.

All of these files can be found in your `%APPDATA%/ShipBit/WingmanAI/` directory on Windows.

## Feature Requests

Open an [issue](https://github.com/ShipBit/wingman-ai/issues/new). Describe what you'd like to see and why it would be useful.

## Major Features

If you're planning to develop a major feature or new integration, please reach out on [Discord](https://www.shipbit.de/discord) first. We want to make sure your work aligns with the project's direction and doesn't overlap with something already in progress.

## Code of Conduct

Be respectful and constructive. We're all here to make Wingman AI better.
