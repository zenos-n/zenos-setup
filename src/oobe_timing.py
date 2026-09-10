def reached_wallpaper_switch(position: float, duration: float) -> bool:
    return duration > 0 and position >= duration * 0.5


def destination2_wallpaper(theme: dict, root="/run/current-system/sw") -> str:
    colors = {"blue", "green", "grey", "orange", "pink", "purple", "red", "teal", "yellow"}
    color = theme.get("accent", "purple")
    if color not in colors:
        color = "purple"
    color = "slate" if color == "grey" else color
    dark = theme.get("darkMode", True)
    if not isinstance(dark, bool):
        dark = True
    suffix = " dark" if dark else ""
    return f"{root}/share/backgrounds/destination-2/{color}{suffix}.png"
