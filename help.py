import subprocess
import os

uid = os.getuid()

subprocess.run([
    "dbus-send", "--system", "--print-reply",
    "--dest=org.freedesktop.Accounts",
    f"/org/freedesktop/Accounts/User{uid}",
    "org.freedesktop.Accounts.User.SetSession",
    "string:gnome"
])

subprocess.run(["gnome-session-quit", "--logout", "--no-prompt"])
