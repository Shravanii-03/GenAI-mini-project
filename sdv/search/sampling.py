"""Space-filling sampling of attack parameters."""


def latin_hypercube(bounds: dict, n: int, rng):
    """n stratified samples over a {name: (lo, hi)} box; integer-valued for the 'k' parameter."""
    columns = {}
    for key, (lo, hi) in bounds.items():
        cells = [(i + rng.random()) / n for i in range(n)]
        rng.shuffle(cells)
        values = [lo + c * (hi - lo) for c in cells]
        columns[key] = [round(v) for v in values] if key == "k" else values
    return [{k: columns[k][i] for k in bounds} for i in range(n)]
