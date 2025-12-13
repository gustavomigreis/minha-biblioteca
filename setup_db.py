import sqlite3
import os

DB_NAME = "minha_biblioteca.db"

def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Tabela principal para os livros/referências (dados do Zotero/Manual)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bibliografia (
            id INTEGER PRIMARY KEY,
            titulo TEXT,
            autor TEXT,
            tipo TEXT,
            ano INTEGER,
            tags TEXT,
            caminho_arquivo TEXT -- Usado para links do Google Drive
        )
    """)

    # Tabela para outros datasets (se precisar de dados brutos)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meus_dados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_dataset TEXT,
            descricao TEXT,
            caminho_arquivo TEXT
        )
    """)
    conn.commit()
    conn.close()
    print(f"✅ Banco de dados '{DB_NAME}' criado com sucesso.")

if __name__ == "__main__":
    setup_database()