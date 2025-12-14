import streamlit as st
import sqlite3
import pandas as pd
import os
import matplotlib.pyplot as plt
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode 
import re 
import hashlib 
import io 

# --- Variáveis de Configuração e Segurança ---
st.set_page_config(page_title="LABEUR - Biblioteca Digital", layout="wide")
DB_NAME = "minha_biblioteca.db"
# SENHA FIXA: Hash da senha 'labeur.operacional.senha'
CORRECT_PASSWORD_HASH = hashlib.sha256("labeur.operacional.senha".encode()).hexdigest() 

# Inicializa o estado de visualização do layout (False = Layout Inicial Grande)
if 'layout_buscado' not in st.session_state:
    st.session_state['layout_buscado'] = False
if 'selecao_aggrid_row' not in st.session_state:
    st.session_state['selecao_aggrid_row'] = []

# --- MIGRACAO: ADICIONAR COLUNAS E NOVAS TABELAS (Execute uma vez) ---
def get_connection():
    return sqlite3.connect(DB_NAME)

def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Tenta adicionar a coluna 'localizacao_fisica' na tabela 'bibliografia'
    try:
        cursor.execute("ALTER TABLE bibliografia ADD COLUMN localizacao_fisica TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            st.error(f"Erro ao migrar a tabela bibliografia: {e}")
            
    # 2. Cria a nova tabela 'dados_externos'
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dados_externos (
                id INTEGER PRIMARY KEY,
                titulo TEXT NOT NULL,
                descricao TEXT,
                link_drive TEXT NOT NULL,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception as e:
        st.error(f"Erro ao criar a tabela dados_externos: {e}")
        
    finally:
        conn.close()

# Executa a inicialização do banco de dados
initialize_database()
# -----------------------------------------------------------------------


# --- Funções de Banco de Dados ---

def carregar_dados_bibliografia():
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM bibliografia", conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def carregar_datasets_externos():
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM dados_externos ORDER BY data_cadastro DESC", conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def update_all_data(df_atualizado):
    """Salva todas as colunas alteradas da tabela de volta no SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    sql_update = "UPDATE bibliografia SET titulo=?, autor=?, tipo=?, ano=?, tags=?, caminho_arquivo=?, resumo=?, localizacao_fisica=? WHERE id=?"
    
    updates = [
        (row['titulo'], row['autor'], row['tipo'], row['ano'], row['tags'], row['caminho_arquivo'], 
         row.get('resumo', ''), 
         row.get('localizacao_fisica', ''),
         row['id'])
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

def delete_reference(id_livro):
    """Exclui uma referência do banco de dados."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bibliografia WHERE id = ?", (id_livro,))
    conn.commit()
    conn.close()

# --- Funções para extrair ID e gerar link do Google Drive ---
def extract_file_id(drive_link):
    """Extrai o ID do arquivo de um URL de compartilhamento do Google Drive."""
    match = re.search(r'/d/([^/]+)', drive_link)
    if match:
        return match.group(1)
    
    match_uc = re.search(r'id=([^&]+)', drive_link)
    if match_uc:
        return match_uc.group(1)
        
    return None

def create_drive_download_link(file_id):
    """Gera um link de download direto para o Google Drive."""
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return None

# --- FUNÇÃO DE LOGIN ---
def check_password():
    """Retorna True se a senha estiver correta."""
    if st.session_state.get("logged_in"):
        return True

    def password_entered():
        """Verifica a senha e define o estado da sessão."""
        
        hashed_entered_password = hashlib.sha256(st.session_state["password"].encode()).hexdigest()
        
        if hashed_entered_password == CORRECT_PASSWORD_HASH:
            st.session_state["logged_in"] = True
            del st.session_state["password"]
        else:
            st.session_state["logged_in"] = False
            
    st.sidebar.subheader("🔒 Acesso Restrito")
    st.sidebar.text_input(
        "Senha:", type="password", on_change=password_entered, key="password"
    )
    
    if "logged_in" in st.session_state and st.session_state["logged_in"] is False:
        st.sidebar.error("Senha incorreta.")
    
    return st.session_state.get("logged_in")

# --- CUSTOMIZAÇÃO DE LAYOUT E ESTILOS DINÂMICOS ---

# Estilos que dependem do estado de busca
layout_buscado_css = ""
if st.session_state['layout_buscado']:
    # Layout Pós-Busca: Título Pequeno e no Topo Direito
    layout_buscado_css = f"""
        .main-header-container {{
            position: absolute;
            top: 10px;
            right: 10px;
            text-align: right;
            max-width: 300px;
            z-index: 1000;
        }}
        .main-header-title {{
            font-size: 1.5rem !important;
            font-weight: 600 !important;
            text-align: right !important;
            margin: 0 !important;
        }}
        .main-slogan {{
            font-size: 0.7rem !important;
            text-align: right !important;
            color: #555 !important;
            margin: 0 !important;
        }}
        /* Empurra o conteúdo principal para baixo para evitar sobreposição */
        [data-testid="stAppViewBlockContainer"] > div:first-child {{
            padding-top: 50px; /* Ajuste se necessário */
        }}
    """
else:
    # Layout Inicial: Título Grande e Centralizado
    layout_buscado_css = """
        .main-header-container {
            margin-bottom: 50px;
        }
        .main-header-title { 
            font-size: 3.5rem !important; 
            font-weight: 800 !important;
            text-align: center !important;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.1); 
        }
        .main-slogan {
            font-size: 1.0rem !important;
            text-align: center !important;
            color: #1f1f1f !important;
        }
    """


st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700;800&display=swap');
    .stApp {{ background-color: #fdfdfd; font-family: 'Poppins', sans-serif; }}
    [data-testid="stSidebar"] {{ background-color: #ffffff; box-shadow: 2px 0 10px rgba(0,0,0,0.1); }}
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] h1 {{ color: #1f1f1f !important; }}
    h1, h2, h3, h4, .st-b5, [data-testid="stText"] {{ color: #1f1f1f !important; }}
    .content-box {{ background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); margin-bottom: 20px; }}
    .content-box *, .content-box [data-testid="stText"] {{ color: #1f1f1f !important; }}
    .stTextInput input, .stTextInput textarea {{ color: #1f1f1f !important; }}
    .stTextInput input::placeholder {{ color: #555555 !important; }}
    .stTextInput > div > div, .stSelectbox > div:first-child > div, .stDataFrame {{ background-color: white !important; border-radius: 4px; border: 1px solid #ddd; }}
    footer {{ visibility: hidden; }}
    .footer-custom {{ font-size: 0.9rem; font-weight: 400; text-align: center; margin-top: 50px; padding: 15px 10px; border-top: 1px solid #e0e0e0; color: #555555 !important; line-height: 1.6; }}
    
    /* REDUÇÃO MÁXIMA: Filtro de tema e seus elementos */
    .content-box .stSelectbox > label {{
        font-size: 0.8rem !important; 
        font-weight: 400 !important;
        color: #666666 !important;
    }}
    .content-box .stSelectbox div[role="combobox"] {{
        font-size: 0.9rem !important;
        padding: 5px 10px;
    }}

    /* Destaque da linha de AgGrid selecionada */
    .ag-row-selected {{
        background-color: #e0f0ff !important; /* Fundo azul claro ao selecionar */
        border: 1px solid #007bff;
        font-weight: 600;
    }}
    
    {layout_buscado_css}
    </style>
    """,
    unsafe_allow_html=True
)

# --- INJEÇÃO FORÇADA DE CSS PARA A BARRA DE PESQUISA ---
# Esta é a última tentativa de forçar o tamanho visualmente.
st.markdown("""
<style>
    /* MÁXIMO DE DESTAQUE FORÇADO: Barra de pesquisa */
    .search-container { 
        max-width: 900px; 
        margin: 30px auto 40px auto; 
        text-align: center; 
    }
    
    /* FORÇANDO O TAMANHO DO LABEL (Pesquisa por...) */
    /* Usando id para forçar precedência máxima */
    div[data-testid="stTextInput"] label[for^="search_geral"] {
        font-size: 2.5rem !important; /* AUMENTO EXTREMO */
        font-weight: 900 !important;
        color: #000000 !important;
    }
    /* FORÇANDO O TAMANHO DA CAIXA DE INPUT */
    div[data-testid="stTextInput"] input[id^="search_geral"] {
        font-size: 2.2rem !important; /* AUMENTO EXTREMO */
        padding: 40px 30px !important; /* AUMENTA A ALTURA DA CAIXA */
        border: 4px solid #007bff !important; /* DESTAQUE AINDA MAIOR */
        box-shadow: 0 5px 25px rgba(0, 123, 255, 0.6) !important; 
    }
</style>
""", unsafe_allow_html=True)
# -----------------------------------------------------------------------


# --- LÓGICA DE NAVEGAÇÃO E RESTRIÇÃO ---

# LOGO NO TOPO DO SIDEBAR
st.sidebar.image("Labeur_logo.jpg", width=150) 

# --- DEFINIÇÃO DO MENU COM BASE NO LOGIN ---
opcoes_menu = ["🏠 Biblioteca Principal"]

if check_password():
    opcoes_menu.extend([
        "🔗 Gestão de Referências",
        "➕ Cadastro Manual",
        "📊 Dashboard",
        "💾 Cadastro de Dados Externos"
    ])
    st.sidebar.success("Acesso total liberado.")
else:
    st.sidebar.warning("Acesso restrito. Faça login para gerenciar dados.")

st.sidebar.title("📚 Navegação")
menu = st.sidebar.radio("Ir para:", opcoes_menu)


# === PÁGINA 1: BIBLIOTECA PRINCIPAL (Consulta Pública - HOME) ===
if menu == "🏠 Biblioteca Principal":
    
    # --- TÍTULO PRINCIPAL (Estrutura adaptada para mudança dinâmica de layout) ---
    st.markdown(
        f"""
        <div class="main-header-container">
            <div class="main-header-title">LABEUR - Biblioteca Digital</div>
            <p class="main-slogan">Pesquisa unificada em artigos, livros e datasets externos.</p>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    st.markdown("---") 

    # Prepara os dados
    df_biblio = carregar_dados_bibliografia()
    df_datasets = carregar_datasets_externos()

    # --- INPUT DE FILTRO GERAL (MÁXIMO DE DESTAQUE) ---
    st.markdown('<div class="search-container">', unsafe_allow_html=True)
    # Importante: O ID deve ser mantido como 'search_geral' para o CSS funcionar com [id^="search_geral"]
    filtro_geral = st.text_input("🔍 Pesquisa por Título, Autor, Tag ou Localização:", key="search_geral", label_visibility="visible")
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Placeholder para o conteúdo da busca
    busca_placeholder = st.empty()
    
    with busca_placeholder.container():
        st.markdown('<div class="content-box">', unsafe_allow_html=True)
        
        # --- FILTRAGEM DE TAGS (MENOS DESTAQUE) ---
        
        todas_tags = set()
        for tags_str in df_biblio['tags'].dropna():
            tags_limpas = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
            todas_tags.update(tags_limpas)
        
        temas_opcoes = sorted(list(todas_tags))
        temas_opcoes.insert(0, "TODOS OS TEMAS")
        
        col_tema, col_vazia = st.columns([1, 3])
        with col_tema:
            tema_selecionado = st.selectbox("Filtrar Referências por Tema Principal:", temas_opcoes, key="select_tema_principal")
            
        df_biblio_filtrada = df_biblio.copy()
        
        # Condição para exibir resultados
        deve_exibir_resultados = False
        
        if tema_selecionado != "TODOS OS TEMAS":
            df_biblio_filtrada = df_biblio_filtrada[
                df_biblio_filtrada['tags'].fillna('').apply(lambda x: tema_selecionado in [t.strip() for t in x.split(',')])
            ].copy()
            deve_exibir_resultados = True
        
        
        # --- APLICA FILTRO DE TEXTO GERAL ---
        
        df_datasets_filtrados = df_datasets.copy()
        
        if filtro_geral:
            deve_exibir_resultados = True
            
            # Filtro de Bibliografia
            if not df_biblio_filtrada.empty:
                df_biblio_filtrada = df_biblio_filtrada[
                    df_biblio_filtrada['titulo'].str.contains(filtro_geral, case=False, na=False) | 
                    df_biblio_filtrada['autor'].str.contains(filtro_geral, case=False, na=False) |
                    df_biblio_filtrada['tags'].str.contains(filtro_geral, case=False, na=False) |
                    df_biblio_filtrada['localizacao_fisica'].str.contains(filtro_geral, case=False, na=False) 
                ].copy()
                
            # Filtro de Datasets
            if not df_datasets_filtrados.empty:
                df_datasets_filtrados = df_datasets_filtrados[
                    df_datasets_filtrados['titulo'].str.contains(filtro_geral, case=False, na=False) |
                    df_datasets_filtrados['descricao'].str.contains(filtro_geral, case=False, na=False)
                ].copy()
                
        
        
        # --- CONCATENAÇÃO PARA O DATAFRAME AGGRID ---
        
        df_unificado = pd.DataFrame()

        if not df_biblio_filtrada.empty:
            df_biblio_formatado = df_biblio_filtrada[['id', 'titulo', 'autor', 'ano', 'tipo', 'localizacao_fisica']].copy()
            df_biblio_formatado['ID_Recurso'] = 'B-' + df_biblio_formatado['id'].astype(str)
            df_biblio_formatado['Tipo de Recurso'] = df_biblio_formatado['tipo'].apply(lambda x: f"Referência ({x})")
            df_biblio_formatado = df_biblio_formatado.rename(columns={'autor': 'Autor/Fonte', 'ano': 'Ano/Data', 'localizacao_fisica': 'Localização'})
            
            df_biblio_formatado = df_biblio_formatado[['ID_Recurso', 'Tipo de Recurso', 'titulo', 'Autor/Fonte', 'Ano/Data', 'Localização']]
            df_unificado = pd.concat([df_unificado, df_biblio_formatado])

        if not df_datasets_filtrados.empty:
            df_datasets_formatado = df_datasets_filtrados[['id', 'titulo', 'descricao', 'data_cadastro']].copy()
            df_datasets_formatado['ID_Recurso'] = 'D-' + df_datasets_formatado['id'].astype(str)
            df_datasets_formatado['Tipo de Recurso'] = 'Dataset/Dado'
            df_datasets_formatado['Localização'] = 'Drive/Online'
            
            df_datasets_formatado['Ano/Data'] = df_datasets_formatado['data_cadastro'].str[:10]
            df_datasets_formatado = df_datasets_formatado.rename(columns={'descricao': 'Autor/Fonte'})
            df_datasets_formatado = df_datasets_formatado[['ID_Recurso', 'Tipo de Recurso', 'titulo', 'Autor/Fonte', 'Ano/Data', 'Localização']]
            df_unificado = pd.concat([df_unificado, df_datasets_formatado])
            
        # ------------------------------------------------------------------
        # --- LÓGICA DE EXIBIÇÃO E SELEÇÃO ---
        # ------------------------------------------------------------------
        
        if deve_exibir_resultados and not df_unificado.empty:
            
            # --- ATIVA O LAYOUT DE BUSCA (REINICIA A PÁGINA COM O NOVO CSS) ---
            if not st.session_state['layout_buscado']:
                st.session_state['layout_buscado'] = True
                st.rerun() 
            # --- FIM DA ATIVAÇÃO DE LAYOUT ---

            st.subheader(f"Resultados da Busca Unificada ({len(df_unificado)} itens):")
            st.info("Clique em uma linha na tabela abaixo para ver os detalhes e a pré-visualização.")
            
            # Configuração do AgGrid para SELEÇÃO DE LINHA
            df_aggrid = df_unificado[['Tipo de Recurso', 'titulo', 'Autor/Fonte', 'Ano/Data', 'Localização', 'ID_Recurso']].reset_index(drop=True)

            gb = GridOptionsBuilder.from_dataframe(df_aggrid)
            gb.configure_column("ID_Recurso", hide=True)
            # Configura seleção de linha única
            gb.configure_selection('single', use_checkbox=False)
            gb.configure_grid_options(domLayout='autoHeight')
            gridOptions = gb.build()

            grid_response = AgGrid(
                df_aggrid,
                gridOptions=gridOptions,
                data_return_mode='AS_INPUT',
                update_mode=GridUpdateMode.MODEL_CHANGED, # Detecta a seleção de linha
                fit_columns_on_grid_load=True,
                allow_unsafe_jscode=True,
                theme='streamlit',
                key='aggrid_busca_unificada'
            )
            
            # Captura o item selecionado na tabela
            selected_rows_df = grid_response.get('selected_rows')
            
            id_selecionado = None
            
            if selected_rows_df is not None and not selected_rows_df.empty: 
                id_selecionado = selected_rows_df.iloc[0]['ID_Recurso']
            
            # Se não houver seleção, mas houver resultados, seleciona o primeiro item filtrado por padrão
            elif not df_unificado.empty:
                 id_selecionado = df_unificado['ID_Recurso'].iloc[0]


            # Fecha content-box da lista
            st.markdown('</div>', unsafe_allow_html=True) 

            # --- SEÇÃO DE DETALHES DINÂMICOS ---
            if id_selecionado:
                st.markdown("## Detalhes e Pré-visualização")
                
                recurso_tipo = id_selecionado.split('-')[0]
                original_id = int(id_selecionado.split('-')[1])

                col_principal, col_lateral = st.columns([2.5, 1.5]) 

                if recurso_tipo == 'B': # REFERÊNCIA BIBLIOGRÁFICA (PDF/DOCUMENTO)
                    infos = df_biblio[df_biblio['id'] == original_id].iloc[0]
                    caminho = infos.get('caminho_arquivo', '')
                    resumo = infos.get('resumo', 'Nenhum resumo cadastrado.')
                    localizacao = infos.get('localizacao_fisica', 'Não cadastrada.')

                    with col_principal:
                        st.markdown('<div class="content-box">', unsafe_allow_html=True)
                        st.subheader(f"📚 Referência: {infos['titulo']}")
                        
                        # ALTERADO: Ordem de exibição dos detalhes
                        st.write(f"Autor(es): {infos['autor']}")
                        st.write(f"Tipo: {infos['tipo']} | Ano: {infos['ano']}")
                        st.write(f"Tags: {infos['tags']}")
                        st.write(f"Localização Física: **{localizacao}**") # Localização após Tags
                        
                        with st.expander("Ver Resumo / Prévia Textual"):
                            st.write(resumo)

                        if caminho and str(caminho).startswith("http"):
                            st.link_button("☁️ Abrir no Google Drive em Nova Aba", caminho, type="primary")

                        st.markdown('</div>', unsafe_allow_html=True) 
                    
                    with col_lateral:
                        st.markdown('<div class="content-box">', unsafe_allow_html=True)
                        st.subheader("👁️ Prévia Visual do Documento")
                        if caminho and str(caminho).startswith("http"):
                            file_id = extract_file_id(caminho)
                            if file_id:
                                preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
                                st.components.v1.iframe(preview_url, height=780, scrolling=True) 
                            else:
                                st.warning("❌ Link do Drive inválido para prévia.")
                        else:
                            st.info("⚠️ Arquivo não vinculado ao Google Drive ou o link não foi preenchido.")
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                elif recurso_tipo == 'D': # DATASET EXTERNO (DADOS)
                    infos = df_datasets[df_datasets['id'] == original_id].iloc[0]
                    link_drive = infos['link_drive']
                    file_id = extract_file_id(link_drive)
                    download_link = create_drive_download_link(file_id)
                    
                    with col_principal:
                        st.markdown('<div class="content-box">', unsafe_allow_html=True)
                        st.subheader(f"📈 Dataset: {infos['titulo']}")
                        st.markdown(f"**Descrição/Fonte:** {infos['descricao']}")
                        st.markdown(f"**Data de Cadastro:** {infos['data_cadastro'][:10]}")
                        st.info("Este é um Dataset Externo. Use os links abaixo para visualização e download.")
                        
                        col_view, col_download = st.columns(2)
                        with col_view:
                            st.link_button("☁️ Visualizar no Drive", link_drive)
                        with col_download:
                            if download_link:
                                st.link_button("⬇️ Baixar Dataset", download_link, type="primary")
                            else:
                                st.error("Link de Drive inválido.")
                        
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                    with col_lateral:
                        st.markdown('<div class="content-box">', unsafe_allow_html=True)
                        st.subheader("🖼️ Prévia de Dados")
                        if file_id:
                            # Para planilhas e arquivos compatíveis, o iframe do Drive funciona como prévia.
                            preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
                            st.components.v1.iframe(preview_url, height=780, scrolling=True) 
                        else:
                            st.warning("Não é possível gerar a prévia. O link do Drive pode estar mal formatado.")
                        st.markdown('</div>', unsafe_allow_html=True)

        
        elif deve_exibir_resultados and df_unificado.empty:
            # --- ATIVA O LAYOUT DE BUSCA (REINICIA A PÁGINA COM o NOVO CSS) ---
            if not st.session_state['layout_buscado']:
                st.session_state['layout_buscado'] = True
                st.rerun() 
            # --- FIM DA ATIVAÇÃO DE LAYOUT ---
            st.warning(f"Nenhum item encontrado na Biblioteca ou nos Datasets para o termo pesquisado '{filtro_geral}' no tema '{tema_selecionado}'.")
            st.markdown('</div>', unsafe_allow_html=True) # Fecha content-box
        
        else:
            # Mensagem inicial quando nada foi buscado/filtrado (MENOS DESTAQUE)
            # Garante que o layout volte ao padrão grande se a busca foi limpa
            if st.session_state['layout_buscado']:
                 st.session_state['layout_buscado'] = False
                 st.rerun()
                 
            st.markdown('<p style="font-size:0.9rem; color:#555555; text-align:center;">Utilize a barra de pesquisa ou selecione um tema acima para iniciar a busca unificada na biblioteca e nos datasets.</p>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True) # Fecha content-box


# === PÁGINAS RESTRITAS (Sem alteração) ===

# === PÁGINA 2: GESTÃO DE REFERÊNCIAS (Edição em Bloco e Exclusão) ===
elif menu == "🔗 Gestão de Referências":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar a Gestão de Referências.")
        st.stop()
        
    st.title("🔗 Gestão de Referências (Planilha Editável)")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("Instruções: **Edite as células**, cole links do Drive em `caminho_arquivo` e preencha a **Localização Física**.")

    df_links = carregar_dados_bibliografia()
    
    if not df_links.empty:
        # Configurações da Tabela AgGrid
        gb = GridOptionsBuilder.from_dataframe(df_links)
        
        gb.configure_column("id", header_name="ID", editable=False, width=50)
        gb.configure_column("titulo", editable=True)
        gb.configure_column("autor", editable=True)
        gb.configure_column("tipo", editable=True, width=100) 
        gb.configure_column("ano", editable=True, width=70)  
        gb.configure_column("tags", editable=True)
        gb.configure_column("resumo", editable=True, width=200) 
        gb.configure_column("caminho_arquivo", header_name="Link Google Drive", editable=True, width=300)
        gb.configure_column("localizacao_fisica", header_name="Localização Física", editable=True, width=150)
        gb.configure_columns(['data_adicao'], hide=True)
        gridOptions = gb.build()

        grid_response = AgGrid(
            df_links,
            gridOptions=gridOptions,
            data_return_mode='AS_INPUT',
            update_mode=GridUpdateMode.VALUE_CHANGED, 
            fit_columns_on_grid_load=False,
            height=400, 
            width='100%',
            reload_data=True,
            key="aggrid_bibliografia_edit"
        )

        df_atualizado = grid_response['data']
        st.write("---")
        
        # BOTÃO SALVAR
        if st.button("💾 Salvar TODAS as Alterações no Banco de Dados Local", type="primary"):
            if update_all_data(df_atualizado):
                st.success("✅ Todos os dados foram salvos no arquivo minha_biblioteca.db!")
            else:
                st.error("Falha ao salvar. Verifique o terminal.")
                
        st.write("---")
        
        # Funcionalidade de Excluir
        st.subheader("⚠️ Excluir Referência Permanentemente")
        
        opcoes_delete = df_links.set_index('id')['titulo'].to_dict()
        
        col_del1, col_del2 = st.columns([3, 1])
        
        with col_del1:
            if opcoes_delete:
                id_delete = st.selectbox(
                    "Selecione o item para EXCLUIR:", 
                    options=opcoes_delete.keys(), 
                    format_func=lambda x: opcoes_delete[x] if x in opcoes_delete else x,
                    key="select_delete_biblio"
                )
            else:
                id_delete = None
                st.info("Nenhuma referência para excluir.")


        with col_del2:
            st.write(" ")
            if id_delete and st.button("EXCLUIR SELECIONADO", type="primary"): 
                delete_reference(id_delete)
                st.success(f"Item ID {id_delete} excluído com sucesso!")
                st.rerun() 

    else:
        st.info("Nenhum dado para gerenciar.")
    
    st.markdown('</div>', unsafe_allow_html=True)


# === PÁGINA 3: CADASTRO MANUAL (Inserir Novo Item) ===
elif menu == "➕ Cadastro Manual":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Cadastro Manual.")
        st.stop()
        
    st.title("➕ Cadastrar Nova Referência")
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("Use esta página para adicionar livros e artigos diretamente ao seu banco de dados.")

    with st.form("form_cadastro"):
        col1, col2 = st.columns(2)
        with col1:
            titulo = st.text_input("Título da Obra *")
            autor = st.text_input("Autor (Sobrenome, Nome)")
            tipo = st.selectbox("Tipo:", ["Livro", "Artigo", "Capítulo", "Tese", "Relatório", "Outro"])
        
        with col2:
            ano = st.number_input("Ano de Publicação", min_value=1900, max_value=2100, step=1, value=2023)
            tags = st.text_input("Tags (separadas por vírgula, ex: Política, Economia, Geossistema)")
            
            # Reorganizado para ficar abaixo de Tags
            localizacao_fisica = st.text_input("Localização Física")
            
            link_drive = st.text_input("Link do Google Drive (opcional)")
        
        resumo = st.text_area("Resumo / Prévia")
        
        enviado = st.form_submit_button("Salvar Referência 💾", type="primary")

        if enviado:
            if titulo and autor:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO bibliografia (titulo, autor, tipo, ano, tags, caminho_arquivo, resumo, localizacao_fisica)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (titulo, autor, tipo, ano, tags, link_drive, resumo, localizacao_fisica))
                    conn.commit()
                    st.success(f"Referência '{titulo}' salva com sucesso! ID: {cursor.lastrowid}")
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")
                finally:
                    conn.close()
            else:
                st.warning("Preencha pelo menos o Título e o Autor.")
    
    st.markdown('</div>', unsafe_allow_html=True) 


# === PÁGINA 4: DASHBOARD ===
elif menu == "📊 Dashboard":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Dashboard.")
        st.stop()
        
    st.title("📊 Estatísticas da Biblioteca")
    
    if os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        
        st.markdown('<div class="content-box">', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Por Tipo (Bibliografia)")
            try:
                dados_tipo = pd.read_sql_query("SELECT tipo, COUNT(*) as qtd FROM bibliografia GROUP BY tipo", conn)
                if not dados_tipo.empty:
                    fig, ax = plt.subplots()
                    ax.pie(dados_tipo['qtd'], labels=dados_tipo['tipo'], autopct='%1.1f%%', startangle=90)
                    st.pyplot(fig) 
                else:
                    st.write("Sem dados.")
            except:
                st.write("Erro ao ler dados.")

        with col2:
            st.subheader("Publicações por Ano (Últimos 15)")
            try:
                dados_ano = pd.read_sql_query("SELECT ano, COUNT(*) as qtd FROM bibliografia WHERE ano > 1900 GROUP BY ano ORDER BY ano DESC LIMIT 15", conn)
                if not dados_ano.empty:
                    dados_ano['ano'] = pd.to_numeric(dados_ano['ano'], errors='coerce').fillna(0).astype(int)
                    st.bar_chart(dados_ano.set_index('ano'))
                else:
                    st.write("Sem dados.")
            except:
                st.write("Erro ao ler dados.")
                
        conn.close()
        st.markdown('</div>', unsafe_allow_html=True) 
    else:
        st.error("Banco de dados não encontrado.")


# === PÁGINA 5: CADASTRO DE DADOS EXTERNOS (Restrito) ===
elif menu == "💾 Cadastro de Dados Externos":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Cadastro de Dados Externos.")
        st.stop()
        
    st.title("💾 Cadastro de Datasets Externos")
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("""
        Cadastre novos datasets (populacionais, econômicos, etc.) vinculando-os a um **link de compartilhamento do Google Drive**. 
        Certifique-se de que o link do Drive esteja configurado como **público** (qualquer pessoa com o link pode visualizar/baixar) para que o download funcione na área pública.
    """)

    with st.form("form_cadastro_dados"):
        titulo = st.text_input("Título do Dataset (Ex: População de SP - 2010/2020) *")
        link_drive = st.text_input("Link de Compartilhamento do Google Drive (CSV ou XLSX) *")
        descricao = st.text_area("Descrição e Fonte (Ex: Dados IBGE, Tratados pelo LABEUR)")
        
        enviado = st.form_submit_button("Salvar Dataset 💾", type="primary")

        if enviado:
            if titulo and link_drive:
                
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO dados_externos (titulo, descricao, link_drive)
                        VALUES (?, ?, ?)
                    """, (titulo, descricao, link_drive))
                    conn.commit()
                    st.success(f"Dataset '{titulo}' cadastrado com sucesso e linkado ao Google Drive! Será exibido na área pública.")
                except Exception as e:
                    st.error(f"Erro ao salvar no DB: {e}")
                finally:
                    conn.close()
            else:
                st.warning("Preencha pelo menos o Título e o Link do Google Drive.")
    
    st.markdown('</div>', unsafe_allow_html=True)


# --- CRÉDITOS NO RODAPÉ ---
st.markdown(
    f"""
    <div class="footer-custom">
        <span>Desenvolvido por Gustavo Miguel Reis | LABEUR - Laboratório de Estudos Urbanos e Regionais</span>
        <br>
        <span>
            Fale Conosco: Dúvidas, sugestões, reclamações e elogios? Envie e-mail para labeur.operacional@gmail.com
        </span>
    </div>
    """, 
    unsafe_allow_html=True
)