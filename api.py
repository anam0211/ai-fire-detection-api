"""Public entrypoint for the temperature and IR Fire API."""
import os
from risk_v2.api import app, create_app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), workers=1)
