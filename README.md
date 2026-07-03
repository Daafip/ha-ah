# Python package template [UV]

> [!WARNING]
> This is still a work in progress, some documentation on how to use uv might be missing.

[UV](https://docs.astral.sh/uv/) is a package which is a replacement for `pip` in package managing for python. [Pixi](https://pixi.prefix.dev/latest/) manages packages broarder sence and thus replaces `conda`. The alternative python package template for pixi can be found at [HKV-products-services/python_package_template](https://github.com/HKV-products-services/python_package_template). Depending on your needs one is more suited than the other.

This template package contains core functionality for a python package, developed to showcase and speed up the process of developing a python package. This Python package template is developed by HKV, though based heavily on other open source projects and is published under the GNU GPL-3 license.

## Configuring the template (remove before publishing)

### Naming

The current package name is `python_package_template` and `# Python package template`, if you search for this in your IDE (e.g. VS Code) you can replace these with your given name.

### Pre-commit

This repo has an example pre-commit configuration in `.pre-commit-config.yaml`.
Depending on your needs you might want to uncomment certain sections.
Let us know by making an issue if we missed a useful pre-commit.
Use `pre-commit install --hook-type pre-commit --hook-type pre-push` to automatically run pre-commit.
To run, use `uv run pre-commit run --all-files`

### GitHub Tests

In the folder `.github` there are four workflows which run automatically.
You will need to adjust these depending on your needs.
To run use: `uv run pytest`.

### uv

Read bellow for more information on uv and a quick guideline you can include in your project.

## Getting started

### Using install (in future)

run `pip install Python_package_template`

### developing with uv

To manage the environment we use uv.

<details>
<summary>windows</summary>

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | more"
```

</details>

<details>
<summary>Linux/Mac</summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | less
```

</details>

#### installing

With the `uv` command in powershell install the python environment:

```bash
 cd ../python_package_template
 uv sync --locked
```

The `uv.lock` file loads the correct packages and downloads to the `.venv` file, you can use this environment in developing and resting.

For questions about how to use this package contact `dupuits@hkv.nl` or `haasnoot@hkv.nl`.
