"""Check a clean editable or wheel installation without credentials or YouTube."""
import argparse
import os
import shutil
import subprocess
import tempfile
import venv
import zipfile
from pathlib import Path


def run(*args, cwd, env):
    subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("editable", "wheel"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix=f"playlist-install-{args.kind}-"))
    print(f"Installation check scratch directory: {scratch}", flush=True)
    project = scratch / "project"
    project.mkdir()
    # Copy only public build inputs; never copy local credentials, state or notes.
    for filename in ("pyproject.toml", "README.md", "LICENSE", "MANIFEST.in"):
        shutil.copy2(root / filename, project / filename)
    shutil.copytree(root / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    environment = scratch / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python"
    executable = environment / "bin/youtube-playlist-updater"
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.kind == "editable":
        run(python, "-m", "pip", "install", "-e", project, cwd=scratch, env=env)
    else:
        wheels = scratch / "wheels"
        run(python, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", wheels, project, cwd=scratch, env=env)
        wheel = next(wheels.glob("youtube_playlist_updater-*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            assert not any("config.toml" in name or "README.local" in name or name.startswith(("credentials/", "data/", ".local/")) for name in archive.namelist())
            policy_files = {name.rsplit("/", 1)[-1] for name in archive.namelist() if "/policies/" in name and name.endswith(".py")}
            assert policy_files == {"__init__.py", "duration.py"}
        run(python, "-m", "pip", "install", wheel, cwd=scratch, env=env)
    elsewhere = scratch / "elsewhere"
    elsewhere.mkdir()
    external = scratch / "external"
    external.mkdir()
    config = external / "config.toml"
    shutil.copy2(root / "config.example.toml", config)
    before = config.read_bytes()
    run(executable, "--config", config, "--all", "--demo", "--non-interactive", cwd=elsewhere, env=env)
    # The installed entry point must not rely on the checkout or current directory.
    assert config.read_bytes() == before
    assert not (external / "data").exists() and not (external / "credentials").exists()
    assert not (elsewhere / "data").exists()
    run(executable, "--all", "--demo", "--non-interactive", cwd=external, env=env)
    run(python, "-c", "import youtube_playlist_updater; print(youtube_playlist_updater.__file__)", cwd=elsewhere, env=env)
    print(f"Clean {args.kind} installation verified; scratch files retained at {scratch}.")


if __name__ == "__main__":
    main()
