"""API endpoints para mini repo fixture."""

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI()

    class ItemRequest(BaseModel):
        name: str
        value: int

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    @app.post("/items")
    async def create_item(item: ItemRequest):
        """Create a new item."""
        if item.value < 0:
            raise HTTPException(status_code=400, detail="Value cannot be negative")
        return {"id": 1, "name": item.name, "value": item.value}

except ImportError:
    pass
