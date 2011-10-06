from sys import stdin
from math import hypot, ceil

from Skeletron2 import ParserOSM, Canvas, buffer_graph, polygon_rings, skeleton_graph

p = ParserOSM()
g = p.parse(stdin.read())
print sorted(g.keys())
graph = g[(u'Lakeside Drive', u'secondary')]

# draw the underlying street

points = [graph.node[id]['point'] for id in graph.nodes()]
xs, ys = map(None, *[(pt.x, pt.y) for pt in points])

xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)

canvas = Canvas(900, 600)
canvas.fit(xmin - 50, ymax + 50, xmax + 50, ymin - 50)

for point in points:
    canvas.dot(point.x, point.y, fill=(.8, .8, .8))

for (a, b) in graph.edges():
    pt1, pt2 = graph.node[a]['point'], graph.node[b]['point']
    line = [(pt1.x, pt1.y), (pt2.x, pt2.y)]
    canvas.line(line, stroke=(.8, .8, .8))

# fatten

poly = buffer_graph(graph)

for ring in polygon_rings(poly):
    canvas.line(list(ring.coords), stroke=(.9, .9, .9))

skeleton = skeleton_graph(poly)

for index in skeleton.nodes():
    point = skeleton.node[index]['point']
    canvas.dot(point.x, point.y)

for (v, w) in skeleton.edges():
    line = list(skeleton.edge[v][w]['line'].coords)
    canvas.line(line)

canvas.save('look.png')