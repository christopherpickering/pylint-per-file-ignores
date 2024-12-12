# Pylint Per File Ignores 😲

This pylint plugin will enable per-file-ignores in your project!

## Install

```
# w/ poetry
poetry add pylint-per-file-ignores --group dev

# w/ pip
pip install pylint-per-file-ignores
```

## Add to Pylint Settings

```toml
[tool.pylint.MASTER]
load-plugins=[
    "pylint_per_file_ignores",
    ...
]
```


## Usage

Add list of patterns and codes you would like to ignore.

### Using native pylint settings

Section "MESSAGES CONTROL". Examples:

```ini
# setup.cfg

[pylint.MESSAGES CONTROL]
per-file-ignores =
  /folder_1/:missing-function-docstring,W0621,W0240,C0115
  file.py:C0116,E0001
```

```toml
# pyproject.toml

[tool.pylint.'messages control']
per-file-ignores = [
    "/folder_1/:missing-function-docstring,W0621,W0240,C0115",
    "file.py:C0116,E0001"
]
```

### Using custom `pyproject.toml` section

For backwards compatibility only. Example:

```toml
[tool.pylint-per-file-ignores]
"/folder_1/"="missing-function-docstring,W0621,W0240,C0115"
"file.py"="C0116,E0001"
```

## Thanks

To pylint :) And the plugin `pylint-django` who produced most of the complex code.

## Contributing

This repo uses commitizen and semantic release. Please commit using `npm run commit` .
