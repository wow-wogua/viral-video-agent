import chromadb
from src.config import CHROMA_HOST, CHROMA_PORT


def get_chroma_client():
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def get_or_create_collection(name: str = "knowledge"):
    client = get_chroma_client()
    return client.get_or_create_collection(name)
