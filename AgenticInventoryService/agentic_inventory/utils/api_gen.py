import json
from collections import OrderedDict
from agentic_inventory.main import app

schema = app.openapi()

ordered_schema = json.loads(json.dumps(schema), object_hook=OrderedDict)

pretty_schema = json.dumps(ordered_schema, indent=4)
print(pretty_schema)
