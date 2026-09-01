def next_tour_index(position: float, page_count: int) -> int | None:
    if page_count <= 1:
        return None
    return (round(position) + 1) % page_count
