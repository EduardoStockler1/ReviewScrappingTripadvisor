# coding: utf-8

# Quantidade de threads que serão usadas para fazer o scrapping
# Quanto mais threads, mais navegadores simultâneos serão simulados
THREADS = 1

# Se o WebDriver deve ser executado sem mostrar interface
HEADLESS = False

# Limite de reviews a serem salvos em memória principal antes
# de salvar no disco
SAVING_THRESHOLD = 150

# Caminho do arquivo onde o Playwright salva os cookies/sessão do navegador
# depois que um captcha é resolvido manualmente (HEADLESS=False). Nas
# próximas execuções, essa sessão é reaproveitada para evitar cair de novo
# na tela de verificação anti-bot. Não versionar esse arquivo no Git.
STORAGE_STATE_PATH = "storage_state.json"

# Intervalo mínimo e máximo (em segundos) de pausa aleatória entre ações
# como ir para a próxima página de reviews. Simula um ritmo mais humano de
# navegação, evitando o padrão de cliques em intervalos perfeitamente
# regulares que sistemas anti-bot (Cloudflare/PerimeterX) detectam com
# facilidade.
MIN_DELAY_BETWEEN_ACTIONS = 1.5
MAX_DELAY_BETWEEN_ACTIONS = 4.0