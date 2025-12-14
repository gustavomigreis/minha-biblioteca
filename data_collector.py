import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlencode, urljoin
import random
import time

# Configuração de headers para simular um navegador de forma mais detalhada
# Isso ajuda a reduzir o risco de bloqueio
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'Connection': 'keep-alive',
}

def search_google_scholar(query, num_results=10):
    """
    Simula uma busca no Google Scholar para dados bibliográficos.
    """
    search_query = f"{query} Peru socioespacial"
    base_url = "https://scholar.google.com/scholar"
    params = {
        'q': search_query,
        'hl': 'pt',
        'as_ylo': '2015',
        'num': num_results
    }
    
    results = []
    
    try:
        # Atraso aleatório para parecer mais humano
        time.sleep(random.uniform(1, 3)) 
        
        response = requests.get(base_url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status() 
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # O Google Scholar usa a classe gs_r para cada resultado
        for item in soup.find_all('div', class_='gs_r gs_or gs_scl'):
            
            title_tag = item.find('h3', class_='gs_rt')
            link_tag = title_tag.find('a') if title_tag else None
            snippet_tag = item.find('div', class_='gs_rs')
            info_tag = item.find('div', class_='gs_a')
            
            title = link_tag.text if link_tag else "Título não encontrado"
            link = link_tag['href'] if link_tag and 'href' in link_tag.attrs else "#"
            snippet = snippet_tag.text.strip().replace('\n', ' ') if snippet_tag else "Descrição/Resumo não disponível."
            info = info_tag.text.strip().replace('\n', ' ') if info_tag else "Autor/Ano não disponível."
            
            results.append({
                'tipo': 'Bibliografia (Acadêmico)',
                'titulo': title,
                'link': link,
                'fonte': info,
                'resumo_preview': snippet
            })
            
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429 or response.status_code == 403:
             results.append({'tipo': 'Erro', 'titulo': "Conexão Bloqueada pelo Google Scholar", 'link': '#', 'fonte': "O Google detectou o scraping. Tente novamente mais tarde ou no Streamlit Cloud.", 'resumo_preview': str(e)})
        else:
             results.append({'tipo': 'Erro', 'titulo': f"Erro HTTP {response.status_code}", 'link': '#', 'fonte': "Verifique sua conexão ou URL.", 'resumo_preview': str(e)})
    except requests.exceptions.RequestException as e:
        results.append({
            'tipo': 'Erro',
            'titulo': f"Falha na conexão com o Google Scholar.",
            'link': '#',
            'fonte': str(e),
            'resumo_preview': "Verifique sua conexão ou as configurações de VPN/Firewall."
        })

    return results

def search_peru_economic_data(query, num_results=5):
    """
    Simula uma busca genérica por dados econômicos em fontes peruanas
    (Esta função permanece a mesma, mas se o Google bloquear o Scholar,
    ela também será instável, pois usa a busca regular do Google).
    """
    search_query = f"site:bcrp.gob.pe {query} informe anual"
    
    base_url = "https://www.google.com/search"
    params = {
        'q': search_query,
        'num': num_results
    }
    
    results = []
    
    try:
        # Atraso aleatório
        time.sleep(random.uniform(1, 3)) 
        response = requests.get(base_url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for g in soup.find_all('div', class_='g'):
            link_tag = g.find('a', href=True)
            title_tag = g.find('h3')
            snippet_tag = g.find('div', class_='VwiC3b yXK7lb DZRp5 yndLd') # Classe do snippet
            
            if link_tag and title_tag:
                title = title_tag.text
                link = link_tag['href']
                snippet = snippet_tag.text.strip() if snippet_tag else "Descrição não disponível."
                
                if '.pdf' in link.lower() or 'informe' in title.lower():
                    results.append({
                        'tipo': 'Econômico (BCRP)',
                        'titulo': title,
                        'link': link,
                        'fonte': 'Banco Central de Reserva del Perú',
                        'resumo_preview': snippet
                    })
            
    except requests.exceptions.RequestException as e:
         results.append({'tipo': 'Erro', 'titulo': f"Falha na conexão com o Google/BCRP.", 'link': '#', 'fonte': str(e), 'resumo_preview': "Verifique sua conexão e tente novamente."})
        
    return results
    
def unified_data_search(query):
    """Executa a busca em todas as fontes e combina os resultados."""
    bibliographic_results = search_google_scholar(query)
    economic_results = search_peru_economic_data(query)
    
    all_results = economic_results + bibliographic_results
    
    return all_results