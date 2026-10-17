# 连连看 solver: 8x8 grid, connect identical tiles with path of <=2 turns (through empty cells)
grid = [list(r) for r in [
    "EEPTSCRB",
    "SSCTSESB",
    "TEREPTRR",
    "CSTCRBPS",
    "TBPSRTRS",
    "CERBTPTP",
    "TTBSESRB",
    "EPEPRSPR",
]]
R, C = 8, 8
from collections import Counter
print(Counter(sum(grid, [])))

def can_connect(g, r1, c1, r2, c2):
    # BFS over states (r, c, dir, turns); may pass through empty cells only
    # grid padded virtually: path may go outside border (classic rule)
    from collections import deque
    start = (r1, c1)
    # state: (r, c, direction) direction: 0=up,1=down,2=left,3=right, 4=none(start)
    dq = deque()
    dq.append((r1, c1, 4, 0))
    seen = {}
    dirs = [(-1,0),(1,0),(0,-1),(0,1)]
    while dq:
        r, c, d, t = dq.popleft()
        key = (r, c, d)
        if key in seen and seen[key] <= t: continue
        seen[key] = t
        if (r, c) == (r2, c2) and d != 4:
            return True
        for nd, (dr, dc) in enumerate(dirs):
            nt = t if (d == 4 or d == nd) else t + 1
            if nt > 2: continue
            nr, nc = r + dr, c + dc
            if not (-1 <= nr <= R and -1 <= nc <= C): continue  # allow one ring outside
            if (nr, nc) == (r2, c2):
                dq.append((nr, nc, nd, nt)); continue
            if 0 <= nr < R and 0 <= nc < C and g[nr][nc] is not None:
                continue
            dq.append((nr, nc, nd, nt))
    return False

def find_pairs(g):
    res = []
    for r1 in range(R):
        for c1 in range(C):
            if g[r1][c1] is None: continue
            for r2 in range(R):
                for c2 in range(C):
                    if (r2,c2) <= (r1,c1): continue
                    if g[r2][c2] is None or g[r2][c2] != g[r1][c1]: continue
                    if can_connect(g, r1, c1, r2, c2):
                        res.append(((r1+1,c1+1),(r2+1,c2+1),g[r1][c1]))
    return res

pairs = find_pairs(grid)
print(f"currently connectable pairs: {len(pairs)}")
for p in pairs: print(p)

# greedy elimination attempt
g = [row[:] for row in grid]
steps = []
while True:
    ps = find_pairs(g)
    if not ps: break
    (a, b, t) = ps[0]
    steps.append((a,b,t))
    g[a[0]-1][a[1]-1] = None
    g[b[0]-1][b[1]-1] = None
left = sum(1 for r in range(R) for c in range(C) if g[r][c] is not None)
print(f"\neliminated {len(steps)} pairs, remaining tiles: {left}")
rem = [(r+1,c+1,g[r][c]) for r in range(R) for c in range(C) if g[r][c] is not None]
print("remaining:", rem)

# print full elimination sequence with names + draw annotated board
name = {'E':'茄子','P':'土豆','T':'番茄','S':'红薯','C':'白菜','R':'萝卜','B':'烧饼'}
print("\n--- elimination order ---")
g2 = [row[:] for row in grid]
seq = []
while True:
    ps = find_pairs(g2)
    if not ps: break
    (a,b,t) = ps[0]
    seq.append((a,b,t))
    g2[a[0]-1][a[1]-1] = None; g2[b[0]-1][b[1]-1] = None
for i,(a,b,t) in enumerate(seq,1):
    print(f"{i:2d}. {name[t]} ({a[0]},{a[1]}) + ({b[0]},{b[1]})")
