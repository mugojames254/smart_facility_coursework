# Development Environment Setup Guide

Follow these steps in order. Commands are given for **Windows** (Command Prompt / PowerShell) and **Unix** (macOS / Linux). Run each command in your terminal exactly as shown.

> **Which terminal?**
> - **Windows:** open **Command Prompt** (search "cmd") or **PowerShell** (search "PowerShell"). Both are covered below.
> - **macOS:** open **Terminal** (search with Spotlight, `Cmd + Space`).
> - **Linux:** open your **Terminal** app.

---

## 1. Install VS Code

VS Code is the code editor we will use.

**Download page (all systems):** https://code.visualstudio.com/download

### Windows (command line)
Open **Command Prompt** or **PowerShell** and run:
```powershell
winget install --id Microsoft.VisualStudioCode -e
```

### macOS (command line)
Requires [Homebrew](https://brew.sh). Run:
```bash
brew install --cask visual-studio-code
```

### Linux (command line)
Debian / Ubuntu:
```bash
sudo apt update && sudo apt install -y wget gpg
wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > packages.microsoft.gpg
sudo install -D -o root -g root -m 644 packages.microsoft.gpg /usr/share/keyrings/packages.microsoft.gpg
echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" | sudo tee /etc/apt/sources.list.d/vscode.list
sudo apt update && sudo apt install -y code
```

**Verify:** close and reopen the terminal, then run:
```bash
code --version
```

---

## 2. Install uv (Python package & project manager)

`uv` is a fast tool that manages Python itself, virtual environments, and packages — all in one. Install it first; it will install Python for us in the next step.

### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### macOS / Linux
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Verify:** close and reopen the terminal, then run:
```bash
uv --version
```
> If `uv` is "not recognized" / "command not found", fully close the terminal and open a new one so it picks up the updated PATH.

---

## 3. Install Python (with uv)

We let `uv` install and manage Python. Same command on every system:
```bash
uv python install 3.12
```

**Verify:**
```bash
uv python list
```
You should see `3.12` listed.

---

## 4. Create & Activate a Virtual Environment

A virtual environment keeps each project's packages isolated.

### Create it (all systems)
From inside your project folder:
```bash
uv venv
```
This creates a `.venv` folder.

### Activate it

**Windows — Command Prompt (cmd):**
```cmd
.venv\Scripts\activate.bat
```

**Windows — PowerShell:**
```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

When active, your prompt shows `(.venv)` at the start. To leave the environment later, run `deactivate`.

---

### ⚠️ Windows PowerShell activation error (execution policy)

If, in **PowerShell**, running `.venv\Scripts\Activate.ps1` gives an error like:

```
.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled on this system.
```

PowerShell is blocking the `.ps1` activation script. Fix it **once** by allowing signed local scripts for your user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Type `Y` and press Enter if prompted. Then run the activation command again.

> **Alternative:** if you cannot or prefer not to change the policy, use **Command Prompt (cmd)** instead — `activate.bat` is not affected by this setting.

---

## 5. Install Jupyter Notebook

With the virtual environment **activated** (`(.venv)` visible in your prompt), install the notebook packages:

```bash
uv pip install jupyter ipykernel
```

- `jupyter` — the Jupyter Notebook / JupyterLab app.
- `ipykernel` — lets this virtual environment run as a Jupyter kernel.

### Register this environment as a kernel
So the notebook can find your project's Python:
```bash
python -m ipykernel install --user --name=project-venv --display-name "Python (project-venv)"
```

### Launch the notebook
```bash
jupyter notebook
```
This opens Jupyter in your web browser. Create a new notebook and pick the **Python (project-venv)** kernel.

> **Tip (VS Code):** you can also open a `.ipynb` file directly in VS Code. Install the **Python** and **Jupyter** extensions (Extensions panel, `Ctrl+Shift+X`), then select the `project-venv` kernel in the top-right of the notebook.

---

## Quick Recap (cheat sheet)

```bash
# 1. VS Code    -> installed via winget / brew / apt (see Section 1)
# 2. uv         -> installed via install script (see Section 2)
uv python install 3.12          # 3. Python
uv venv                         # 4. create virtual environment
# activate:
#   cmd         : .venv\Scripts\activate.bat
#   PowerShell  : .venv\Scripts\Activate.ps1
#   mac/linux   : source .venv/bin/activate
uv pip install jupyter ipykernel   # 5. Jupyter
python -m ipykernel install --user --name=project-venv --display-name "Python (project-venv)"
jupyter notebook


Website url: https://mugojames254.github.io/smart_facility_coursework/
```
