from leo_code.core.parser import extract_from_python

# Pydantic model
code1 = "from pydantic import BaseModel\nclass User(BaseModel):\n    name: str\n    age: int"
caps1 = extract_from_python(code1, "models.py")
print("=== Pydantic ===")
for c in caps1:
    print(f"  {c.name}: type={c.type} fw={c.properties.get('framework','')}")

# FastAPI endpoint
code2 = "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/users')\ndef get_users():\n    return []"
caps2 = extract_from_python(code2, "api.py")
print("=== FastAPI ===")
for c in caps2:
    print(f"  {c.name}: type={c.type} fw={c.properties.get('framework','')} decorators={c.properties.get('decorators','')}")

# Flask endpoint
code3 = "from flask import Flask\napp = Flask(__name__)\n@app.route('/hello')\ndef hello():\n    return 'hi'"
caps3 = extract_from_python(code3, "app.py")
print("=== Flask ===")
for c in caps3:
    print(f"  {c.name}: type={c.type} fw={c.properties.get('framework','')}")

# Django model
code4 = "from django.db import models\nclass User(models.Model):\n    name = models.CharField(max_length=100)"
caps4 = extract_from_python(code4, "models.py")
print("=== Django ===")
for c in caps4:
    print(f"  {c.name}: type={c.type} fw={c.properties.get('framework','')} hereda={c.properties.get('hereda_de','')}")

print("\nOK: all framework detection working")
