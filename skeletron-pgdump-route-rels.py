#!/usr/bin/env python
from sys import stdout, stderr
from bz2 import BZ2File
from xml.etree.ElementTree import Element, ElementTree
from itertools import count
from multiprocessing import JoinableQueue, Process

from psycopg2 import connect
from shapely.geometry import LineString

def write_groups(queue):
    '''
    '''
    names = ('routes-%06d.osm.bz2' % id for id in count(1))
    
    while True:
        try:
            group = queue.get(timeout=300)
        except:
            print('bah')
            break
        
        tree = make_group_tree(group)
        file = BZ2File(next(names), mode='w')

        tree.write(file)
        file.close()

def get_relations_list(db):
    '''
    '''
    db.execute('''SELECT id, tags
                  FROM planet_osm_rels
                  WHERE 'network' = ANY(tags)
                    AND 'ref' = ANY(tags)
                  ''')
    
    relations = []
    
    for (id, tags) in db.fetchall():
        tags = dict([keyval for keyval in zip(tags[0::2], tags[1::2])])
        
        if 'network' not in tags or 'ref' not in tags:
            continue
        
        network = tags.get('network', '')
        route = tags.get('route', '')
        
        if route == 'route_master' and 'route_master' in tags:
            route = tags.get('route_master', '')

        # Skip bike
        if network in ('lcn', 'rcn', 'ncn', 'icn', 'mtb'):
            continue
        
        # Skip walking
        if network in ('lwn', 'rwn', 'nwn', 'iwn'):
            continue

        # Skip buses, trains
        if route in ('bus', 'bicycle', 'tram', 'train', 'subway', 'light_rail'):
            continue
        
        # if tags.get('network', '') not in ('US:I', ): continue
        
        relations.append((id, tags))
    
    return relations

def get_relation_ways(db, rel_id):
    '''
    '''
    rel_ids = [rel_id]
    rels_seen = set()
    way_ids = set()
    
    while rel_ids:
        rel_id = rel_ids.pop(0)
        
        if rel_id in rels_seen:
            break
        
        rels_seen.add(rel_id)
        
        db.execute('''SELECT members
                      FROM planet_osm_rels
                      WHERE id = %d''' \
                    % rel_id)
        
        try:
            (members, ) = db.fetchone()

        except TypeError:
            # missing relation
            continue
        
        if not members:
            continue
        
        for member in members[0::2]:
            if member.startswith('r'):
                rel_ids.append(int(member[1:]))
            
            elif member.startswith('w'):
                way_ids.add(int(member[1:]))
    
    return way_ids

def get_way_tags(db, way_id):
    '''
    '''
    db.execute('''SELECT tags
                  FROM planet_osm_ways
                  WHERE id = %d''' \
                % way_id)
    
    try:
        (tags, ) = db.fetchone()
        tags = dict([keyval for keyval in zip(tags[0::2], tags[1::2])])

    except TypeError:
        # missing way
        return dict()
    
    return tags

def get_way_linestring(db, way_id):
    '''
    '''
    db.execute('SELECT SRID(way) FROM planet_osm_point LIMIT 1')
    
    (srid, ) = db.fetchone()
    
    if srid not in (4326, 900913):
        raise Exception('Unknown SRID %d' % srid)
    
    db.execute('''SELECT X(location) AS lon, Y(location) AS lat
                  FROM (
                    SELECT
                      CASE
                      WHEN %s = 900913
                      THEN Transform(SetSRID(MakePoint(n.lon * 0.01, n.lat * 0.01), 900913), 4326)
                      WHEN %s = 4326
                      THEN MakePoint(n.lon * 0.0000001, n.lat * 0.0000001)
                      END AS location
                    FROM (
                      SELECT unnest(nodes)::int AS id
                      FROM planet_osm_ways
                      WHERE id = %d
                    ) AS w,
                    planet_osm_nodes AS n
                    WHERE n.id = w.id
                  ) AS points''' \
                % (srid, srid, way_id))
    
    coords = db.fetchall()
    
    if len(coords) < 2:
        return None
    
    return LineString(coords)

def cascaded_union(shapes):
    '''
    '''
    if len(shapes) == 0:
        return None
    
    if len(shapes) == 1:
        return shapes[0]
    
    if len(shapes) == 2:
        if shapes[0] and shapes[1]:
            return shapes[0].union(shapes[1])
        
        if shapes[0] is None:
            return shapes[1]
        
        if shapes[1] is None:
            return shapes[0]
        
        return None
    
    cut = len(shapes) / 2
    
    shapes1 = cascaded_union(shapes[:cut])
    shapes2 = cascaded_union(shapes[cut:])
    
    return cascaded_union([shapes1, shapes2])

def relation_key(tags):
    '''
    '''
    return (tags.get('network', ''), tags.get('ref', ''), tags.get('modifier', ''))

def gen_relation_groups(relations):
    '''
    '''
    relation_keys = [relation_key(tags) for (id, tags) in relations]
    
    group, coords, last_key = [], 0, None
    
    for (key, (id, tags)) in sorted(zip(relation_keys, relations)):

        if coords > 100000 and key != last_key:
            yield group
            group, coords = [], 0
        
        way_ids = get_relation_ways(db, id)
        way_tags = [get_way_tags(db, way_id) for way_id in way_ids]
        way_lines = [get_way_linestring(db, way_id) for way_id in way_ids]
        rel_coords = sum([len(line.coords) for line in way_lines if line])
        #multiline = cascaded_union(way_lines)
        
        print(', '.join(key), '--', rel_coords, 'nodes', file=stderr)
        
        group.append((id, tags, way_tags, way_lines))
        coords += rel_coords
        last_key = key

    yield group

def make_group_tree(group):
    '''
    '''
    ids = (str(-id) for id in count(1))
    osm = Element('osm', dict(version='0.6'))

    for (id, tags, way_tags, way_lines) in group:
    
        rel = Element('relation', dict(id=next(ids), version='1', timestamp='0000-00-00T00:00:00Z'))
        
        for (k, v) in list(tags.items()):
            rel.append(Element('tag', dict(k=k, v=v)))
        
        for (tags, line) in zip(way_tags, way_lines):
            if not line:
                continue
        
            way = Element('way', dict(id=next(ids), version='1', timestamp='0000-00-00T00:00:00Z'))
            
            for (k, v) in list(tags.items()):
                way.append(Element('tag', dict(k=k, v=v)))
            
            for coord in line.coords:
                lon, lat = '%.7f' % coord[0], '%.7f' % coord[1]
                node = Element('node', dict(id=next(ids), lat=lat, lon=lon, version='1', timestamp='0000-00-00T00:00:00Z'))
                nd = Element('nd', dict(ref=node.attrib['id']))

                osm.append(node)
                way.append(nd)
            
            rel.append(Element('member', dict(type='way', ref=way.attrib['id'])))
            
            osm.append(way)
        
        osm.append(rel)
    
    return ElementTree(osm)

if __name__ == '__main__':

    queue = JoinableQueue()
    
    group_writer = Process(target=write_groups, args=(queue, ))
    group_writer.start()
    
    db = connect(host='localhost', user='gis', database='gis', password='gis').cursor()
    
    relations = get_relations_list(db)
    
    for group in gen_relation_groups(relations):
        queue.put(group)

        print('-->', len(group), 'relations', file=stderr)
        print('-' * 80, file=stderr)
    
    group_writer.join()
