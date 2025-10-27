from fastapi import FastAPI
import uvicorn
from main import leads, send, status

app = FastAPI(
    title="Dental Leads Engine",
    version="0.1.0"
)

app.include_router(leads.router)
app.include_router(send.router)
app.include_router(status.router)

@app.get("/")
def root():
    return {"ok": True, "service": "dental-leads-backend"}

if __name__ == "__main__":
    uvicorn.run("main.main:app", host="0.0.0.0", port=8000, reload=True)
