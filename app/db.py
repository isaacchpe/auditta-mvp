from functools import lru_cache

from app.config import MONGODB_DB, MONGODB_URI


@lru_cache
def obtener_db():
    if MONGODB_URI.startswith("mongomock://"):
        import mongomock

        cliente = mongomock.MongoClient()
    else:
        from pymongo import MongoClient

        cliente = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
    return cliente[MONGODB_DB]
