import streamlit as st
import sqlite3
import pandas as pd
import os
import matplotlib.pyplot as plt
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode 
import re 
import hashlib 
import io 
import requests 
from io import BytesIO 
from datetime import datetime
# IMPORTAÇÃO: Funções de processamento e sugestão devem estar no pdf_processor.py
from pdf_processor import extract_text_from_drive_link, process_pdf_bytes, suggest_metadata, extract_file_id 
# Importamos extract_file_id do pdf_processor.py para usar na prévia

# --- Variáveis de Configuração e Segurança ---
# NOTA: O tema deve ser forçado pelo arquivo .streamlit/config.toml
st.set_page_config(page_title="LABEUR - Biblioteca Digital", layout="wide")
DB_NAME = "minha_biblioteca.db"
# SENHA FIXA: Hash da senha 'labeur.operacional.senha'
CORRECT_PASSWORD_HASH = hashlib.sha256("labeur.operacional.senha".encode()).hexdigest() 

# Inicializa o estado de visualização do layout (False = Layout Inicial Grande)
if 'layout_buscado' not in st.session_state:
    st.session_state['layout_buscado'] = False
if 'selecao_aggrid_row' not in st.session_state:
    st.session_state['selecao_aggrid_row'] = []
if 'extracted_text' not in st.session_state:
    st.session_state['extracted_text'] = None
if 'suggested_data' not in st.session_state:
    st.session_state['suggested_data'] = {}


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

# --- FUNÇÕES DE EDIÇÃO/EXCLUSÃO PARA BIBLIOGRAFIA ---

def update_all_data(df_atualizado):
    """Salva todas as colunas alteradas da tabela bibliografia de volta no SQLite."""
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
        st.error(f"Erro ao salvar no banco de dados (bibliografia): {e}")
        return False
    finally:
        conn.close()

def delete_reference(id_livro):
    """Exclui uma referência da tabela bibliografia."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bibliografia WHERE id = ?", (id_livro,))
    conn.commit()
    conn.close()

# --- FUNÇÕES DE EDIÇÃO/EXCLUSÃO PARA DATASETS EXTERNOS ---

def update_all_data_datasets(df_atualizado):
    """Salva todas as colunas alteradas da tabela dados_externos de volta no SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    sql_update = "UPDATE dados_externos SET titulo=?, descricao=?, link_drive=? WHERE id=?"
    
    updates = [
        (row['titulo'], row['descricao'], row['link_drive'], row['id'])
        for index, row in df_atualizado.iterrows()
    ]
    
    try:
        cursor.executemany(sql_update, updates)
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no banco de dados (datasets): {e}")
        return False
    finally:
        conn.close()

def delete_dataset(id_dataset):
    """Exclui um item da tabela dados_externos."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dados_externos WHERE id = ?", (id_dataset,))
    conn.commit()
    conn.close()

# --- Funções auxiliares (MANTIDAS NO APP.PY POR SEREM GENÉRICAS) ---
# NOTA: extract_file_id foi movida para pdf_processor para evitar redundância, mas mantemos o nome original aqui para consistência.
# A importação no topo já cobre isso.
# def extract_file_id(drive_link): ...
# def create_drive_download_link(file_id): ...


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
            
    st.sidebar.subheader("Acesso Restrito")
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
    
    /* FORÇANDO TEMA CLARO */
    .stApp {{ background-color: #fdfdfd; font-family: 'Poppins', sans-serif; }}
    [data-testid="stSidebar"] {{ background-color: #ffffff; box-shadow: 2px 0 10px rgba(0,0,0,0.1); }}
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] h1 {{ color: #1f1f1f !important; }}
    h1, h2, h3, h4, .st-b5, [data-testid="stText"], [data-testid="stMarkdownContainer"] {{ color: #1f1f1f !important; }}

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
st.markdown("""
<style>
    /* MÁXIMO DE DESTAQUE FORÇADO: Barra de pesquisa */
    .search-container { 
        max-width: 900px; 
        margin: 30px auto 40px auto; 
        text-align: center; 
    }
    
    /* FORÇANDO O TAMANHO DO LABEL (Pesquisa por...) */
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
opcoes_menu = ["Biblioteca Principal"]

if check_password():
    # ITENS APENAS PARA USUÁRIOS LOGADOS
    opcoes_menu.extend([
        "Cadastro Automatizado (PDF)", 
        "Gestão de Referências",
        "Gestão de Dados Externos",
        "Cadastro Manual",
        "Cadastro de Dados Externos",
        "Dashboard"
    ])
    st.sidebar.success("Acesso total liberado.")
else:
    # SE NÃO ESTIVER LOGADO, SÓ MOSTRA O MENU PRINCIPAL
    pass # Deixa apenas o "Biblioteca Principal"

st.sidebar.title("Navegação")
menu = st.sidebar.radio("Ir para:", opcoes_menu)


# =========================================================================
# === PÁGINA: CADASTRO AUTOMATIZADO (PDF) (AGORA PROTEGIDA) ================
# =========================================================================

if menu == "Cadastro Automatizado (PDF)":
    # Verifica login no início da página restrita
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Cadastro Automatizado.")
        st.stop()
        
    st.title("Cadastro Automatizado de Referência (PDF)")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("""
        Use esta ferramenta para extrair texto de um PDF e preparar metadados (Título, Autor, Ano). 
        Você pode fazer upload de um arquivo local ou usar um link de **download direto** do Google Drive.
    """)

    uploaded_file = st.file_uploader("1. Faça Upload de um PDF local:", type="pdf")
    link_drive_input = st.text_input("2. OU insira um Link de Download Direto do Google Drive:")
    
    process_button = st.button("Processar Arquivo para Extração de Texto e Sugestões", type="primary")

    if process_button:
        st.session_state['extracted_text'] = None
        st.session_state['suggested_data'] = {}
        
        raw_text = None
        
        with st.spinner("Processando o PDF e extraindo metadados..."):
            if uploaded_file is not None:
                # Processa o arquivo carregado (lido como BytesIO)
                pdf_bytes = BytesIO(uploaded_file.read())
                raw_text = process_pdf_bytes(pdf_bytes)
                st.session_state['suggested_data']['caminho_arquivo'] = "Local Upload"
            
            elif link_drive_input:
                # Processa o link do Drive (requer download)
                raw_text = extract_text_from_drive_link(link_drive_input)
                # O link direto precisa ser armazenado para a prévia
                st.session_state['suggested_data']['caminho_arquivo'] = link_drive_input
            
            else:
                st.warning("Por favor, forneça um arquivo por upload ou um link do Google Drive.")
        
        if raw_text and not raw_text.startswith("Erro"):
            st.session_state['extracted_text'] = raw_text
            
            # --- INTEGRAÇÃO DA FUNÇÃO DE SUGESTÃO DE METADADOS ---
            
            if len(raw_text) > 100: 
                try:
                    suggested_data = suggest_metadata(raw_text) 
                    st.session_state['suggested_data'].update(suggested_data)
                    st.success("Extração de texto e sugestões de metadados concluídas! Revise ao lado.")
                except Exception as e:
                    st.error(f"Erro na sugestão automática de metadados. Revise manualmente. Erro: {e}")
                    # Fallback
                    st.session_state['suggested_data'].update({
                        'titulo': "ERRO NA EXTRAÇÃO. Revise manualmente.",
                        'autor': "",
                        'ano': datetime.now().year,
                        'tipo': "Artigo",
                        'tags': "Erro, Revisar",
                        'resumo': raw_text[:1500] if len(raw_text) > 1500 else raw_text
                    })
            else:
                 st.session_state['suggested_data'].update({
                    'titulo': "Texto muito curto, insira manualmente",
                    'autor': "",
                    'ano': datetime.now().year,
                    'tipo': "Artigo",
                    'tags': "",
                    'resumo': raw_text
                })
            
            # Exibe o painel de edição
            st.rerun() 
        
        elif raw_text and raw_text.startswith("Erro"):
             st.error(raw_text)

    if st.session_state['extracted_text']:
        st.markdown("---")
        st.subheader("3. Revisar e Confirmar Metadados")
        
        col_sugestoes, col_preview = st.columns([1, 1]) # Dividindo em colunas
        
        sdata = st.session_state['suggested_data']
        caminho = sdata.get('caminho_arquivo', '')

        with col_sugestoes:
            st.info("Os campos foram preenchidos pela IA. Corrija-os e clique em Salvar.")
            
            with st.form("form_sugestao_cadastro"):
                
                col_f1, col_f2 = st.columns(2)
                
                with col_f1:
                    titulo_s = st.text_input("Título Sugerido *", value=sdata.get('titulo', ''))
                    autor_s = st.text_input("Autor(es) Sugerido", value=sdata.get('autor', ''))
                    tipo_s = st.selectbox("Tipo Sugerido", options=["Livro", "Artigo", "Capítulo", "Tese", "Relatório", "Outro"], index=["Livro", "Artigo", "Capítulo", "Tese", "Relatório", "Outro"].index(sdata.get('tipo', 'Artigo')))
                
                with col_f2:
                    ano_s = st.number_input("Ano Sugerido", min_value=1900, max_value=2100, step=1, value=sdata.get('ano', datetime.now().year))
                    tags_s = st.text_input("Tags Sugeridas (Separar por vírgula)", value=sdata.get('tags', ''))
                    localizacao_s = st.text_input("Localização Física", value=sdata.get('localizacao_fisica', ''))
                
                resumo_s = st.text_area("Resumo Sugerido", value=sdata.get('resumo', ''), height=300)
                
                st.caption(f"Caminho do Arquivo: {caminho if caminho != 'Local Upload' else 'Arquivo carregado localmente'}")

                salvar_sugestao = st.form_submit_button("Salvar Referência Automatizada", type="primary")

                if salvar_sugestao:
                    # Lógica de salvar no banco de dados
                    conn = get_connection()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT INTO bibliografia (titulo, autor, tipo, ano, tags, caminho_arquivo, resumo, localizacao_fisica)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (titulo_s, autor_s, tipo_s, ano_s, tags_s, caminho if caminho != 'Local Upload' else '', resumo_s, localizacao_s))
                        conn.commit()
                        st.success(f"Referência '{titulo_s}' salva com sucesso! ID: {cursor.lastrowid}")
                        # Limpa o estado após salvar
                        st.session_state['extracted_text'] = None
                        st.session_state['suggested_data'] = {}
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
                    finally:
                        conn.close()

        with col_preview:
            st.subheader("Prévia do Documento")
            
            if caminho and caminho != "Local Upload":
                # Se o link do Drive existe, mostra o iframe
                file_id = extract_file_id(caminho)
                if file_id:
                    preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
                    st.components.v1.iframe(preview_url, height=750, scrolling=True) 
                else:
                    st.warning("Link do Drive inválido para prévia visual.")
            elif caminho == "Local Upload":
                 st.info("Prévia indisponível para arquivos carregados localmente após o processamento. Consulte o texto extraído abaixo.")
            else:
                 st.info("Nenhum link de Drive disponível para prévia.")

        with st.expander("Ver Texto Completo Extraído (Para Revisão da IA)"):
            st.code(st.session_state['extracted_text'])
    
    st.markdown('</div>', unsafe_allow_import streamlit as st
import sqlite3
import pandas as pd
import os
import matplotlib.pyplot as plt
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode 
import re 
import hashlib 
import io 
import requests 
from io import BytesIO 
from datetime import datetime
# IMPORTAÇÃO: Funções de processamento e sugestão devem estar no pdf_processor.py
from pdf_processor import extract_text_from_drive_link, process_pdf_bytes, suggest_metadata, extract_file_id 
# Importamos extract_file_id do pdf_processor.py para usar na prévia

# --- Variáveis de Configuração e Segurança ---
# NOTA: O tema deve ser forçado pelo arquivo .streamlit/config.toml
st.set_page_config(page_title="LABEUR - Biblioteca Digital", layout="wide")
DB_NAME = "minha_biblioteca.db"
# SENHA FIXA: Hash da senha 'labeur.operacional.senha'
CORRECT_PASSWORD_HASH = hashlib.sha256("labeur.operacional.senha".encode()).hexdigest() 

# Inicializa o estado de visualização do layout (False = Layout Inicial Grande)
if 'layout_buscado' not in st.session_state:
    st.session_state['layout_buscado'] = False
if 'selecao_aggrid_row' not in st.session_state:
    st.session_state['selecao_aggrid_row'] = []
if 'extracted_text' not in st.session_state:
    st.session_state['extracted_text'] = None
if 'suggested_data' not in st.session_state:
    st.session_state['suggested_data'] = {}


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

# --- FUNÇÕES DE EDIÇÃO/EXCLUSÃO PARA BIBLIOGRAFIA ---

def update_all_data(df_atualizado):
    """Salva todas as colunas alteradas da tabela bibliografia de volta no SQLite."""
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
        st.error(f"Erro ao salvar no banco de dados (bibliografia): {e}")
        return False
    finally:
        conn.close()

def delete_reference(id_livro):
    """Exclui uma referência da tabela bibliografia."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bibliografia WHERE id = ?", (id_livro,))
    conn.commit()
    conn.close()

# --- FUNÇÕES DE EDIÇÃO/EXCLUSÃO PARA DATASETS EXTERNOS ---

def update_all_data_datasets(df_atualizado):
    """Salva todas as colunas alteradas da tabela dados_externos de volta no SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    sql_update = "UPDATE dados_externos SET titulo=?, descricao=?, link_drive=? WHERE id=?"
    
    updates = [
        (row['titulo'], row['descricao'], row['link_drive'], row['id'])
        for index, row in df_atualizado.iterrows()
    ]
    
    try:
        cursor.executemany(sql_update, updates)
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no banco de dados (datasets): {e}")
        return False
    finally:
        conn.close()

def delete_dataset(id_dataset):
    """Exclui um item da tabela dados_externos."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dados_externos WHERE id = ?", (id_dataset,))
    conn.commit()
    conn.close()

# --- Funções auxiliares (MANTIDAS NO APP.PY POR SEREM GENÉRICAS) ---
# NOTA: extract_file_id foi movida para pdf_processor para evitar redundância, mas mantemos o nome original aqui para consistência.
# A importação no topo já cobre isso.
# def extract_file_id(drive_link): ...
# def create_drive_download_link(file_id): ...


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
            
    st.sidebar.subheader("Acesso Restrito")
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
    
    /* FORÇANDO TEMA CLARO */
    .stApp {{ background-color: #fdfdfd; font-family: 'Poppins', sans-serif; }}
    [data-testid="stSidebar"] {{ background-color: #ffffff; box-shadow: 2px 0 10px rgba(0,0,0,0.1); }}
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] h1 {{ color: #1f1f1f !important; }}
    h1, h2, h3, h4, .st-b5, [data-testid="stText"], [data-testid="stMarkdownContainer"] {{ color: #1f1f1f !important; }}

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
st.markdown("""
<style>
    /* MÁXIMO DE DESTAQUE FORÇADO: Barra de pesquisa */
    .search-container { 
        max-width: 900px; 
        margin: 30px auto 40px auto; 
        text-align: center; 
    }
    
    /* FORÇANDO O TAMANHO DO LABEL (Pesquisa por...) */
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
opcoes_menu = ["Biblioteca Principal"]

if check_password():
    # ITENS APENAS PARA USUÁRIOS LOGADOS
    opcoes_menu.extend([
        "Cadastro Automatizado (PDF)", 
        "Gestão de Referências",
        "Gestão de Dados Externos",
        "Cadastro Manual",
        "Cadastro de Dados Externos",
        "Dashboard"
    ])
    st.sidebar.success("Acesso total liberado.")
else:
    # SE NÃO ESTIVER LOGADO, SÓ MOSTRA O MENU PRINCIPAL
    pass # Deixa apenas o "Biblioteca Principal"

st.sidebar.title("Navegação")
menu = st.sidebar.radio("Ir para:", opcoes_menu)


# =========================================================================
# === PÁGINA: CADASTRO AUTOMATIZADO (PDF) (AGORA PROTEGIDA) ================
# =========================================================================

if menu == "Cadastro Automatizado (PDF)":
    # Verifica login no início da página restrita
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Cadastro Automatizado.")
        st.stop()
        
    st.title("Cadastro Automatizado de Referência (PDF)")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("""
        Use esta ferramenta para extrair texto de um PDF e preparar metadados (Título, Autor, Ano). 
        Você pode fazer upload de um arquivo local ou usar um link de **download direto** do Google Drive.
    """)

    uploaded_file = st.file_uploader("1. Faça Upload de um PDF local:", type="pdf")
    link_drive_input = st.text_input("2. OU insira um Link de Download Direto do Google Drive:")
    
    process_button = st.button("Processar Arquivo para Extração de Texto e Sugestões", type="primary")

    if process_button:
        st.session_state['extracted_text'] = None
        st.session_state['suggested_data'] = {}
        
        raw_text = None
        
        with st.spinner("Processando o PDF e extraindo metadados..."):
            if uploaded_file is not None:
                # Processa o arquivo carregado (lido como BytesIO)
                pdf_bytes = BytesIO(uploaded_file.read())
                raw_text = process_pdf_bytes(pdf_bytes)
                st.session_state['suggested_data']['caminho_arquivo'] = "Local Upload"
            
            elif link_drive_input:
                # Processa o link do Drive (requer download)
                raw_text = extract_text_from_drive_link(link_drive_input)
                # O link direto precisa ser armazenado para a prévia
                st.session_state['suggested_data']['caminho_arquivo'] = link_drive_input
            
            else:
                st.warning("Por favor, forneça um arquivo por upload ou um link do Google Drive.")
        
        if raw_text and not raw_text.startswith("Erro"):
            st.session_state['extracted_text'] = raw_text
            
            # --- INTEGRAÇÃO DA FUNÇÃO DE SUGESTÃO DE METADADOS ---
            
            if len(raw_text) > 100: 
                try:
                    suggested_data = suggest_metadata(raw_text) 
                    st.session_state['suggested_data'].update(suggested_data)
                    st.success("Extração de texto e sugestões de metadados concluídas! Revise ao lado.")
                except Exception as e:
                    st.error(f"Erro na sugestão automática de metadados. Revise manualmente. Erro: {e}")
                    # Fallback
                    st.session_state['suggested_data'].update({
                        'titulo': "ERRO NA EXTRAÇÃO. Revise manualmente.",
                        'autor': "",
                        'ano': datetime.now().year,
                        'tipo': "Artigo",
                        'tags': "Erro, Revisar",
                        'resumo': raw_text[:1500] if len(raw_text) > 1500 else raw_text
                    })
            else:
                 st.session_state['suggested_data'].update({
                    'titulo': "Texto muito curto, insira manualmente",
                    'autor': "",
                    'ano': datetime.now().year,
                    'tipo': "Artigo",
                    'tags': "",
                    'resumo': raw_text
                })
            
            # Exibe o painel de edição
            st.rerun() 
        
        elif raw_text and raw_text.startswith("Erro"):
             st.error(raw_text)

    if st.session_state['extracted_text']:
        st.markdown("---")
        st.subheader("3. Revisar e Confirmar Metadados")
        
        col_sugestoes, col_preview = st.columns([1, 1]) # Dividindo em colunas
        
        sdata = st.session_state['suggested_data']
        caminho = sdata.get('caminho_arquivo', '')

        with col_sugestoes:
            st.info("Os campos foram preenchidos pela IA. Corrija-os e clique em Salvar.")
            
            with st.form("form_sugestao_cadastro"):
                
                col_f1, col_f2 = st.columns(2)
                
                with col_f1:
                    titulo_s = st.text_input("Título Sugerido *", value=sdata.get('titulo', ''))
                    autor_s = st.text_input("Autor(es) Sugerido", value=sdata.get('autor', ''))
                    tipo_s = st.selectbox("Tipo Sugerido", options=["Livro", "Artigo", "Capítulo", "Tese", "Relatório", "Outro"], index=["Livro", "Artigo", "Capítulo", "Tese", "Relatório", "Outro"].index(sdata.get('tipo', 'Artigo')))
                
                with col_f2:
                    ano_s = st.number_input("Ano Sugerido", min_value=1900, max_value=2100, step=1, value=sdata.get('ano', datetime.now().year))
                    tags_s = st.text_input("Tags Sugeridas (Separar por vírgula)", value=sdata.get('tags', ''))
                    localizacao_s = st.text_input("Localização Física", value=sdata.get('localizacao_fisica', ''))
                
                resumo_s = st.text_area("Resumo Sugerido", value=sdata.get('resumo', ''), height=300)
                
                st.caption(f"Caminho do Arquivo: {caminho if caminho != 'Local Upload' else 'Arquivo carregado localmente'}")

                salvar_sugestao = st.form_submit_button("Salvar Referência Automatizada", type="primary")

                if salvar_sugestao:
                    # Lógica de salvar no banco de dados
                    conn = get_connection()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT INTO bibliografia (titulo, autor, tipo, ano, tags, caminho_arquivo, resumo, localizacao_fisica)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (titulo_s, autor_s, tipo_s, ano_s, tags_s, caminho if caminho != 'Local Upload' else '', resumo_s, localizacao_s))
                        conn.commit()
                        st.success(f"Referência '{titulo_s}' salva com sucesso! ID: {cursor.lastrowid}")
                        # Limpa o estado após salvar
                        st.session_state['extracted_text'] = None
                        st.session_state['suggested_data'] = {}
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
                    finally:
                        conn.close()

        with col_preview:
            st.subheader("Prévia do Documento")
            
            if caminho and caminho != "Local Upload":
                # Se o link do Drive existe, mostra o iframe
                file_id = extract_file_id(caminho)
                if file_id:
                    preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
                    st.components.v1.iframe(preview_url, height=750, scrolling=True) 
                else:
                    st.warning("Link do Drive inválido para prévia visual.")
            elif caminho == "Local Upload":
                 st.info("Prévia indisponível para arquivos carregados localmente após o processamento. Consulte o texto extraído abaixo.")
            else:
                 st.info("Nenhum link de Drive disponível para prévia.")

        with st.expander("Ver Texto Completo Extraído (Para Revisão da IA)"):
            st.code(st.session_state['extracted_text'])
    
    st.markdown('</div>', unsafe_allow_html=True) 

# =========================================================================
# === OUTRAS PÁGINAS (CÓDIGO OMITIDO POR SER REPETIDO) =====================
# =========================================================================
# ... (Código para Biblioteca Principal, Gestão de Referências, Gestão de Dados Externos, Cadastro Manual, Cadastro de Dados Externos, Dashboard e Rodapé)
# (Mantenha o restante do seu app.py intacto, pois as alterações ocorreram apenas acima)
# --------------------------------------------------------------------------

# Por favor, note que o código das outras páginas (Gestão, Dashboard, etc.) foi
# omitido aqui para brevidade. Certifique-se de usar seu arquivo app.py completo!

# --------------------------------------------------------------------------html=True) 

# =========================================================================
# === OUTRAS PÁGINAS (CÓDIGO OMITIDO POR SER REPETIDO) =====================
# =========================================================================
# ... (Código para Biblioteca Principal, Gestão de Referências, Gestão de Dados Externos, Cadastro Manual, Cadastro de Dados Externos, Dashboard e Rodapé)
# (Mantenha o restante do seu app.py intacto, pois as alterações ocorreram apenas acima)
# --------------------------------------------------------------------------

# Por favor, note que o código das outras páginas (Gestão, Dashboard, etc.) foi
# omitido aqui para brevidade. Certifique-se de usar seu arquivo app.py completo!

# --------------------------------------------------------------------------