"""Base ranges: n with digits_b(n^2) + digits_b(n^3) == b (the search range), and which
bases have nice-only work (some residue mod b-1 can be nice)."""
def ndig(x, b):
    d = 0
    while x:
        x //= b; d += 1
    return d

def total(n, b):
    return ndig(n * n, b) + ndig(n ** 3, b)

def first_n(b, target):  # smallest n with total(n) >= target (total is nondecreasing)
    lo, hi = 1, 1
    while total(hi, b) < target:
        hi *= 2
    while lo < hi:
        m = (lo + hi) // 2
        if total(m, b) >= target: hi = m
        else: lo = m + 1
    return lo

def base_range(b):
    s, e = first_n(b, b), first_n(b, b + 1)
    return (s, e) if total(s, b) == b and e > s else None

def niceonly_residues(b):
    # n is only possibly nice if n^2 + n^3 ≡ sum of all digits (b(b-1)/2) mod (b-1)
    m = b - 1; want = (b * (b - 1) // 2) % m
    return [r for r in range(m) if (r * r + r ** 3) % m == want]

if __name__ == "__main__":
    for b in range(40, 98):
        r = base_range(b)
        if r:
            print(b, r[0], r[1], r[1] - r[0], len(niceonly_residues(b)))
