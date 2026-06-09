from types import SimpleNamespace

from fastapi.testclient import TestClient

import saas.app as saas_app
import saas.auth as saas_auth


async def _fake_user_owner(*args, **kwargs):
    return SimpleNamespace(id='test-user', role=getattr(saas_auth,'UserRole',None), organization_id='test-org')

saas_app.app.dependency_overrides[saas_auth.get_current_user] = _fake_user_owner
client = TestClient(saas_app.app)

payload = {
    'name':'research_crew',
    'agents':[{'role':'Researcher','goal':'Find info'}],
    'tasks':[{'description':'Research {topic}','expected_output':'Summary'}],
    'process':'pipeline',
}
r = client.post('/api/v1/crews', json=payload)
print('crews status', r.status_code)
try:
    print(r.json())
except Exception:
    print(r.text)

payload2={'name':'research_task','description':'Research {topic}','expected_output':'Summary'}
r2 = client.post('/api/v1/tasks', json=payload2)
print('tasks status', r2.status_code)
try:
    print(r2.json())
except Exception:
    print(r2.text)
