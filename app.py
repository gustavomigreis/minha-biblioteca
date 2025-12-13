import streamlit as st
import sqlite3
import pandas as pd
import os
import matplotlib.pyplot as plt
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode 

# --- Configuração da Página ---
st.set_page_config(page_title="Biblioteca Digital", layout="wide")
DB_NAME = "minha_biblioteca.db"

# --- Funções de Banco de Dados ---
def get_connection():
    return sqlite3.connect(DB_NAME)

def carregar_dados_bibliografia():
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM bibliografia", conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def update_all_data(df_atualizado):
    """Salva todas as colunas alteradas da tabela de volta no SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    # Comando SQL para atualizar todas as colunas editáveis
    sql_update = "UPDATE bibliografia SET titulo=?, autor=?, tipo=?, ano=?, tags=?, caminho_arquivo=? WHERE id=?"
    
    # Prepara a lista de tuplas para execução em lote
    updates = [
        (row['titulo'], row['autor'], row['tipo'], row['ano'], row['tags'], row['caminho_arquivo'], row['id'])
        for index, row in df_atualizado.iterrows()
    ]
    
    try:
        cursor.executemany(sql_update, updates)
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no banco de dados: {e}")
        return False
    finally:
        conn.close()

# --- Interface Gráfica ---
st.sidebar.title("📚 Navegação")
menu = st.sidebar.radio("Ir para:", ["➕ Cadastro Manual", "🔍 Consulta e Leitura", "🔗 Gestão de Links em Massa", "📊 Dashboard"])


# === PÁGINA 1: CADASTRO MANUAL ===
if menu == "➕ Cadastro Manual":
    st.title("➕ Cadastrar Nova Referência")
    st.markdown("Use esta página para adicionar livros e artigos diretamente ao seu banco de dados.")

    with st.form("form_cadastro"):
        col1, col2 = st.columns(2)
        with col1:
            titulo = st.text_input("Título da Obra *")
            autor = st.text_input("Autor (Sobrenome, Nome)")
            tipo = st.selectbox("Tipo:", ["Livro", "Artigo", "Capítulo", "Tese", "Relatório", "Outro"])
        
        with col2:
            ano = st.number_input("Ano de Publicação", min_value=1900, max_value=2100, step=1, value=2023)
            tags = st.text_input("Tags (separadas por vírgula, ex: Urbanismo, Planejamento)")
            link_drive = st.text_input("Link do Google Drive (opcional)")
        
        enviado = st.form_submit_button("Salvar Referência 💾", type="primary")

        if enviado:
            if titulo and autor:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO bibliografia (titulo, autor, tipo, ano, tags, caminho_arquivo)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (titulo, autor, tipo, ano, tags, link_drive))
                    conn.commit()
                    st.success(f"Referência '{titulo}' salva com sucesso! ID: {cursor.lastrowid}")
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")
                finally:
                    conn.close()
            else:
                st.warning("Preencha pelo menos o Título e o Autor.")


# === PÁGINA 2: CONSULTA E LEITURA ===
elif menu == "🔍 Consulta e Leitura":
    st.title("📖 Consulta de Referências")
    df = carregar_dados_bibliografia()

    if not df.empty:
        filtro = st.text_input("🔍 Pesquisar (Título, Autor ou Tag):")
        if filtro:
            df = df[df['titulo'].str.contains(filtro, case=False, na=False) | 
                    df['autor'].str.contains(filtro, case=False, na=False) |
                    df['tags'].str.contains(filtro, case=False, na=False)
            ]

        st.dataframe(df[['titulo', 'autor', 'tipo', 'ano']], use_container_width=True, hide_index=True)
        st.write("---")
        
        opcoes = df.set_index('id')['titulo'].to_dict()
        if opcoes:
            id_selecionado = st.selectbox("Selecione para ler:", options=opcoes.keys(), format_func=lambda x: opcoes[x])
            
            infos = df[df['id'] == id_selecionado].iloc[0]
            caminho = infos['caminho_arquivo']
            
            if caminho:
                st.info(f"Caminho/Link cadastrado: {caminho}")
                
                if str(caminho).startswith("http"):
                    st.success("✅ Documento disponível online! (Funciona no celular)")
                    st.link_button("☁️ Abrir no Google Drive / Web", caminho, type="primary")
                
                elif os.path.exists(caminho):
                    st.warning("💻 Arquivo local (só abre se estiver no PC).")
                    with open(caminho, "rb") as f:
                        st.download_button("📥 Baixar Localmente", f, file_name=os.path.basename(caminho))
                else:
                    st.error("❌ Arquivo não encontrado. O link pode estar quebrado ou não foi cadastrado.")
            else:
                st.warning("⚠️ Nenhum arquivo vinculado.")

    else:
        st.warning("Sua biblioteca está vazia. Cadastre o primeiro item ou importe do Zotero.")


# === PÁGINA 3: GESTÃO DE LINKS EM MASSA (E EDIÇÃO DE DADOS) ===
elif menu == "🔗 Gestão de Links em Massa":
    st.title("🔗 Gestão de Links e Edição de Dados em Massa")
    st.markdown("""
    1. **Edite as células** (clique duas vezes) para corrigir títulos, autores, **Tipo** ou **Ano**.
    2. Cole o link do Google Drive na coluna **caminho_arquivo**.
    3. Clique no botão azul para salvar.
    """)
    
    df_links = carregar_dados_bibliografia()
    
    if not df_links.empty:
        # Configurações da Tabela AgGrid
        gb = GridOptionsBuilder.from_dataframe(df_links)
        
        # Torna as colunas mais relevantes editáveis
        gb.configure_column("id", header_name="ID", editable=False)
        gb.configure_column("titulo", editable=True)
        gb.configure_column("autor", editable=True)
        
        # CORREÇÃO: Colunas 'tipo' e 'ano' agora são editáveis
        gb.configure_column("tipo", editable=True) 
        gb.configure_column("ano", editable=True)  

        gb.configure_column("caminho_arquivo", header_name="Link Google Drive", editable=True, width=400)
        
        # Excluir colunas que não são úteis para edição em massa ou estão em outro formato
        gb.configure_columns(['tags', 'resumo', 'data_adicao'], hide=True)
        
        gridOptions = gb.build()

        # Exibe a tabela editável
        grid_response = AgGrid(
            df_links,
            gridOptions=gridOptions,
            data_return_mode='AS_INPUT',
            update_mode=GridUpdateMode.VALUE_CHANGED, 
            fit_columns_on_grid_load=False,
            height=500, 
            width='100%',
            reload_data=True
        )

        df_atualizado = grid_response['data']

        st.write("---")
        if st.button("💾 Salvar TODAS as Alterações no Banco de Dados Local", type="primary"):
            if update_all_data(df_atualizado):
                st.success("✅ Todos os dados foram salvos no arquivo minha_biblioteca.db!")
                st.info("Próximo Passo para usar online: Envie os arquivos 'minha_biblioteca.db' e 'app.py' atualizados para o GitHub.")
            else:
                st.error("Falha ao salvar. Verifique o terminal.")

    else:
        st.info("Nenhum dado para gerenciar.")


# === PÁGINA 4: DASHBOARD ===
elif menu == "📊 Dashboard":
    st.title("📊 Estatísticas da Biblioteca")
    
    if os.path.exists(DB_NAME):
        conn = get_connection()
        df = pd.read_sql_query("SELECT * FROM bibliografia", conn)
        conn.close()

        if not df.empty:
            st.subheader("Distribuição de Referências")
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Por Tipo")
                dados_tipo = df.groupby('tipo').size().reset_index(name='qtd')
                if not dados_tipo.empty:
                    fig, ax = plt.subplots()
                    ax.pie(dados_tipo['qtd'], labels=dados_tipo['tipo'], autopct='%1.1f%%'); st.pyplot(fig)

            with col2:
                st.subheader("Publicações por Ano (Últimos 15)")
                dados_ano = df[df['ano'] > 1900].groupby('ano').size().reset_index(name='qtd').sort_values('ano', ascending=False).head(15)
                if not dados_ano.empty:
                    st.bar_chart(dados_ano.set_index('ano'))
            
        else:
            st.info("Sem dados suficientes para gerar o Dashboard.")
    else:
        st.error("Banco de dados não encontrado.")