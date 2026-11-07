r"""W3: build the app package dist/Chutku-<version>-win64.zip (no Python, Node or git needed on the user's PC).

    python scripts/build_release.py                    # build (needs internet: python.org, PyPI)
    python scripts/build_release.py --python-zip X     # use a local python-3.13.x-embed-amd64.zip (still hash-checked)
    python scripts/build_release.py --print-python-pin # find the newest 3.13 embeddable zip and print its pin

The package holds:
  python/          the python.org embeddable CPython 3.13 for win-amd64, pinned in models/manifest.json ("python")
  python/Lib/site-packages   requirements.lock installed with --require-hashes --only-binary=:all: for win_amd64
  chutku/          compiled to .pyc next to the sources (compileall -b), no .py; web/, atlases and data files kept
  bin/             agent-desktop and agent-browser win32-x64 exes (their own .sha256 checked when shipped)
  models/          manifest.json and the essential models present at build time (wake word, speaker, embed)
  vendor/          the pinned llama.cpp runtimes, when present at build time
  docs/apps/       the app feature maps (read by apps.howto)
  Chutku.exe       the launcher (installer/launcher.cs), built with the .NET Framework csc.exe on Windows
  LICENSE, THIRD_PARTY_LICENSES.md, NOTICE, version.json, pyproject.toml, requirements.lock

Never included: data/, .env, sandbox/, tests/, scripts/, .git, caches, the PortAudio ASIO DLL variant (W7).
The .pyc files are compiled by this interpreter, so it must be CPython 3.13 like the embedded one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_MINOR = (3, 13)
PACKAGE_EXCLUDE = {"hypothesis", "sortedcontainers"}   # test-only pins in the lock
# Pinned packages PyPI has no wheel for (checked 2026-11-07): pure Python, so their hash-checked sdist is built into
# a py3-none-any wheel here. shortcut: a fixed list; a new sdist-only pin fails the build with pip's message.
SOURCE_ONLY = {"proxy-tools"}
EXCLUDED_FILES = re.compile(r"(?i)(^|/)(libportaudio\w*-asio\.dll|\.env|desktop\.ini)$")
SKIP_PARTS = {"__pycache__", ".git", "data", "sandbox", "tests", ".hypothesis", "node_modules"}
ESSENTIAL_MODELS = ("wake", "speaker", "embed")        # small models every install needs (about 160 MB)
NATIVE = {"agent-desktop": "agent-desktop/bin/agent-desktop-win32-x64.exe",
          "agent-browser": "agent-browser/bin/agent-browser-win32-x64.exe"}
FTP = "https://www.python.org/ftp/python/"


class BuildError(RuntimeError):
    pass


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def version():
    import tomllib
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def manifest():
    return json.loads((ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))


# -- the embedded Python ------------------------------------------------------------------------------------------

def newest_embed(opener=urllib.request.urlopen):
    """(version, url) of the newest python-3.13.N-embed-amd64.zip on python.org."""
    with opener(FTP, timeout=30) as response:
        listing = response.read().decode("utf-8", "replace")
    versions = sorted({tuple(map(int, v.split("."))) for v in re.findall(r'href="(3\.13\.\d+)/"', listing)},
                      reverse=True)
    for parts in versions:
        name = ".".join(map(str, parts))
        url = f"{FTP}{name}/python-{name}-embed-amd64.zip"
        try:
            with opener(urllib.request.Request(url, method="HEAD"), timeout=30):
                return name, url
        except OSError:
            continue   # a pre-release folder without an embeddable build
    raise BuildError("No CPython 3.13 embeddable zip found on python.org.")


def download(url, target, expected=None):
    """Download to `target`; refuse (and delete) a file whose SHA-256 is not `expected`."""
    with urllib.request.urlopen(url, timeout=120) as response, open(target, "wb") as stream:
        shutil.copyfileobj(response, stream)
    if expected and sha256(target) != expected:
        Path(target).unlink(missing_ok=True)
        raise BuildError(f"{url} does not match its pinned SHA-256; refused.")
    return target


def python_zip(work, local=None):
    pin = manifest().get("python")
    if not isinstance(pin, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256", ""))):
        raise BuildError("models/manifest.json has no pinned 'python' entry; run --print-python-pin and add it.")
    if local:
        if sha256(local) != pin["sha256"]:
            raise BuildError(f"{local} does not match the pinned SHA-256 of {pin['version']}; refused.")
        return Path(local), pin
    return download(pin["source"], Path(work) / Path(pin["source"]).name, pin["sha256"]), pin


def install_python(stage, archive, pin):
    target = stage / "python"
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    pth = next(target.glob("python3*._pth"), None)
    if pth is None:
        raise BuildError("The embeddable zip has no ._pth file.")
    stem = pth.stem   # python313
    # The app folder (..) holds chutku/; site-packages next to the stdlib; `import site` runs .pth files.
    pth.write_text(f"{stem}.zip\n.\nLib\\site-packages\n..\nimport site\n", encoding="utf-8")
    return target


def _pins(names=None, exclude=()):
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    logical = re.sub(r"\\\r?\n\s*", " ", text).splitlines()
    return [line for line in logical if line.strip() and not line.lstrip().startswith("#")
            and (names is None or line.split("==")[0].strip().casefold() in names)
            and line.split("==")[0].strip().casefold() not in exclude]


def lock_without_test_pins(work, *, source_only=False):
    """The lock for the package: test-only pins out; the binary lock or (source_only) the sdist-only pins."""
    if source_only:
        kept, name = _pins(SOURCE_ONLY), "source.lock"
    else:
        kept, name = _pins(exclude=PACKAGE_EXCLUDE | SOURCE_ONLY), "package.lock"
    path = Path(work) / name
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return path


def install_packages(stage, work):
    target = stage / "python" / "Lib" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--require-hashes",
               "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.13", "--implementation", "cp",
               "--abi", "cp313", "--no-deps", "--target", str(target), "-r", str(lock_without_test_pins(work))]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError("pip could not install the locked packages:\n" + done.stderr[-3000:])
    install_source_only(target, work)
    for path in list(target.rglob("*")):   # e.g. PortAudio's ASIO builds (licence: not shipped, W7)
        if path.is_file() and EXCLUDED_FILES.search(path.relative_to(target).as_posix()):
            path.unlink()
    shutil.rmtree(target / "bin", ignore_errors=True)   # console-script launchers point at the build machine
    # Hash-checked .pyc that are never re-validated: unzipping resets mtimes, and the app folder must never be
    # written at run time (W2/W3), so Python must not need to rewrite them.
    # Not fatal: some wheels ship files that never compile (test fixtures, other Python versions); the launcher
    # sets PYTHONDONTWRITEBYTECODE, so those are simply read from source.
    subprocess.run([sys.executable, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
                    str(target)], capture_output=True, text=True)
    return target


def install_source_only(target, work):
    """SOURCE_ONLY pins: download the sdist (its hash checked by --require-hashes), build a wheel, install it."""
    sdists, wheels = Path(work) / "sdists", Path(work) / "wheels"
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check", "--no-input"]
    done = subprocess.run(pip + ["download", "--require-hashes", "--no-deps", "--no-binary=:all:", "-d", str(sdists),
                                 "-r", str(lock_without_test_pins(work, source_only=True))], capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError("pip could not fetch the source-only packages:\n" + done.stderr[-3000:])
    for archive in sorted(sdists.iterdir()):
        done = subprocess.run(pip + ["wheel", "--no-deps", "--use-pep517", "-w", str(wheels), str(archive)],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise BuildError(f"{archive.name} did not build:\n" + done.stderr[-3000:])
    built = sorted(wheels.glob("*.whl"))
    if any(not w.name.endswith("-py3-none-any.whl") and "-py2.py3-none-any" not in w.name for w in built):
        raise BuildError("A source-only package built a platform wheel; it cannot be cross-built for Windows.")
    done = subprocess.run(pip + ["install", "--no-deps", "--no-index", "--target", str(target), *map(str, built)],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError("The built wheels did not install:\n" + done.stderr[-3000:])


# -- Chutku itself ---------------------------------------------------------------------------------------------------

def _copy_tree(source, target):
    for path in sorted(Path(source).rglob("*")):
        relative = path.relative_to(source)
        if any(part in SKIP_PARTS for part in relative.parts) or path.is_dir():
            continue
        if EXCLUDED_FILES.search(relative.as_posix()):
            continue
        destination = Path(target) / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def compile_chutku(stage):
    """chutku/ as .pyc files only (compileall -b writes x.pyc next to x.py; the .py is then removed)."""
    if sys.version_info[:2] != PYTHON_MINOR:
        raise BuildError(f"Build with CPython {PYTHON_MINOR[0]}.{PYTHON_MINOR[1]}: the .pyc must match the embedded "
                         f"Python (this is {sys.version.split()[0]}).")
    target = stage / "chutku"
    _copy_tree(ROOT / "chutku", target)
    done = subprocess.run([sys.executable, "-m", "compileall", "-q", "-b", "-j", "0", str(target)],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError("compileall failed:\n" + (done.stdout + done.stderr)[-3000:])
    for source in target.rglob("*.py"):
        if not source.with_suffix(".pyc").is_file():
            raise BuildError(f"{source} was not compiled.")
        source.unlink()
    return target


def copy_bundles(stage, tools=None):
    notes = []
    (stage / "models").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "models" / "manifest.json", stage / "models" / "manifest.json")
    for name in ESSENTIAL_MODELS:
        if (ROOT / "models" / name).is_dir():
            _copy_tree(ROOT / "models" / name, stage / "models" / name)
        else:
            notes.append(f"essential model folder models/{name} was not present at build time")
    if (ROOT / "vendor").is_dir():
        _copy_tree(ROOT / "vendor", stage / "vendor")
    else:
        notes.append("vendor/ (llama.cpp runtimes) was not present: the offline brain needs it")
    _copy_tree(ROOT / "docs" / "apps", stage / "docs" / "apps")
    for name in ("LICENSE", "THIRD_PARTY_LICENSES.md", "pyproject.toml", "requirements.lock"):
        shutil.copy2(ROOT / name, stage / name)
    modules = Path(tools or ROOT / "tools" / "node_modules")
    (stage / "bin").mkdir(exist_ok=True)
    for name, relative in NATIVE.items():
        source = modules / relative
        if not source.is_file():
            raise BuildError(f"{source} is missing: run `npm ci --prefix tools` first.")
        pinned = source.with_name(source.name + ".sha256")
        if pinned.is_file() and pinned.read_text().split()[0].lower() != sha256(source):
            raise BuildError(f"{source.name} does not match its own .sha256; refused.")
        shutil.copy2(source, stage / "bin" / source.name)
    return notes


def build_launcher(stage, ver):
    """Chutku.exe from installer/launcher.cs with the csc.exe that ships with Windows (.NET Framework 4)."""
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    csc = Path(windir or "C:/Windows") / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not csc.is_file():
        return f"Chutku.exe not built: {csc} is missing (build on Windows)"
    sys.path.insert(0, str(ROOT))
    from chutku.icon import icon_bytes
    with tempfile.TemporaryDirectory() as temp:
        icon = Path(temp) / "chutku.ico"
        icon.write_bytes(icon_bytes())
        source = Path(temp) / "launcher.cs"
        numeric = ".".join((re.findall(r"\d+", ver) + ["0", "0", "0", "0"])[:4])
        source.write_text((ROOT / "installer" / "launcher.cs").read_text(encoding="utf-8")
                          .replace("0.0.0.0", numeric), encoding="utf-8")
        done = subprocess.run([str(csc), "/nologo", "/target:winexe", "/optimize+", f"/win32icon:{icon}",
                               f"/out:{stage / 'Chutku.exe'}", str(source)], capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError("csc failed:\n" + (done.stdout + done.stderr)[-3000:])
    return None


def notice(stage):
    (stage / "NOTICE").write_text(
        "Chutku, MIT licence (LICENSE). It bundles third-party software and models under their own licences, listed in "
        "THIRD_PARTY_LICENSES.md, among them:\n"
        "- CPython (PSF License), and the Python packages in python/Lib/site-packages (each package's licence is in "
        "its *.dist-info folder).\n"
        "- openWakeWord models: CC BY-NC-SA 4.0 (non-commercial, attribution).\n"
        "- espeak-ng (through espeakng-loader): GPL-3.0-or-later. Source: https://github.com/espeak-ng/espeak-ng\n"
        "- agent-desktop and agent-browser (MIT), llama.cpp (MIT).\n"
        "The PortAudio ASIO variant is not included.\n", encoding="utf-8")


# -- checks and the zip ----------------------------------------------------------------------------------------------

FORBIDDEN = re.compile(r"(?i)(^|/)(data|sandbox|tests|\.git)(/|$)|(^|/)\.env$|\.py$")


def check_stage(stage):
    """Nothing personal or source-only in the package (W8 runs the content scan on the zip as well)."""
    bad = [p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()
           and FORBIDDEN.search(p.relative_to(stage).as_posix())
           and not p.relative_to(stage).as_posix().startswith("python/")]   # python/ ships its own stdlib layout
    bad += [p.relative_to(stage).as_posix() for p in stage.rglob("*-asio.dll")]   # anywhere, python/ included
    if bad:
        raise BuildError("These must not be in the package: " + ", ".join(bad[:10]))


def make_zip(stage, out, ver):
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"Chutku-{ver}-win64.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(stage).as_posix())
    return target


def build(out, *, python_local=None, ver=None):
    ver = ver or version()
    with tempfile.TemporaryDirectory() as work:
        stage = Path(work) / "Chutku"
        stage.mkdir()
        archive, pin = python_zip(work, python_local)
        install_python(stage, archive, pin)
        install_packages(stage, work)
        compile_chutku(stage)
        notes = copy_bundles(stage)
        launcher = build_launcher(stage, ver)
        if launcher:
            notes.append(launcher)
        notice(stage)
        (stage / "version.json").write_text(json.dumps({"version": ver, "python": pin["version"], "notes": notes},
                                                       indent=1), encoding="utf-8")
        check_stage(stage)
        target = make_zip(stage, Path(out), ver)
    digest = sha256(target)
    (target.parent / (target.name + ".sha256")).write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return {"zip": str(target), "sha256": digest, "size": target.stat().st_size, "version": ver, "notes": notes}


RELEASES = "https://github.com/sidvashisth2005/Chutku-releases/releases/download"


def latest_json(zip_path, tag):
    """dist/latest.json for the setup: {version, url, sha256, size} of the package published under `tag`."""
    zip_path = Path(zip_path)
    info = {"version": tag.removeprefix("v"), "url": f"{RELEASES}/{tag}/{zip_path.name}", "sha256": sha256(zip_path),
            "size": zip_path.stat().st_size}
    (zip_path.parent / "latest.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--python-zip", help="a local embeddable zip (checked against the pin)")
    parser.add_argument("--version", help="override pyproject's version")
    parser.add_argument("--print-python-pin", action="store_true", help="print the newest 3.13 embeddable pin")
    parser.add_argument("--latest-json", nargs=2, metavar=("ZIP", "TAG"), help="write latest.json next to ZIP")
    args = parser.parse_args(argv)
    try:
        if args.latest_json:
            print(json.dumps(latest_json(*args.latest_json), indent=1))
            return 0
        if args.print_python_pin:
            name, url = newest_embed()
            with tempfile.TemporaryDirectory() as temp:
                file = download(url, Path(temp) / Path(url).name)
                print(json.dumps({"python": {"version": name, "source": url, "sha256": sha256(file),
                                             "license": "PSF-2.0"}}, indent=1))
            return 0
        print(json.dumps(build(args.out, python_local=args.python_zip, ver=args.version), indent=1))
        return 0
    except (BuildError, OSError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
