import streamlit as st
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
import gspread # NOVO: Para interagir com Google Sheets
from google.oauth2.service_account import Credentials # NOVO: Para autenticação

# IMPORTAÇÃO DOS MÓDULOS DE PROCESSAMENTO E COLETA
from pdf_processor import extract_text_from_drive_link, process_pdf_bytes, suggest_metadata, extract_file_id 
from data_collector import unified_data_search 

# --- Variáveis de Configuração e Segurança ---
st.set_page_config(page_title="LABEUR - Biblioteca Digital", layout="wide")

# ARQUIVO DE CREDENCIAIS (Service Account) - DEVE ESTAR NA RAIZ DO PROJETO
CREDENCIAL_FILE = 'gdrive_credentials.json'
SPREADSHEET_ID = "1A8EhdUs9ow5tywxY_xvDHACYezTf_AuQ39H8y3Zqtrc"
SHEET_BIBLIOGRAFIA_NAME = "bibliografia" # Nome da Aba 1
SHEET_DATASETS_NAME = "dados_externos" # Nome da Aba 2

# SENHA FIXA: Hash da senha 'labeur.operacional.senha'
CORRECT_PASSWORD_HASH = hashlib.sha256("labeur.operacional.senha".encode()).hexdigest() 

# NENHUM DRIVE_CONTROL_FILE_URL NECESSÁRIO AQUI, POIS USAMOS O SPREADSHEET_ID

# --- Inicialização de Estados da Sessão ---
if 'layout_buscado' not in st.session_state:
    st.session_state['layout_buscado'] = False
if 'selecao_aggrid_row' not in st.session_state:
    st.session_state['selecao_aggrid_row'] = []
if 'extracted_text' not in st.session_state:
    st.session_state['extracted_text'] = None
if 'suggested_data' not in st.session_state:
    st.session_state['suggested_data'] = {}
if 'logs' not in st.session_state:
    st.session_state['logs'] = {}
if 'search_results_online' not in st.session_state:
    st.session_state['search_results_online'] = []
if 'selected_online_item' not in st.session_state:
    st.session_state['selected_online_item'] = None
if 'last_online_query' not in st.session_state:
    st.session_state['last_online_query'] = "mineração"


# --- Funções de Conexão e Backend (Google Sheets) ---

@st.cache_resource(ttl=3600) # Mantém a conexão ativa por 1h
def connect_to_sheets():
    """Conecta ao Google Sheets usando a Service Account."""
    if not os.path.exists(CREDENCIAL_FILE):
        st.error(f"Erro: Arquivo de credenciais '{CREDENCIAL_FILE}' não encontrado. O Streamlit não pode se conectar ao Google Sheets.")
        return None
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(CREDENCIAL_FILE, scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        return spreadsheet
    except Exception as e:
        st.error(f"Falha na autenticação ou conexão com o Google Sheets. Verifique o compartilhamento do ID: {SPREADSHEET_ID}. Erro: {e}")
        return None

# Definindo o esquema obrigatório (usado para salvar novos dados)
SCHEMA_BIBLIO = ["id", "titulo", "autor", "tipo", "ano", "tags", "caminho_arquivo", "resumo", "localizacao_fisica", "data_adicao"]
SCHEMA_DATASET = ["id", "titulo", "descricao", "link_drive", "data_cadastro"]

@st.cache_data(ttl=60) # Atualiza o cache a cada 60 segundos
def carregar_dados_bibliografia():
    """Lê a aba 'bibliografia' do Google Sheets e retorna um DataFrame."""
    spreadsheet = connect_to_sheets()
    if not spreadsheet: return pd.DataFrame()
    try:
        worksheet = spreadsheet.worksheet(SHEET_BIBLIOGRAFIA_NAME)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Garante que as colunas essenciais existem, adicionando se necessário (para compatibilidade)
        for col in SCHEMA_BIBLIO:
            if col not in df.columns:
                 df[col] = None 
        
        # Adiciona um ID temporário se não houver (para visualização no AgGrid)
        if 'id' not in df.columns or df['id'].empty or not pd.api.types.is_numeric_dtype(df['id']):
             df['id'] = range(1, len(df) + 1)
        
        return df
    except gspread.WorksheetNotFound:
        st.warning(f"Aba '{SHEET_BIBLIOGRAFIA_NAME}' não encontrada na Planilha Mestra. Crie-a.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar dados da aba Bibliografia: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def carregar_datasets_externos():
    """Lê a aba 'dados_externos' do Google Sheets e retorna um DataFrame."""
    spreadsheet = connect_to_sheets()
    if not spreadsheet: return pd.DataFrame()
    try:
        worksheet = spreadsheet.worksheet(SHEET_DATASETS_NAME)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        for col in SCHEMA_DATASET:
            if col not in df.columns:
                 df[col] = None 
        
        if 'id' not in df.columns or df['id'].empty or not pd.api.types.is_numeric_dtype(df['id']):
             df['id'] = range(1, len(df) + 1)
             
        return df
    except gspread.WorksheetNotFound:
        st.warning(f"Aba '{SHEET_DATASETS_NAME}' não encontrada na Planilha Mestra. Crie-a.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar dados da aba Datasets: {e}")
        return pd.DataFrame()

# --- Funções de Escrita e CRUD (Substituindo SQLite) ---

# Função auxiliar para garantir que o dataframe tem o esquema correto
def _prepare_df_for_sheets(df, schema):
    df = df.copy()
    # Garante que todas as colunas do esquema estão presentes
    for col in schema:
        if col not in df.columns:
            df[col] = None
    # Seleciona apenas as colunas na ordem correta
    return df[schema]

def update_all_data(df_atualizado):
    """Sobrescreve TODA a aba 'bibliografia' com os dados atualizados."""
    spreadsheet = connect_to_sheets()
    if not spreadsheet: return False
    try:
        df_clean = _prepare_df_for_sheets(df_atualizado, SCHEMA_BIBLIO)
        worksheet = spreadsheet.worksheet(SHEET_BIBLIOGRAFIA_NAME)
        worksheet.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
        st.cache_data.clear() # Limpa o cache para forçar nova leitura
        return True
    except Exception as e:
        st.error(f"Erro ao salvar dados (bibliografia) no Google Sheets: {e}")
        return False

def delete_reference(id_livro):
    """Exclui uma referência no Google Sheets pelo ID."""
    df = carregar_dados_bibliografia()
    if df.empty: return

    # O Sheets usa indexação baseada em 1, e a linha 1 é o header.
    # O Gspread usa row_index (2 para a primeira linha de dados).
    try:
        row_to_delete = df[df['id'] == id_livro].index.tolist()
        if not row_to_delete: return
        
        sheet = connect_to_sheets().worksheet(SHEET_BIBLIOGRAFIA_NAME)
        sheet.delete_rows(row_to_delete[0] + 2) # +2: 0-indexed para 1-indexed (linha de dados)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao excluir referência no Google Sheets: {e}")

def append_new_reference(data):
    """Adiciona uma nova linha (referência) à aba 'bibliografia'."""
    spreadsheet = connect_to_sheets()
    if not spreadsheet: return False
    try:
        # Prepara os dados na ordem do SCHEMA
        new_row = [
            data.get('titulo'), data.get('autor'), data.get('tipo'), data.get('ano'), 
            data.get('tags'), data.get('caminho_arquivo'), data.get('resumo'), 
            data.get('localizacao_fisica'), datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        worksheet = spreadsheet.worksheet(SHEET_BIBLIOGRAFIA_NAME)
        worksheet.append_row(new_row, value_input_option='USER_ENTERED')
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erro ao adicionar nova referência: {e}")
        return False

# --- Funções de CRUD para Datasets (Implementação similar) ---

def update_all_data_datasets(df_atualizado):
    """Sobrescreve TODA a aba 'dados_externos' com os dados atualizados."""
    spreadsheet = connect_to_sheets()
    if not spreadsheet: return False
    try:
        df_clean = _prepare_df_for_sheets(df_atualizado, SCHEMA_DATASET)
        worksheet = spreadsheet.worksheet(SHEET_DATASETS_NAME)
        worksheet.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar dados (datasets) no Google Sheets: {e}")
        return False
        
def append_new_dataset(data):
    """Adiciona uma nova linha (dataset) à aba 'dados_externos'."""
    spreadsheet = connect_to_sheets()
    if not spreadsheet: return False
    try:
        # Prepara os dados na ordem do SCHEMA
        new_row = [
            data.get('titulo'), data.get('descricao'), data.get('link_drive'), 
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        worksheet = spreadsheet.worksheet(SHEET_DATASETS_NAME)
        worksheet.append_row(new_row, value_input_option='USER_ENTERED')
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Erro ao adicionar novo dataset: {e}")
        return False

def delete_dataset(id_dataset):
    """Exclui um item da tabela dados_externos no Google Sheets."""
    df = carregar_datasets_externos()
    if df.empty: return
    try:
        row_to_delete = df[df['id'] == id_dataset].index.tolist()
        if not row_to_delete: return
        
        sheet = connect_to_sheets().worksheet(SHEET_DATASETS_NAME)
        sheet.delete_rows(row_to_delete[0] + 2) 
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao excluir dataset no Google Sheets: {e}")


# --- FUNÇÃO DE LOGIN (Inalterada) ---
def check_password():
    if st.session_state.get("logged_in"):
        return True
    def password_entered():
        hashed_entered_password = hashlib.sha256(st.session_state["password"].encode()).hexdigest()
        if hashed_entered_password == CORRECT_PASSWORD_HASH:
            st.session_state["logged_in"] = True
            del st.session_state["password"]
        else:
            st.session_state["logged_in"] = False
    st.sidebar.subheader("Acesso Restrito")
    st.sidebar.text_input("Senha:", type="password", on_change=password_entered, key="password")
    if "logged_in" in st.session_state and st.session_state["logged_in"] is False:
        st.sidebar.error("Senha incorreta.")
    return st.session_state.get("logged_in")

# --- CUSTOMIZAÇÃO DE LAYOUT E ESTILOS DINÂMICOS (Inalterada) ---

layout_buscado_css = ""
if st.session_state['layout_buscado']:
    layout_buscado_css = f"""
        .main-header-container {{ position: absolute; top: 10px; right: 10px; text-align: right; max-width: 300px; z-index: 1000; }}
        .main-header-title {{ font-size: 1.5rem !important; font-weight: 600 !important; text-align: right !important; margin: 0 !important; }}
        .main-slogan {{ font-size: 0.7rem !important; text-align: right !important; color: #555 !important; margin: 0 !important; }}
        [data-testid="stAppViewBlockContainer"] > div:first-child {{ padding-top: 50px; }}
    """
else:
    layout_buscado_css = """
        .main-header-container { margin-bottom: 50px; }
        .main-header-title { font-size: 3.5rem !important; font-weight: 800 !important; text-align: center !important; text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.1); }
        .main-slogan { font-size: 1.0rem !important; text-align: center !important; color: #1f1f1f !important; }
    """

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700;800&display=swap');
    
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
    
    .content-box .stSelectbox > label {{ font-size: 0.8rem !important; font-weight: 400 !important; color: #666666 !important; }}
    .content-box .stSelectbox div[role="combobox"] {{ font-size: 0.9rem !important; padding: 5px 10px; }}

    .ag-row-selected {{ background-color: #e0f0ff !important; border: 1px solid #007bff; font-weight: 600; }}
    
    {layout_buscado_css}
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("""
<style>
    .search-container { max-width: 900px; margin: 30px auto 40px auto; text-align: center; }
    div[data-testid="stTextInput"] label[for^="search_geral"] { font-size: 2.5rem !important; font-weight: 900 !important; color: #000000 !important; }
    div[data-testid="stTextInput"] input[id^="search_geral"] { font-size: 2.2rem !important; padding: 40px 30px !important; border: 4px solid #007bff !important; box-shadow: 0 5px 25px rgba(0, 123, 255, 0.6) !important; }
</style>
""", unsafe_allow_html=True)


# --- LÓGICA DE NAVEGAÇÃO E RESTRIÇÃO ---
st.sidebar.image("Labeur_logo.jpg", width=150) 
opcoes_menu = ["Biblioteca Principal"]

if check_password():
    opcoes_menu.extend([
        "Sincronização Drive (Coleta)",
        "Coleta de Dados Online", 
        "Cadastro Automatizado (PDF)", 
        "Gestão de Referências",
        "Gestão de Dados Externos",
        "Cadastro Manual",
        "Cadastro de Dados Externos",
        "Dashboard"
    ])
    st.sidebar.success("Acesso total liberado.")
else:
    pass 

if 'menu_selection' in st.session_state:
    menu = st.session_state.pop('menu_selection')
else:
    st.sidebar.title("Navegação")
    menu = st.sidebar.radio("Ir para:", opcoes_menu)


# =========================================================================
# === PÁGINA: SINCRONIZAÇÃO DRIVE (COLETA AUTOMATIZADA DE LINKS) ==========
# =========================================================================

if menu == "Sincronização Drive (Coleta)":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar a Sincronização do Drive.")
        st.stop()
        
    st.title("Sincronização e Coleta de Links do Google Drive")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("""
        Esta ferramenta lista os arquivos na Planilha Mestra (aba `dados_externos` e `bibliografia`) que estão marcados como **Status = 'Pendente'** para processamento.
        
        **NOTA:** A sincronização de metadados do Drive para o Sheets deve ser feita manualmente ou via Google Apps Script (GAS) fora desta aplicação.
    """)
    
    # Lendo ambas as abas para simular um controle unificado de "Pendente"
    df_biblio = carregar_dados_bibliografia()
    df_datasets = carregar_datasets_externos()

    # Combinando e filtrando por status 'Pendente' (Assumindo que você adiciona essa coluna manualmente no Sheets)
    # ATENÇÃO: Se suas abas do Sheets não tiverem a coluna 'Status', esta lógica falhará.
    
    df_pendente_biblio = df_biblio[(df_biblio['resumo'].isna()) & (df_biblio['caminho_arquivo'].str.contains('http', na=False))]
    # Aqui, a lógica é simplificada: Pendente = Tem link, mas não tem resumo (precisa de extração)
    
    df_pendente_datasets = df_datasets[df_datasets['link_drive'].notna()]
    # Para datasets, assumimos que eles são apenas cadastrados e não "processados"
    
    # Criando uma lista unificada para exibição
    all_pendentes = []
    
    if not df_pendente_biblio.empty:
        df_pendente_biblio['ID_Ref'] = 'B-' + df_pendente_biblio['id'].astype(str)
        df_pendente_biblio['Tipo'] = 'Referência/PDF'
        all_pendentes.append(df_pendente_biblio[['ID_Ref', 'titulo', 'caminho_arquivo', 'Tipo']])

    # Se você quiser processar datasets no cadastro, adicione-os aqui
    
    if not all_pendentes:
        st.success("✅ Não há novos arquivos Pendentes de processamento de metadados.")
        st.markdown('</div>', unsafe_allow_html=True)
        st.stop()

    df_pendente = pd.concat(all_pendentes).rename(columns={'caminho_arquivo': 'Link para Processamento', 'titulo': 'Título Provisório'})
    
    st.markdown("---")
    st.subheader(f"Arquivos Pendentes de Processamento ({len(df_pendente)} itens)")
    
    # --- Configuração AgGrid ---
    df_display = df_pendente[['Tipo', 'Título Provisório', 'Link para Processamento']]

    gb = GridOptionsBuilder.from_dataframe(df_display)
    gb.configure_selection('single', use_checkbox=False)
    gb.configure_grid_options(domLayout='autoHeight')
    gridOptions = gb.build()

    grid_response = AgGrid(
        df_display,
        gridOptions=gridOptions,
        data_return_mode='AS_INPUT',
        update_mode=GridUpdateMode.MODEL_CHANGED,
        fit_columns_on_grid_load=True,
        theme='streamlit',
        key='aggrid_drive_sync'
    )
    
    selected_rows_df = grid_response.get('selected_rows') 
    st.markdown("---")

    selected_item = None
    if selected_rows_df is not None and not selected_rows_df.empty: 
        selected_item = selected_rows_df.iloc[0]
        
        st.info(f"Item Selecionado: **{selected_item['Título Provisório']}**")
        
        transfer_button = st.button("Transferir Link para Cadastro Automatizado", key="transfer_drive_link_btn", type="primary")
        
        if transfer_button:
            st.session_state['transfer_link'] = selected_item['Link para Processamento']
            st.session_state['transfer_title'] = selected_item['Título Provisório']
            st.success("Link transferido! Redirecionando...")
            
            st.session_state['menu_selection'] = "Cadastro Automatizado (PDF)"
            st.rerun() 
    else:
        st.warning("Selecione um item na tabela para processar.")
        
    st.markdown('</div>', unsafe_allow_html=True)

# =========================================================================
# === PÁGINA: COLETA DE DADOS ONLINE (BUSCA ALICIA/BCRP) ==================
# =========================================================================

elif menu == "Coleta de Dados Online":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar a Coleta de Dados Online.")
        st.stop()
        
    st.title("Plataforma de Coleta de Dados Online")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown(f"""
        Busque recursos acadêmicos (ALICIA) e relatórios econômicos (BCRP) com foco em **Formação Socioespacial do Peru**.
    """)

    search_query = st.text_input(
        "Termo de Busca Focado (Ex: mineração, desigualdade urbana)",
        value=st.session_state['last_online_query'] 
    )
    
    col_button, col_clear = st.columns([1, 1])
    
    with col_button:
        search_button = st.button("Buscar Dados Online", type="primary")

    with col_clear:
        if st.button("Limpar Resultados"):
            st.session_state['search_results_online'] = []
            st.session_state['selected_online_item'] = None
            st.session_state['last_online_query'] = ""
            st.rerun()

    if search_button:
        if search_query:
            st.session_state['last_online_query'] = search_query
            st.session_state['search_results_online'] = []
            st.session_state['selected_online_item'] = None 
            
            with st.spinner(f"Buscando por '{search_query}' nas fontes online..."):
                try:
                    results = unified_data_search(search_query)
                    st.session_state['search_results_online'] = results
                    
                    if any(res.get('tipo') == 'Erro' for res in results):
                         st.warning(f"Busca concluída, mas **houve erros de conexão/bloqueio** em algumas fontes. Total de {len(results)} resultados (incluindo erros).")
                    else:
                         st.success(f"Busca concluída. {len(results)} resultados encontrados.")
                         
                except Exception as e:
                    st.error(f"Erro inesperado durante a busca: {e}. Verifique se 'data_collector.py' e suas bibliotecas (`beautifulsoup4`) estão corretas.")
        else:
            st.warning("Por favor, insira um termo de busca.")

    results = st.session_state['search_results_online']
    
    if results:
        st.markdown("---")
        st.subheader(f"Resultados Encontrados ({len(results)} itens)")
        
        df_results = pd.DataFrame(results)
        df_results['ID'] = range(1, len(df_results) + 1)
        df_display = df_results[['ID', 'tipo', 'titulo', 'fonte']]

        gb = GridOptionsBuilder.from_dataframe(df_display)
        gb.configure_selection('single', use_checkbox=False)
        gb.configure_grid_options(domLayout='autoHeight')
        gridOptions = gb.build()

        grid_response = AgGrid(
            df_display,
            gridOptions=gridOptions,
            data_return_mode='AS_INPUT',
            update_mode=GridUpdateMode.MODEL_CHANGED,
            fit_columns_on_grid_load=True,
            theme='streamlit',
            key='aggrid_online_search'
        )
        
        selected_rows_df = grid_response.get('selected_rows') 
        selected_item = None
        if selected_rows_df is not None and not selected_rows_df.empty: 
            selected_item_index = selected_rows_df.iloc[0]['ID'] - 1
            selected_item = results[selected_item_index]
            st.session_state['selected_online_item'] = selected_item
        
        if st.session_state['selected_online_item']:
            item = st.session_state['selected_online_item']
            st.markdown("---")
            st.subheader(f"Detalhes do Item Selecionado: {item['tipo']}")
            
            st.markdown(f"**Título:** {item['titulo']}")
            st.markdown(f"**Fonte/Autor:** {item['fonte']}")
            st.markdown(f"**Link:** [`Abrir Fonte`]({item['link']})")
            
            with st.expander("Prévia do Conteúdo"):
                st.write(item['resumo_preview'])
                
            st.markdown("---")
            
            if item['link'] != '#':
                st.info("Para importar este item (se for um PDF ou link do Drive) para sua Biblioteca, use o botão abaixo. O link será enviado para o Cadastro Automatizado.")
                
                transfer_button = st.button("Enviar Link para Cadastro Automatizado", key="transfer_link_btn", type="secondary")
                
                if transfer_button:
                    st.session_state['transfer_link'] = item['link']
                    st.session_state['transfer_title'] = item['titulo']
                    st.success("Link transferido! Redirecionando...")
                    
                    st.session_state['menu_selection'] = "Cadastro Automatizado (PDF)"
                    st.rerun() 

    
    st.markdown('</div>', unsafe_allow_html=True)


# =========================================================================
# === PÁGINA: CADASTRO AUTOMATIZADO (PDF) (COM LÓGICA DE RECEPÇÃO DE LINK) =
# =========================================================================

elif menu == "Cadastro Automatizado (PDF)":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Cadastro Automatizado.")
        st.stop()
        
    st.title("Cadastro Automatizado de Referência (PDF)")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("""
        Use esta ferramenta para extrair texto de um PDF e preparar metadados (Título, Autor, Ano). 
        Você pode fazer upload de um arquivo local ou usar um link de **download direto** do Google Drive.
    """)
    
    # --- LÓGICA PARA RECEBER LINK TRANSFERIDO ---
    link_transferido = st.session_state.pop('transfer_link', '')
    title_transferido = st.session_state.pop('transfer_title', '')
    
    default_link_value = link_transferido
    if link_transferido:
        st.warning(f"Link recebido da Coleta: **{title_transferido}**. Clique em 'Processar' para extrair os metadados.")
    
    link_drive_input_initial_value = default_link_value if default_link_value else ""

    # Campos de Upload/Link
    uploaded_file = st.file_uploader("1. Faça Upload de um PDF local:", type="pdf")
    link_drive_input = st.text_input(
        "2. OU insira um Link de Download Direto do Google Drive:", 
        value=link_drive_input_initial_value
    )
    
    process_button = st.button("Processar Arquivo para Extração de Texto e Sugestões", type="primary")

    if process_button:
        st.session_state['extracted_text'] = None
        st.session_state['suggested_data'] = {}
        st.session_state['logs'] = {} 
        raw_text = None
        
        with st.spinner("Processando o PDF e extraindo metadados..."):
            if uploaded_file is not None:
                pdf_bytes = BytesIO(uploaded_file.read())
                raw_text = process_pdf_bytes(pdf_bytes)
                st.session_state['suggested_data']['caminho_arquivo'] = "Local Upload"
            
            elif link_drive_input:
                raw_text = extract_text_from_drive_link(link_drive_input)
                st.session_state['suggested_data']['caminho_arquivo'] = link_drive_input
            
            else:
                st.warning("Por favor, forneça um arquivo por upload ou um link do Google Drive.")
        
        if raw_text and not raw_text.startswith("Erro"):
            st.session_state['extracted_text'] = raw_text
            
            if len(raw_text) > 100: 
                try:
                    suggested_data, logs = suggest_metadata(raw_text) 
                    st.session_state['suggested_data'].update(suggested_data)
                    st.session_state['logs'] = logs 
                    st.success("Extração de texto e sugestões de metadados concluídas! Revise ao lado.")
                except Exception as e:
                    st.error(f"Erro na sugestão automática de metadados. Revise manualmente. Erro: {e}")
                    st.session_state['suggested_data'].update({
                        'titulo': "ERRO NA EXTRAÇÃO. Revise manualmente.",
                        'autor': "",
                        'ano': datetime.now().year,
                        'tipo': "Artigo",
                        'tags': "Erro, Revisar",
                        'resumo': raw_text[:1500] if len(raw_text) > 1500 else raw_text
                    })
                    st.session_state['logs'] = {'status_geral': f"Falha na execução da sugestão. Erro Python: {e}"}
            else:
                 st.session_state['suggested_data'].update({
                    'titulo': "Texto muito curto, insira manualmente",
                    'autor': "",
                    'ano': datetime.now().year,
                    'tipo': "Artigo",
                    'tags': "",
                    'resumo': raw_text
                })
                 st.session_state['logs'] = {'status_geral': "Texto extraído insignificante para processamento."}
            
            st.rerun() 
        
        elif raw_text and raw_text.startswith("Erro"):
             st.error(raw_text)

    if st.session_state['extracted_text']:
        st.markdown("---")
        st.subheader("3. Revisar e Confirmar Metadados")
        
        col_sugestoes, col_preview = st.columns([1, 1]) 
        
        sdata = st.session_state['suggested_data']
        logs = st.session_state.get('logs', {}) 
        caminho = sdata.get('caminho_arquivo', '')

        with col_sugestoes:
            st.info("Os campos foram preenchidos pela IA. Corrija-os e clique em Salvar.")
            
            if logs:
                 with st.expander("Ver Logs e Status de Execução da IA"):
                     st.markdown("Logs de Detecção de Metadados:")
                     for key, value in logs.items():
                         status_emoji = "ⓘ "
                         if 'Sucesso' in value: status_emoji = "✅ "
                         elif 'Falhou' in value or 'Erro' in value: status_emoji = "❌ "
                         elif 'Aviso' in value: status_emoji = "⚠️ "
                         st.markdown(f"**{status_emoji}{key.replace('_', ' ').title()}:** `{value}`")

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
                    data = {
                        'titulo': titulo_s, 'autor': autor_s, 'tipo': tipo_s, 'ano': ano_s,
                        'tags': tags_s, 'caminho_arquivo': caminho if caminho != 'Local Upload' else '', 
                        'resumo': resumo_s, 'localizacao_fisica': localizacao_s
                    }
                    if append_new_reference(data): # NOVO: Usando a função Sheets
                        st.success(f"Referência '{titulo_s}' salva com sucesso no Google Sheets!")
                        st.session_state['extracted_text'] = None
                        st.session_state['suggested_data'] = {}
                        st.session_state['logs'] = {}
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Falha ao salvar no Google Sheets.")

        with col_preview:
            st.subheader("Prévia do Documento")
            
            if caminho and caminho != "Local Upload":
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
# === PÁGINA: BIBLIOTECA PRINCIPAL (Consulta Pública - HOME) ================
# =========================================================================
elif menu == "Biblioteca Principal":
    
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

    df_biblio = carregar_dados_bibliografia()
    df_datasets = carregar_datasets_externos()

    st.markdown('<div class="search-container">', unsafe_allow_html=True)
    filtro_geral = st.text_input("Pesquisa por Título, Autor, Tag ou Localização:", key="search_geral", label_visibility="visible")
    st.markdown('</div>', unsafe_allow_html=True)
    
    busca_placeholder = st.empty()
    
    with busca_placeholder.container():
        st.markdown('<div class="content-box">', unsafe_allow_html=True)
        
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
        deve_exibir_resultados = False
        
        if tema_selecionado != "TODOS OS TEMAS":
            df_biblio_filtrada = df_biblio_filtrada[
                df_biblio_filtrada['tags'].fillna('').apply(lambda x: tema_selecionado in [t.strip() for t in x.split(',')])
            ].copy()
            deve_exibir_resultados = True
        
        df_datasets_filtrados = df_datasets.copy()
        
        if filtro_geral:
            deve_exibir_resultados = True
            
            if not df_biblio_filtrada.empty:
                df_biblio_filtrada = df_biblio_filtrada[
                    df_biblio_filtrada['titulo'].str.contains(filtro_geral, case=False, na=False) | 
                    df_biblio_filtrada['autor'].str.contains(filtro_geral, case=False, na=False) |
                    df_biblio_filtrada['tags'].str.contains(filtro_geral, case=False, na=False) |
                    df_biblio_filtrada['localizacao_fisica'].str.contains(filtro_geral, case=False, na=False) 
                ].copy()
                
            if not df_datasets_filtrados.empty:
                df_datasets_filtrados = df_datasets_filtrados[
                    df_datasets_filtrados['titulo'].str.contains(filtro_geral, case=False, na=False) |
                    df_datasets_filtrados['descricao'].str.contains(filtro_geral, case=False, na=False)
                ].copy()
                
        
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
            df_datasets_formatado['ID_Recurso'] = 'D-' + df_datasets_filtrados['id'].astype(str)
            df_datasets_formatado['Tipo de Recurso'] = 'Dataset/Dado'
            df_datasets_formatado['Localização'] = 'Drive/Online'
            df_datasets_formatado['Ano/Data'] = df_datasets_formatado['data_cadastro'].str[:10]
            df_datasets_formatado = df_datasets_formatado.rename(columns={'descricao': 'Autor/Fonte'})
            df_datasets_formatado = df_datasets_formatado[['ID_Recurso', 'Tipo de Recurso', 'titulo', 'Autor/Fonte', 'Ano/Data', 'Localização']]
            df_unificado = pd.concat([df_unificado, df_datasets_formatado])
            
        
        if deve_exibir_resultados and not df_unificado.empty:
            
            if not st.session_state['layout_buscado']:
                st.session_state['layout_buscado'] = True
                st.rerun() 

            st.subheader(f"Resultados da Busca Unificada ({len(df_unificado)} itens):")
            st.info("Clique em uma linha na tabela abaixo para ver os detalhes e a pré-visualização.")
            
            df_aggrid = df_unificado[['Tipo de Recurso', 'titulo', 'Autor/Fonte', 'Ano/Data', 'Localização', 'ID_Recurso']].reset_index(drop=True)

            gb = GridOptionsBuilder.from_dataframe(df_aggrid)
            gb.configure_column("ID_Recurso", hide=True)
            gb.configure_selection('single', use_checkbox=False)
            gb.configure_grid_options(domLayout='autoHeight')
            gridOptions = gb.build()

            grid_response = AgGrid(
                df_aggrid,
                gridOptions=gridOptions,
                data_return_mode='AS_INPUT',
                update_mode=GridUpdateMode.MODEL_CHANGED, 
                fit_columns_on_grid_load=True,
                allow_unsafe_jscode=True,
                theme='streamlit',
                key='aggrid_busca_unificada'
            )
            
            selected_rows_df = grid_response.get('selected_rows')
            id_selecionado = None
            
            if selected_rows_df is not None and not selected_rows_df.empty: 
                id_selecionado = selected_rows_df.iloc[0]['ID_Recurso']
            
            elif not df_unificado.empty:
                 id_selecionado = df_unificado['ID_Recurso'].iloc[0]

            st.markdown('</div>', unsafe_allow_html=True) 

            if id_selecionado:
                st.markdown("## Detalhes e Pré-visualização")
                
                recurso_tipo = id_selecionado.split('-')[0]
                original_id = id_selecionado.split('-')[1] # Não precisamos converter para int se estamos buscando por ID no DataFrame

                if recurso_tipo == 'B': # REFERÊNCIA BIBLIOGRÁFICA (PDF/DOCUMENTO)
                    infos = df_biblio[df_biblio['id'] == int(original_id)].iloc[0]
                    caminho = infos.get('caminho_arquivo', '')
                    resumo = infos.get('resumo', 'Nenhum resumo cadastrado.')
                    localizacao = infos.get('localizacao_fisica', 'Não cadastrada.')

                    st.markdown('<div class="content-box">', unsafe_allow_html=True)
                    st.subheader(f"Referência: {infos['titulo']}")
                    
                    st.write(f"Autor(es): {infos['autor']}")
                    st.write(f"Tipo: {infos['tipo']} | Ano: {infos['ano']}")
                    st.write(f"Tags: {infos['tags']}")
                    st.write(f"Localização Física: **{localizacao}**")
                    
                    with st.expander("Ver Resumo / Prévia Textual"):
                        st.write(resumo)

                    if caminho and str(caminho).startswith("http"):
                        st.link_button("Abrir no Google Drive em Nova Aba", caminho, type="primary")

                    st.markdown('</div>', unsafe_allow_html=True) 
                    
                    st.markdown('<div class="content-box">', unsafe_allow_html=True)
                    st.subheader("Prévia Visual do Documento")
                    if caminho and str(caminho).startswith("http"):
                        file_id = extract_file_id(caminho) 
                        if file_id:
                            preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
                            st.components.v1.iframe(preview_url, height=780, scrolling=True) 
                        else:
                            st.warning("Link do Drive inválido para prévia.")
                    else:
                        st.info("Arquivo não vinculado ao Google Drive ou o link não foi preenchido.")
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                elif recurso_tipo == 'D': # DATASET EXTERNO (DADOS)
                    infos = df_datasets[df_datasets['id'] == int(original_id)].iloc[0]
                    link_drive = infos['link_drive']
                    file_id = extract_file_id(link_drive)
                    
                    def create_drive_download_link(file_id):
                        if file_id:
                            return f"https://drive.google.com/uc?export=download&id={file_id}"
                        return None
                        
                    download_link = create_drive_download_link(file_id)
                    
                    st.markdown('<div class="content-box">', unsafe_allow_html=True)
                    st.subheader(f"Dataset: {infos['titulo']}")
                    st.markdown(f"**Descrição/Fonte:** {infos['descricao']}")
                    st.markdown(f"**Data de Cadastro:** {infos['data_cadastro'][:10]}")
                    st.info("Este é um Dataset Externo. Use os links abaixo para visualização e download.")
                    
                    col_view, col_download = st.columns(2)
                    with col_view:
                        st.link_button("Visualizar no Drive", link_drive)
                    with col_download:
                        if download_link:
                            st.link_button("Baixar Dataset", download_link, type="primary")
                        else:
                            st.error("Link de Drive inválido.")
                    
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('<div class="content-box">', unsafe_allow_html=True)
                    st.subheader("Prévia de Dados")
                    if file_id:
                        preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
                        st.components.v1.iframe(preview_url, height=780, scrolling=True) 
                    else:
                        st.warning("Não é possível gerar a prévia. O link do Drive pode estar mal formatado.")
                    st.markdown('</div>', unsafe_allow_html=True)

        
        elif deve_exibir_resultados and df_unificado.empty:
            if not st.session_state['layout_buscado']:
                st.session_state['layout_buscado'] = True
                st.rerun() 
            st.warning(f"Nenhum item encontrado na Biblioteca ou nos Datasets para o termo pesquisado '{filtro_geral}' no tema '{tema_selecionado}'.")
            st.markdown('</div>', unsafe_allow_html=True) 
        
        else:
            if st.session_state['layout_buscado']:
                 st.session_state['layout_buscado'] = False
                 st.rerun()
                 
            st.markdown('<p style="font-size:0.9rem; color:#555555; text-align:center;">Utilize a barra de pesquisa ou selecione um tema acima para iniciar a busca unificada na biblioteca e nos datasets.</p>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True) 


# === PÁGINA: GESTÃO DE REFERÊNCIAS (Edição em Bloco e Exclusão) ===
elif menu == "Gestão de Referências":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar a Gestão de Referências.")
        st.stop()
        
    st.title("Gestão de Referências (Planilha Editável)")
    st.info("Os dados são lidos e salvos diretamente na aba 'bibliografia' do Google Sheets.")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    
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
        if st.button("Salvar TODAS as Alterações no Google Sheets", type="primary"):
            if update_all_data(df_atualizado): # NOVO: Usa Sheets Update
                st.success("Todos os dados foram salvos na aba 'bibliografia' do Google Sheets!")
            else:
                st.error("Falha ao salvar. Verifique o console e as credenciais.")
                
        st.write("---")
        
        # Funcionalidade de Excluir
        st.subheader("Excluir Referência Permanentemente")
        
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
                delete_reference(id_delete) # NOVO: Usa Sheets Delete
                st.success(f"Item ID {id_delete} excluído com sucesso do Google Sheets!")
                st.rerun() 

    else:
        st.info("Nenhum dado para gerenciar.")
    
    st.markdown('</div>', unsafe_allow_html=True)


# === PÁGINA: GESTÃO DE DADOS EXTERNOS ===
elif menu == "Gestão de Dados Externos":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar a Gestão de Dados Externos.")
        st.stop()
        
    st.title("Gestão de Dados Externos (Planilha Editável)")
    st.info("Os dados são lidos e salvos diretamente na aba 'dados_externos' do Google Sheets.")

    st.markdown('<div class="content-box">', unsafe_allow_html=True)

    df_datasets = carregar_datasets_externos()
    
    if not df_datasets.empty:
        # Configurações da Tabela AgGrid para Datasets
        gb = GridOptionsBuilder.from_dataframe(df_datasets)
        
        gb.configure_column("id", header_name="ID", editable=False, width=50)
        gb.configure_column("titulo", editable=True)
        gb.configure_column("descricao", header_name="Descrição e Fonte", editable=True, width=200)
        gb.configure_column("link_drive", header_name="Link Google Drive", editable=True, width=300)
        gb.configure_columns(['data_cadastro'], hide=True)
        gridOptions = gb.build()

        grid_response = AgGrid(
            df_datasets,
            gridOptions=gridOptions,
            data_return_mode='AS_INPUT',
            update_mode=GridUpdateMode.VALUE_CHANGED, 
            fit_columns_on_grid_load=False,
            height=400, 
            width='100%',
            reload_data=True,
            key="aggrid_datasets_edit"
        )

        df_atualizado_datasets = grid_response['data']
        st.write("---")
        
        # BOTÃO SALVAR
        if st.button("Salvar TODAS as Alterações dos Datasets no Google Sheets", type="primary"):
            if update_all_data_datasets(df_atualizado_datasets):
                st.success("Todos os dados externos foram salvos na aba 'dados_externos' do Google Sheets!")
            else:
                st.error("Falha ao salvar. Verifique o console e as credenciais.")
                
        st.write("---")
        
        # Funcionalidade de Excluir
        st.subheader("Excluir Dataset Permanentemente")
        
        opcoes_delete_data = df_datasets.set_index('id')['titulo'].to_dict()
        col_del1, col_del2 = st.columns([3, 1])
        
        with col_del1:
            if opcoes_delete_data:
                id_delete_data = st.selectbox(
                    "Selecione o Dataset para EXCLUIR:", 
                    options=opcoes_delete_data.keys(), 
                    format_func=lambda x: opcoes_delete_data[x] if x in opcoes_delete_data else x,
                    key="select_delete_dataset"
                )
            else:
                id_delete_data = None
                st.info("Nenhum dataset para excluir.")

        with col_del2:
            st.write(" ")
            if id_delete_data and st.button("EXCLUIR DATASET SELECIONADO", type="primary"): 
                delete_dataset(id_delete_data) # NOVO: Usa Sheets Delete
                st.success(f"Dataset ID {id_delete_data} excluído com sucesso do Google Sheets!")
                st.rerun() 

    else:
        st.info("Nenhum dataset para gerenciar.")
    
    st.markdown('</div>', unsafe_allow_html=True)


# === PÁGINA: CADASTRO MANUAL (Inserir Novo Item - BIBLIOGRAFIA) ===
elif menu == "Cadastro Manual":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Cadastro Manual.")
        st.stop()
        
    st.title("Cadastrar Nova Referência")
    st.info("Os dados serão salvos como uma nova linha na aba 'bibliografia' do Google Sheets.")

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
            localizacao_fisica = st.text_input("Localização Física")
            link_drive = st.text_input("Link do Google Drive (opcional)")
        
        resumo = st.text_area("Resumo / Prévia")
        
        enviado = st.form_submit_button("Salvar Referência", type="primary")

        if enviado:
            if titulo: # Apenas título é obrigatório
                data = {
                    'titulo': titulo, 'autor': autor, 'tipo': tipo, 'ano': ano,
                    'tags': tags, 'caminho_arquivo': link_drive, 'resumo': resumo, 
                    'localizacao_fisica': localizacao_fisica
                }
                if append_new_reference(data):
                    st.success(f"Referência '{titulo}' salva com sucesso no Google Sheets!")
                else:
                    st.error("Falha ao salvar no Google Sheets.")
            else:
                st.warning("Preencha pelo menos o Título.")
    
    st.markdown('</div>', unsafe_allow_html=True) 


# === PÁGINA: CADASTRO DE DADOS EXTERNOS (Inserir Novo Item - DATASETS) ===
elif menu == "Cadastro de Dados Externos":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Cadastro de Dados Externos.")
        st.stop()
        
    st.title("Cadastro de Datasets Externos")
    st.info("Os dados serão salvos como uma nova linha na aba 'dados_externos' do Google Sheets.")
    
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    st.markdown("""
        Cadastre novos datasets vinculando-os a um **link de compartilhamento do Google Drive**. 
    """)

    with st.form("form_cadastro_dados"):
        titulo = st.text_input("Título do Dataset (Ex: População de SP - 2010/2020) *")
        link_drive = st.text_input("Link de Compartilhamento do Google Drive (CSV ou XLSX) *")
        descricao = st.text_area("Descrição e Fonte (Ex: Dados IBGE, Tratados pelo LABEUR)")
        
        enviado = st.form_submit_button("Salvar Dataset", type="primary")

        if enviado:
            if titulo and link_drive:
                data = {
                    'titulo': titulo, 'descricao': descricao, 'link_drive': link_drive
                }
                if append_new_dataset(data):
                    st.success(f"Dataset '{titulo}' cadastrado com sucesso no Google Sheets!")
                else:
                    st.error("Falha ao salvar no Google Sheets.")
            else:
                st.warning("Preencha pelo menos o Título e o Link do Google Drive.")
    
    st.markdown('</div>', unsafe_allow_html=True)


# === PÁGINA: DASHBOARD ===
elif menu == "Dashboard":
    if not check_password():
        st.error("Acesso negado. Por favor, insira a senha no menu lateral para acessar o Dashboard.")
        st.stop()
        
    st.title("Estatísticas da Biblioteca")
    
    df_biblio = carregar_dados_bibliografia()
    
    if not df_biblio.empty:
        st.markdown('<div class="content-box">', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Por Tipo (Bibliografia)")
            dados_tipo = df_biblio.groupby('tipo').size().reset_index(name='qtd')
            if not dados_tipo.empty:
                fig, ax = plt.subplots()
                ax.pie(dados_tipo['qtd'], labels=dados_tipo['tipo'], autopct='%1.1f%%', startangle=90)
                st.pyplot(fig) 
            else:
                st.write("Sem dados.")

        with col2:
            st.subheader("Publicações por Ano (Últimos 15)")
            df_clean_year = df_biblio[pd.to_numeric(df_biblio['ano'], errors='coerce').notna()]
            df_clean_year['ano'] = df_clean_year['ano'].astype(int)
            dados_ano = df_clean_year[df_clean_year['ano'] > 1900].groupby('ano').size().reset_index(name='qtd').sort_values('ano', ascending=False).head(15).sort_values('ano', ascending=True)
            
            if not dados_ano.empty:
                st.bar_chart(dados_ano.set_index('ano')) 
            else:
                st.write("Sem dados.")
                
        st.markdown('</div>', unsafe_allow_html=True) 
    else:
        st.error("Nenhum dado encontrado na Planilha Mestra (aba 'bibliografia').")


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