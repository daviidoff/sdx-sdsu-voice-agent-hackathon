import json
import sqlite3

from app.dashboard import instruction_for


def test_full_coverage_plus_partial_identical_zone_keeps_instruction():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE dashboard_zones (id TEXT PRIMARY KEY, data TEXT)')
    for identifier, polygon in [('full', [[0,0],[0,4],[4,4],[4,0]]),
                                ('partial', [[0,0],[0,2],[4,2],[4,0]])]:
        db.execute('INSERT INTO dashboard_zones VALUES (?,?)', (identifier,json.dumps({
            'id':identifier,'label':identifier,'polygon':polygon,'area':'',
            'level':'evacuate','instruction':'Evacuate','version':1,'updated_at':'2026-11-08'})))
    location = {'status':'resolved','query':'Airport','lat':2,'lng':2,'bounds':[1,3,3,1]}
    result = instruction_for(db,'Airport',location)
    assert result['action']=='evacuate' and result['match_status']=='overlap_agreement'
    assert set(result['matching_zone_ids'])=={'full','partial'}
    partial = json.loads(db.execute("SELECT data FROM dashboard_zones WHERE id='partial'").fetchone()['data'])
    partial.update(level='shelter', instruction='Shelter in place')
    db.execute("UPDATE dashboard_zones SET data=? WHERE id='partial'", (json.dumps(partial),))
    assert instruction_for(db,'Airport',location)['action']=='unknown'
    db.execute("DELETE FROM dashboard_zones WHERE id='full'")
    assert instruction_for(db,'Airport',location)['action']=='unknown'
    db.close()
