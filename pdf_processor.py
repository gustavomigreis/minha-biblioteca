import requests
from pdfminer.high_level import extract_text_to_fp
from io import StringIO, BytesIO
import re
from datetime import datetime
from gensim.summarization import summarize, keywords # NOVA IMPORTAÇÃO TextRank

# --- Funções Auxiliares para Google Drive ---

def extract_file_id(drive_link):
    """Extrai o ID do arquivo de um URL de compartilhamento do Google Drive."""
    match = re.search(r'/d/([^/]+)', drive_link)
    if match:
        return match.group(1)
    
    match_uc = re.search(r'id=([^&]+)', drive_link)
    if match_uc:
        return match_uc.group(1)
        
    return None

# --- Função de Processamento Principal ---

def process_pdf_bytes(pdf_bytes):
    """
    Extrai texto limpo de um objeto BytesIO contendo o PDF.
    """
    try:
        output_string = StringIO()
        
        pdf_bytes.seek(0)
        
        extract_text_to_fp(pdf_bytes, output_string)
        
        raw_text = output_string.getvalue()
        output_string.close()
        
        # --- Etapa de Limpeza de Texto (PLN Básico) ---
        # 1. Remover quebras de linha/hifenização de palavras (mantendo parágrafos)
        text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', raw_text)
        
        # 2. Substituir múltiplas quebras de linha (parágrafos) por um marcador único [PARAGRAPH]
        text = re.sub(r'\n\s*\n', '[PARAGRAPH]', text)
        
        # 3. Substituir quebras de linha únicas (dentro da frase) e espaços por um único espaço
        text = re.sub(r'\s*\n\s*', ' ', text)
        
        # 4. Normalizar os parágrafos de volta para quebras de linha
        text = text.replace('[PARAGRAPH]', '\n\n')
        
        return text.strip()

    except Exception as e:
        return f"Erro durante a extração do PDF: {e}"

# --- Função que Recebe o Link do Drive e Faz o Download ---

def extract_text_from_drive_link(drive_download_link):
    """
    Faz o download do PDF a partir do link do Drive e processa o texto.
    """
    try:
        response = requests.get(drive_download_link, stream=True)
        response.raise_for_status() 
        
        content_type = response.headers.get('Content-Type')
        if 'pdf' not in content_type and 'octet-stream' not in content_type:
             return f"Erro: O link não retornou um arquivo PDF. Tipo: {content_type}"

        pdf_bytes = BytesIO(response.content)
        
        return process_pdf_bytes(pdf_bytes)

    except requests.exceptions.HTTPError as e:
        return f"Erro HTTP ao baixar o arquivo: Certifique-se de que o link do Drive é de DOWNLOAD DIRETO e está configurado para acesso público. Erro: {e}"
    except Exception as e:
        return f"Erro inesperado no download: {e}"

# --- FUNÇÃO DE SUGESTÃO DE METADADOS (PLN AVANÇADO com TextRank) ---

def suggest_metadata(full_text):
    """
    Usa heurísticas (RegEx) e TextRank para sugerir metadados (Título, Autor, Ano, Resumo, Tags).
    """
    
    paragraphs = full_text.split('\n\n')
    header_text = "\n\n".join(paragraphs[:8]) if len(paragraphs) > 0 else full_text
    
    suggested = {
        'titulo': "Título não detectado",
        'autor': "Autor não detectado",
        'ano': datetime.now().year,
        'tipo': "Artigo",
        'tags': "",
        'resumo': ""
    }
    
    # --- 1. EXTRAÇÃO DE RESUMO E TAGS (TextRank) ---
    
    # Tenta usar o TextRank para gerar um resumo
    # target_text é o texto que será sumarizado (pode ser o texto inteiro ou apenas a seção de resumo/introdução)
    target_text = " ".join(paragraphs[0:15]) # Usamos os primeiros 15 parágrafos (mais seguro que o texto inteiro)
    
    try:
        # TextRank para Resumo: Pede um resumo de 10% do tamanho (ou menos, se for pequeno)
        # Limita o resumo a 1500 caracteres, pois é o limite da caixa de texto
        textrank_resumo = summarize(target_text, ratio=0.1, word_count=250)
        suggested['resumo'] = textrank_resumo.strip() if textrank_resumo else suggested['resumo']
        
        # TextRank para Tags: Pede 7 palavras-chave separadas por vírgula
        textrank_keywords = keywords(target_text, words=7, separate=True, scores=False)
        suggested['tags'] = textrank_keywords.replace('\n', ', ') if textrank_keywords else suggested['tags']

    except ValueError:
        # Se o texto for muito pequeno, o TextRank pode falhar. Usa o fallback.
        if len(full_text) > 100:
            suggested['resumo'] = full_text[:1500]
            suggested['tags'] = ", ".join(full_text.lower().split()[:7])
    except Exception as e:
        # Log de erro (útil para depuração futura)
        print(f"Erro TextRank: {e}")
        suggested['resumo'] = full_text[:1500] if len(full_text) > 1500 else full_text
        
    
    # --- 2. EXTRAÇÃO DE ANO (HEURÍSTICA) ---
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', header_text)
    if year_match:
        suggested['ano'] = int(year_match.group(0))

    # --- 3. EXTRAÇÃO DE TÍTULO (HEURÍSTICA REFORÇADA) ---
    title_search_area = header_text[:2000] 
    
    title_match = re.search(r'^(.*?)(?:\s*\n\s*por|\s*\n\s*autor|\s*\n\s*abstract|resumo|sumário)', title_search_area, re.IGNORECASE | re.DOTALL)
    
    if title_match:
        detected_title = title_match.group(1).strip()
        detected_title = '\n'.join(detected_title.split('\n')[-5:])
        detected_title = re.sub(r'[^\w\s,\-]', '', detected_title).strip() 
        
        if detected_title and len(detected_title.split()) > 3 and len(detected_title) < 500:
            suggested['titulo'] = ' '.join(detected_title.split())
            
    # --- 4. EXTRAÇÃO DE AUTOR (HEURÍSTICA REFORÇADA) ---
    author_match = re.search(r'(?:por|autores?:?|authors?:?)\s*\n*\s*(.*?)(?:\n\n|\d{4}|email|e-mail|\s*recebido)', header_text, re.IGNORECASE | re.DOTALL)
    
    if author_match and len(author_match.group(1).strip().split()) > 1:
        detected_author = author_match.group(1).strip()
        detected_author = re.sub(r'\s*\[.*?\]|\s*\d+', '', detected_author)
        
        author_lines = detected_author.split('\n')
        detected_author = '\n'.join(author_lines[:5])

        suggested['autor'] = detected_author.replace('\n', ', ')
    
    # --- 5. FALLBACK para Resumo (Se o TextRank falhou) ---
    if not suggested['resumo'] and len(paragraphs) > 1:
        fallback_resumo = paragraphs[1] if len(paragraphs) > 1 else paragraphs[0]
        suggested['resumo'] = fallback_resumo[:1500] if len(fallback_resumo) > 1500 else fallback_resumo
        
        # Tags de fallback simples
        palavras = re.findall(r'\b\w{4,}\b', fallback_resumo.lower()) 
        stopwords = {'de', 'da', 'do', 'em', 'a', 'o', 'e', 'os', 'as', 'que', 'para', 'com', 'um', 'uma', 'seu', 'sua', 'isto', 'este', 'isso'}
        tags_finais = sorted(list(set([p for p in palavras if p not in stopwords])))
        suggested['tags'] = ", ".join(tags_finais[:7])


    return suggested