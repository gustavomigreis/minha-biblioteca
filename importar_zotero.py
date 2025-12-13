import pandas as pd
import sqlite3
import os

# --- Configurações ---
CSV_FILE = "minha_biblioteca.csv"
DB_NAME = "minha_biblioteca.db"
CAMPO_ARQUIVO_ZOTERO = "File Attachments" 

def importar_zotero():
    """Lê o CSV, limpa os dados e insere no banco SQLite."""
    
    # 1. INICIALIZAÇÃO ROBUSTA DAS VARIÁVEIS DE CONTAGEM (CORREÇÃO DE BUG)
    registos_inseridos = 0
    registos_atualizados = 0

    if not os.path.exists(CSV_FILE):
        print("-" * 50)
        print(f"❌ ERRO: Ficheiro '{CSV_FILE}' não encontrado.")
        print("Certifique-se de que o CSV do Zotero está na mesma pasta.")
        print("-" * 50)
        return

    try:
        # 2. Tenta ler o CSV (Ponto-e-vírgula e vírgula)
        try:
            df_zotero = pd.read_csv(CSV_FILE, encoding='utf-8', sep=';')
        except Exception:
            df_zotero = pd.read_csv(CSV_FILE, encoding='utf-8', sep=',')
        
    except Exception as e:
        print(f"❌ Erro de leitura fatal: O CSV não está formatado corretamente. {e}")
        return
        
    print(f"✅ Ficheiro '{CSV_FILE}' carregado. {len(df_zotero)} registos encontrados.")

    # 3. Mapeamento e Limpeza de Colunas
    df_zotero['titulo'] = df_zotero.get('Title', pd.Series()).fillna('')
    df_zotero['autor'] = df_zotero.get('Author', pd.Series()).fillna('')
    df_zotero['tipo'] = df_zotero.get('Item Type', pd.Series()).fillna('Outro')
    df_zotero['ano'] = df_zotero.get('Publication Year', pd.Series()).fillna(0).astype(int)
    df_zotero['tags'] = df_zotero.get('Tags', pd.Series()).fillna('')
    df_zotero['caminho_arquivo'] = df_zotero.get(CAMPO_ARQUIVO_ZOTERO, pd.Series()).astype(str).str.split(';').str[0].fillna('')

    # 4. Conexão e Inserção/Atualização no Banco de Dados
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for index, row in df_zotero.iterrows():
        titulo = row['titulo']
        
        cursor.execute("SELECT id, caminho_arquivo FROM bibliografia WHERE titulo = ?", (titulo,))
        resultado = cursor.fetchone()

        if resultado:
            item_id, caminho_atual = resultado
            # Se já for um link do Drive, preserva o link
            if str(caminho_atual).startswith("http"):
                cursor.execute("""
                    UPDATE bibliografia SET autor=?, tipo=?, ano=?, tags=? WHERE id=?
                """, (row['autor'], row['tipo'], row['ano'], row['tags'], item_id))
            else:
                # Caso contrário, atualiza com os dados do CSV (pode ser o caminho local do Zotero)
                cursor.execute("""
                    UPDATE bibliografia SET autor=?, tipo=?, ano=?, tags=?, caminho_arquivo=? WHERE id=?
                """, (row['autor'], row['tipo'], row['ano'], row['tags'], row['caminho_arquivo'], item_id))
            
            registos_atualizados += 1
        else:
            # Inserir novo registo
            cursor.execute("""
                INSERT INTO bibliografia (titulo, autor, tipo, ano, tags, caminho_arquivo)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (titulo, row['autor'], row['tipo'], row['ano'], row['tags'], row['caminho_arquivo']))
            registos_inseridos += 1
            
    conn.commit()
    conn.close()

    print("-" * 50)
    print(f"✨ Importação Concluída!")
    print(f" > Novas referências adicionadas: {registos_inseridos}")
    print(f" > Referências existentes atualizadas: {registos_atualizados}")
    print("-" * 50)


if __name__ == "__main__":
    importar_zotero()