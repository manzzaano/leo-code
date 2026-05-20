"""Tests: detección de frameworks en parser."""
from leo_code.core.parser import extract_from_python, detect_frameworks

def _extract(code):
    return extract_from_python(code, "test.py")

def get_types(capsules):
    return {(c.name, c.type, c.properties.get("framework", "")) for c in capsules}


def test_pydantic_model():
    caps = _extract("from pydantic import BaseModel\nclass User(BaseModel):\n    name: str")
    types = get_types(caps)
    assert ("User", "model", "pydantic") in types

def test_fastapi_endpoint():
    caps = _extract("from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/users')\ndef get_users():\n    return []")
    types = get_types(caps)
    assert ("get_users", "endpoint", "fastapi") in types

def test_flask_endpoint():
    caps = _extract("from flask import Flask\napp = Flask(__name__)\n@app.route('/hello')\ndef hello():\n    return 'hi'")
    types = get_types(caps)
    assert ("hello", "endpoint", "flask") in types

def test_django_model():
    caps = _extract("from django.db import models\nclass User(models.Model):\n    name = models.CharField(max_length=100)")
    types = get_types(caps)
    assert ("User", "model", "django") in types

def test_sqlalchemy_model():
    caps = _extract("from flask_sqlalchemy import SQLAlchemy\ndb = SQLAlchemy()\nclass User(db.Model):\n    name = db.Column(db.String)")
    types = get_types(caps)
    assert ("User", "model", "sqlalchemy") in types

def test_celery_task():
    caps = _extract("from celery import shared_task\n@shared_task\ndef process_order(order_id: int):\n    return True")
    types = get_types(caps)
    assert ("process_order", "task", "celery") in types

def test_aiohttp_endpoint():
    caps = _extract("from aiohttp import web\nroutes = web.RouteTableDef()\n@routes.get('/health')\ndef health(request):\n    return web.Response(text='ok')")
    types = get_types(caps)
    assert ("health", "endpoint", "aiohttp") in types

def test_sqlmodel_model():
    caps = _extract("from sqlmodel import SQLModel, Field\nclass User(SQLModel, table=True):\n    id: int = Field(primary_key=True)")
    types = get_types(caps)
    assert ("User", "model", "sqlmodel") in types

def test_strawberry_schema():
    caps = _extract("import strawberry\n@strawberry.type\nclass User:\n    name: str\nschema = strawberry.Schema(query=User)")
    types = get_types(caps)
    assert ("User", "schema", "strawberry") in types

print("OK: 9 framework tests passed")
