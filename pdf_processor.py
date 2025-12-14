import requests
from pdfminer.high_level import extract_text_to_fp
from io import StringIO, BytesIO
import re
from datetime import datetime

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

# --- NOVO: FUNÇÃO DE SUGESTÃO DE METADADOS (PLN BÁSICO) ---

def suggest_metadata(full_text):
    """
    Usa heurísticas (RegEx) nas primeiras páginas do texto para sugerir metadados.
    
    Args:
        full_text (str): Texto limpo extraído do PDF.
    
    Returns:
        dict: Sugestões para título, autor, ano, resumo.
    """
    
    # Divide o texto em blocos/parágrafos
    paragraphs = full_text.split('\n\n')
    
    # Pega apenas o cabeçalho (os 5 primeiros parágrafos) para metadados
    header_text = "\n\n".join(paragraphs[:5]) if len(paragraphs) > 0 else full_text
    
    suggested = {
        'titulo': "Título não detectado",
        'autor': "Autor não detectado",
        'ano': datetime.now().year,
        'tipo': "Artigo",
        'tags': "",
        'resumo': ""
    }
    
    # 1. EXTRAÇÃO DE ANO (Heurística: 4 dígitos perto do início)
    # Procura por um ano (1900-2099) no cabeçalho
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', header_text)
    if year_match:
        suggested['ano'] = int(year_match.group(0))

    # 2. EXTRAÇÃO DE RESUMO (Heurística: Procura pela palavra "Abstract" ou "Resumo")
    abstract_match = re.search(r'(abstract|resumo|sumário|sumario)\s*\n\n*(.*?)(\n\n*1\.|introdução|introducao|capítulo|capitulo|\n\n*palavras-chave)', full_text, re.IGNORECASE | re.DOTALL)
    if abstract_match:
        # Pega o texto após o marcador, mas limita o tamanho
        resumo_texto = abstract_match.group(2).strip()
        suggested['resumo'] = resumo_texto[:1500] if len(resumo_texto) > 1500 else resumo_texto
        
        # Sugere Tags baseadas nas 5 primeiras palavras do resumo (PLN simples)
        suggested['tags'] = ", ".join(resumo_texto.lower().split()[:5])

    # 3. EXTRAÇÃO DE TÍTULO (Heurística: O texto em MAIÚSCULAS/Destaque no topo)
    # O título é geralmente o texto em destaque (muitas vezes em MAIÚSCULAS) nas primeiras 1000 palavras
    title_search_area = full_text[:1000]
    
    # Regex simples: procura uma sequência de texto capitalizada ou em negrito/grande no topo
    title_match = re.search(r'^(.+?)(?:\s*\n\s*por|\s*\n\s*autor|\s*\n\s*abstrato|abstract|resumo)', title_search_area, re.IGNORECASE | re.DOTALL)
    
    if title_match:
        detected_title = title_match.group(1).strip()
        
        # Filtra o título para remover números de página ou lixo
        detected_title = re.sub(r'^\s*([A-Z\s,;.]+)\s*$', r'\1', detected_title, flags=re.MULTILINE)
        
        if detected_title and len(detected_title.split()) > 2 and len(detected_title) < 300:
            suggested['titulo'] = detected_title.replace('\n', ' ')
            
    # 4. EXTRAÇÃO DE AUTOR (Heurística: Padrões de Nome perto do topo)
    # Esta é a parte mais complexa e sensível a erros sem um modelo NER
    author_match = re.search(r'(por|autores?:?|authors?:?)\s*\n*\s*(.*?)(\n\n|\d{4})', header_text, re.IGNORECASE | re.DOTALL)
    
    if author_match and len(author_match.group(2).strip().split()) > 1:
        detected_author = author_match.group(2).strip()
        suggested['autor'] = detected_author.replace('\n', ' ')
    
    
    # Se o resumo for muito curto, use o primeiro parágrafo
    if len(suggested['resumo']) < 50 and len(paragraphs) > 1:
        suggested['resumo'] = paragraphs[0][:1000] if len(paragraphs[0]) > 1000 else paragraphs[0]
        suggested['tags'] = ", ".join(suggested['resumo'].lower().split()[:5])


    return suggested

if __name__ == "__main__":
    # --- EXEMPLO DE USO ---
    # Coloque o caminho para um PDF real para testar a extração
    caminho_do_seu_pdf_local = 'caminho/para/seu/artigo_de_teste.pdf'
    
    try:
        with open(caminho_do_seu_pdf_local, 'rb') as f:
             pdf_bytes = BytesIO(f.read())
             full_text = process_pdf_bytes(pdf_bytes)
             
             if not full_text.startswith("Erro"):
                 metadata = suggest_metadata(full_text)
                 print("--- Metadados Sugeridos ---")
                 for key, value in metadata.items():
                     print(f"{key.capitalize()}: {value}")
                     
                 print("\n--- Texto Completo (Início) ---")
                 print(full_text[:500])
             else:
                 print(full_text)

    except FileNotFoundError:
        print(f"ERRO: Arquivo de teste '{caminho_do_seu_pdf_local}' não encontrado. Não foi possível testar a extração.")
    except Exception as e:
        print(f"Erro geral durante o teste: {e}")