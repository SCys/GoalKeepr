from solver import find_pairs, R, C
from collections import Counter
grid = [list(r) for r in [
    "TSTTPEPT",
    "PCBRSBST",
    "BESCCBEE",
    "TEPERPCB",
    "STPRTPPE",
    "RSERSERC",
    "TBSPCBPS",
    "TCCERETS",
]]
print(Counter(sum(grid, [])))
pairs = find_pairs(grid)
print(f"connectable pairs: {len(pairs)}")
name = {'E':'茄子','P':'土豆','T':'番茄','S':'红薯','C':'白菜','R':'萝卜','B':'烧饼'}
for a,b,t in pairs:
    print(f"{name[t]} ({a[0]},{a[1]}) + ({b[0]},{b[1]})")
# greedy full elimination
g = [row[:] for row in grid]
n = 0
while True:
    ps = find_pairs(g)
    if not ps: break
    (a,b,t) = ps[0]
    g[a[0]-1][a[1]-1] = None; g[b[0]-1][b[1]-1] = None
    n += 1
left = sum(1 for r in range(R) for c in range(C) if g[r][c] is not None)
print(f"\neliminated {n} pairs, remaining {left}")
print([(r+1,c+1,g[r][c]) for r in range(R) for c in range(C) if g[r][c] is not None])
