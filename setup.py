from setuptools import setup

APP = ["focus_mode.py"]
DATA_FILES = []
ICON_FILE = "public/icon.icns"
OPTIONS = {
    "argv_emulation": False,
    "iconfile": ICON_FILE,
    "resources": ["public"],
    "plist": {
        "CFBundleName": "Focus Mode",
        "CFBundleDisplayName": "Focus Mode",
        "CFBundleIdentifier": "com.focusmode.menubar",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "NSAppleEventsUsageDescription": "Focus Mode uses browser tab URL checks to monitor YouTube time.",
    },
    "packages": ["rumps", "AppKit", "Foundation", "Quartz", "ApplicationServices"],
}

setup(
    app=APP,
    name="Focus Mode",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
