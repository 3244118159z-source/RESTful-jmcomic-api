import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "cloud-functions"))
from backend import app

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","3002")))
