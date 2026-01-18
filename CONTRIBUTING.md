# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## GitHub is used for everything

GitHub is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation.
3. Make sure your code lints (using ruff).
4. Test your contribution.
5. Issue that pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using GitHub's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People _love_ thorough bug reports. I'm not even kidding.

## Use a Consistent Coding Style

Use [ruff](https://github.com/astral-sh/ruff) to make sure the code follows the style.

## Test your code modification

You should verify that existing [tests](./tests) are still working
and you are encouraged to add new ones.
You can run the tests using the following commands from the root folder:

```bash
# Install dependencies using uv
uv sync --dev
# Run tests with coverage
uv run pytest
```

### Code Quality Checks

Every commit must pass the following checks:

- **ruff**: Code linting and formatting
- **pytest**: All tests must pass
- **ty**: Type checking

You can run these checks locally before committing:

```bash
# Check code style and linting
uv run ruff check .

# Auto-fix formatting issues
uv run ruff format .

# Or just check formatting without fixing
uv run ruff format --check .

# Run type checking
uv run ty check custom_components

# Run tests
uv run pytest
```

If any of the tests fail, make the necessary changes as part of
your changes to the integration.

### Home Assistant Validations

As a Home Assistant custom component, pull requests will also be validated using:

- **hassfest**: Home Assistant's manifest and requirements validator
- **HACS**: HACS integration validation for compatibility

These validations run automatically in CI and help ensure the component
meets Home Assistant and HACS standards.

## Versioning

This project uses [Semantic Versioning](https://semver.org/). Version numbers
are managed in `custom_components/mytpu/manifest.json`.

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
