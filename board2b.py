import importlib, sys
# reuse functions without re-running demo: extract from solver source
src = open('solver.py', encoding='utf-8').read()
ns = {}
exec(src.split("# greedy elimination attempt")[0].split("pairs = find_pairs")[0], ns)
find_pairs, R, C = ns['find_pairs'], ns['R'], ns['C']
grid = [list(r) for r in [
    "TSTTPEPT","PCBRSBST","BESCCBEE","TEPERPCB",
    "STPRTPPE","RSERSERC","TBSPCBPS","TCCERETS",
]]
name = {'E':'茄子','P':'土豆','T':'番茄','S':'红薯','C':'白菜','R':'萝卜','B':'烧饼'}
g = [row[:] for row in grid]
seq = []
while True:
    ps = find_pairs(g)
    if not ps: break
    (a,b,t) = ps[0]
    seq.append((a,b,t))
    g[a[0]-1][a[1]-1] = None; g[b[0]-1][b[1]-1] = None
for i,(a,b,t) in enumerate(seq,1):
    print(f"{i:2d}. {name[t]} ({a[0]},{a[1]}) + ({b[0]},{b[1]})")
print("leftover:", [(r+1,c+1,name[g[r][c]]) for r in range(R) for c in range(C) if g[r][c] is not None])
