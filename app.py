import streamlit as st
import sqlite3
import pandas as pd
import os
import matplotlib.pyplot as plt

# --- Configuração da Página ---
st.set_page_config(page_title="Minha Biblioteca", layout="wide")
DB_NAME = "minha_biblioteca.db"

# --- Funções Auxiliares ---
def carregar_dados_bibliografia():
    if not os.path.exists(DB_NAME):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT * FROM bibliografia", conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def carregar_dados_datasets():
    if not os.path.exists(DB_NAME):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT * FROM meus_dados", conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def abrir_arquivo_local(caminho):
    """Função segura para abrir arquivo no Windows"""
    if caminho and os.path.exists(caminho):
        try:
            os.startfile(caminho)
            return True, "Arquivo aberto com sucesso!"
        except Exception as e:
            return False, f"Erro ao abrir: {e}"
    else:
        return False, "Arquivo não encontrado ou caminho inválido."

# --- Interface Gráfica ---

# Menu Lateral
st.sidebar.title("📚 Navegação")
menu = st.sidebar.radio("Ir para:", ["Biblioteca (Zotero)", "Datasets (Dados)", "Dashboard", "Adicionar Dataset"])

# === PÁGINA 1: BIBLIOTECA ===
if menu == "Biblioteca (Zotero)":
    st.title("📖 Biblioteca de Referências")
    st.markdown("Pesquise seus livros e artigos importados do Zotero.")

    df = carregar_dados_bibliografia()

    if not df.empty:
        # Campo de busca
        filtro = st.text_input("🔍 Pesquisar (Título, Autor ou Tag):")
        
        if filtro:
            # Filtra ignorando maiúsculas/minúsculas
            df = df[
                df['titulo'].str.contains(filtro, case=False, na=False) |
                df['autor'].str.contains(filtro, case=False, na=False) |
                df['tags'].str.contains(filtro, case=False, na=False)
            ]

        # Tabela
        st.dataframe(df[['titulo', 'autor', 'tipo', 'ano', 'tags']], use_container_width=True, hide_index=True)

        st.write("---")
        st.subheader("🚀 Ações")
        
        # Seletor de Arquivos
        # Cria dicionário {ID: Título}
        opcoes = df.set_index('id')['titulo'].to_dict()
        
        if opcoes:
            id_selecionado = st.selectbox(
                "Selecione um item para abrir o PDF:", 
                options=opcoes.keys(), 
                format_func=lambda x: opcoes[x] if x in opcoes else x
            )

            # --- AQUI ESTAVA O ERRO ---
            # O código abaixo do if deve estar recuado (com espaço na frente)
            if st.button("Abrir Arquivo 📂"):
                lista_caminhos = df[df['id'] == id_selecionado]['caminho_arquivo'].values
                
                if len(lista_caminhos) > 0:
                    caminho = lista_caminhos[0]
                    st.info(f"Tentando abrir: {caminho}")
                    sucesso, msg = abrir_arquivo_local(caminho)
                    if sucesso:
                        st.success("Aberto!")
                    else:
                        st.error(msg)
                else:
                    st.error("Caminho não encontrado no banco.")
        else:
            st.warning("Nenhum item encontrado com essa busca.")

    else:
        st.warning("Sua biblioteca está vazia ou o banco de dados não foi encontrado.")
        st.info("Rode o script 'importar_zotero.py' primeiro.")


# === PÁGINA 2: DATASETS ===
elif menu == "Datasets (Dados)":
    st.title("💾 Meus Dados e Datasets")
    st.markdown("Repositório de arquivos brutos.")
    
    df_dados = carregar_dados_datasets()
    if not df_dados.empty:
        st.dataframe(df_dados, use_container_width=True)
    else:
        st.info("Nenhum dataset cadastrado.")


# === PÁGINA 3: DASHBOARD ===
elif menu == "Dashboard":
    st.title("📊 Estatísticas da Biblioteca")
    
    if os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Por Tipo")
            try:
                dados_tipo = pd.read_sql_query("SELECT tipo, COUNT(*) as qtd FROM bibliografia GROUP BY tipo", conn)
                if not dados_tipo.empty:
                    fig1, ax1 = plt.subplots()
                    ax1.pie(dados_tipo['qtd'], labels=dados_tipo['tipo'], autopct='%1.1f%%', startangle=140)
                    st.pyplot(fig1)
                else:
                    st.write("Sem dados.")
            except:
                st.write("Erro ao ler dados.")

        with col2:
            st.subheader("Por Ano")
            try:
                dados_ano = pd.read_sql_query("SELECT ano, COUNT(*) as qtd FROM bibliografia WHERE ano > 1900 GROUP BY ano ORDER BY ano DESC LIMIT 15", conn)
                if not dados_ano.empty:
                    st.bar_chart(dados_ano.set_index('ano'))
                else:
                    st.write("Sem dados.")
            except:
                st.write("Erro ao ler dados.")
                
        conn.close()
    else:
        st.error("Banco de dados não encontrado.")


# === PÁGINA 4: ADICIONAR ===
elif menu == "Adicionar Dataset":
    st.title("➕ Cadastrar Novo Dataset")
    
    with st.form("form_dataset"):
        nome = st.text_input("Nome do Dataset")
        descricao = st.text_area("Descrição")
        fonte = st.text_input("Fonte")
        caminho = st.text_input("Caminho Completo do Arquivo")
        
        enviado = st.form_submit_button("Salvar no Banco")
        
        if enviado:
            if nome and caminho:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS meus_dados (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            nome_dataset TEXT, descricao TEXT, formato TEXT, 
                            fonte TEXT, caminho_arquivo TEXT, data_coleta DATE
                        )
                    """)
                    cursor.execute("""
                        INSERT INTO meus_dados (nome_dataset, descricao, formato, fonte, caminho_arquivo)
                        VALUES (?, ?, ?, ?, ?)
                    """, (nome, descricao, "Manual", fonte, caminho))
                    conn.commit()
                    st.success(f"Dataset '{nome}' salvo com sucesso!")
                except Exception as e:
                    st.error(f"Erro: {e}")
                finally:
                    conn.close()
            else:
                st.warning("Preencha Nome e Caminho.")