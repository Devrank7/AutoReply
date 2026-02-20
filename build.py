"""
Build AutoReply AI into a standalone application.

Usage:
    python build.py

Creates:
    macOS:   dist/AutoReply AI.app  (drag to Applications)
    Windows: dist/AutoReply AI/AutoReply AI.exe  (folder with .exe)

The manager needs to place these files NEXT TO the executable:
    - .env              (API keys — copy from .env.example and fill in)
    - sales_agent_system_prompt.md  (AI instructions — already included)
"""

import subprocess
import sys
import shutil
from pathlib import Path


def main():
    # Check PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Clean previous builds
    for folder in ("build", "dist"):
        if Path(folder).exists():
            print(f"Cleaning {folder}/...")
            shutil.rmtree(folder)

    # Run PyInstaller with spec file
    print("\nBuilding AutoReply AI...\n")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "autoreply.spec", "--clean"],
        check=False,
    )

    if result.returncode != 0:
        print("\nBuild FAILED. Check errors above.")
        sys.exit(1)

    # Copy essential config files to dist
    dist_dir = Path("dist") / "AutoReply AI"
    if not dist_dir.exists():
        # macOS .app bundle — files go inside
        dist_dir = Path("dist")

    for filename in (".env.example", "sales_agent_system_prompt.md"):
        src = Path(filename)
        if src.exists():
            dst = dist_dir / filename
            if not dst.exists():
                shutil.copy2(src, dst)
                print(f"Copied {filename} -> {dst}")

    # Copy .env if it exists
    if Path(".env").exists():
        dst = dist_dir / ".env"
        if not dst.exists():
            shutil.copy2(".env", dst)
            print(f"Copied .env -> {dst}")

    print("\n" + "=" * 50)
    print("BUILD COMPLETE!")
    print("=" * 50)

    import platform
    if platform.system() == "Darwin":
        print(f"\nmacOS: dist/AutoReply AI.app")
        print("  1. Drag to Applications folder")
        print("  2. Make sure .env is configured")
        print("  3. Double-click to launch")
    else:
        print(f"\nWindows: dist/AutoReply AI/AutoReply AI.exe")
        print("  1. Copy the entire 'AutoReply AI' folder wherever you want")
        print("  2. Edit .env file with your API key")
        print("  3. Double-click AutoReply AI.exe to launch")

    print(f"\nHotkeys:")
    if platform.system() == "Darwin":
        print("  Cmd+Option+R    — Quick reply")
        print("  Cmd+Option+E    — Deep scan")
        print("  Cmd+Shift+E     — Client Lookup")
    else:
        print("  Ctrl+Alt+R      — Quick reply")
        print("  Ctrl+Alt+E      — Deep scan")
        print("  Ctrl+Shift+E    — Client Lookup")


if __name__ == "__main__":
    main()
