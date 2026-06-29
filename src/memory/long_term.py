import chromadb
from src.config import CHROMA_HOST, CHROMA_PORT


def get_memory_collection():
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return client.get_or_create_collection("memory")


async def save_memory(user_id: str, key: str, value: str):
    collection = get_memory_collection()
    doc_id = f"{user_id}-{key}"
    collection.upsert(
        ids=[doc_id],
        documents=[value],
        metadatas=[{"user_id": user_id, "key": key}],
    )
    print(f"[memory] saved: {doc_id}")


async def recall_memory(user_id: str, query: str, top_k: int = 5) -> list[str]:
    collection = get_memory_collection()
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where={"user_id": user_id},
    )
    documents = results.get("documents", [[]])[0]
    print(f"[memory] recalled {len(documents)} items for {user_id}")
    return documents
