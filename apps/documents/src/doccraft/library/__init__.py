"""The documents of the plant: reading files, cutting them into passages, finding the plant's tags
in them, and searching them by words and by meaning.

| Module | Does |
|---|---|
| ``extract`` | a file (PDF, DOCX, XLSX, PPTX, text) into sections with their page and heading |
| ``passages`` | sections into passages of about 350 words, never across a heading |
| ``tags`` | the plant's tags (``FIC-1003``) found in a text, kept only when PlantCraft knows them |
| ``embed`` | passages into vectors, offline (a bundled ONNX model, or a hash fallback) |
| ``store`` | folders, documents, revisions and passages in the app's SQLite, with FTS5 and vectors |
| ``search`` | words (BM25) and meaning (cosine) fused by reciprocal rank, filtered by access |
"""
