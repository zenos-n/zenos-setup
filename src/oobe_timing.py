def reached_wallpaper_switch(position: float, duration: float) -> bool:
    return duration > 0 and position >= duration * 0.5
