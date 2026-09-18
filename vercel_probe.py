from fastapi import FastAPI

app = FastAPI(title="WhatsApp Generator - Sonde Vercel")

@app.get("/")
async def index():
    return {"ok": True, "msg": "sonde fonctionnelle"}

@app.get("/api/stats")
async def stats():
    return {"total": 0, "tested": 0, "exists": 0, "templates": 0, "campaigns": 0, "queue": 0}
