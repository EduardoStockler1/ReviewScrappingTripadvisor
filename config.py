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

MAX_REVIEWS = 10  # Limite máximo de reviews a serem coletadas. None = sem limite

# Indícios de que a página atual é um desafio anti-bot (Cloudflare/PerimeterX)
# em vez do conteúdo real do Tripadvisor.
CHALLENGE_TITLE_HINTS = (
    "just a moment",
    "attention required",
    "verifique",
    "verificação",
    "are you a human",
    "access denied",
)

# Indícios de BLOQUEIO TERMINAL: página informativa sem captcha nenhum pra
# resolver ("acesso restrito"). Diferente de um desafio interativo, esperar
# aqui não adianta nada, precisa parar e reduzir o ritmo de requisições.
HARD_BLOCK_TEXT_HINTS = (
    "acesso está temporariamente restrito",
    "temporarily restricted",
    "access to this page has been denied",
)

# CSS classes de elementos que atrapalham a navegação (ex.: banners de
# anúncio que aparecem sobre a página e bloqueiam o clique no botão de
# próximo). Mantidas aqui pra não poluir a classe Scrapper.
CSS_CLASSES = {
    "obstacles": {
        "bottom_ads": "ZHIlj E s f e"
    }
}

# XPath e regex usados em vários pontos do scrapper.py. Mantidos aqui pra não poluir a classe Scrapper.
XPATHS = {
    "bottom_ads_closer": ".//button[contains(@type, 'button') and contains (@aria-label, 'Close')]",
    "bottom_ads": ".//div[contains(@class, '{}')]".format(CSS_CLASSES["obstacles"]["bottom_ads"]),
    # Modal promocional nativo do Tripadvisor (não é anúncio de terceiros,
    # por isso o bloqueio de domínios não pega esse caso) que às vezes
    # aparece sobre a página e atrasa/bloqueia a hidratação do h1.
    "interstitial_close": '//div[@data-automation="interstitialClose"]//button',
    "accept_cookies": '//*[@id="onetrust-accept-btn-handler"]',
    "language_selector": '//span[text()="English"]',
    "lang_option": './/span[@id="menu-item-{}"]',
    "next_page_button": '//a[contains(@data-smoke-attr, "pagination-next-arrow")]',
    "pagination_info": '//div[contains(text(),"Mostrando")]',
    # O Tripadvisor trocou o atributo de "data-automation" pra
    # "data-test-target" nesse h1 específico (confirmado em snapshot de
    # 27/07/2026). Aceita os dois por segurança, caso volte a mudar ou
    # varie entre páginas.
    "place_name": '//h1[@data-automation="mainH1" or @data-test-target="mainH1"]',
    "review_cards": '//*[@data-automation="reviewCard"]',
    # Botão de "próximo" que às vezes é injetado dentro da própria listagem de cards.
    # Usado para filtrar a lista de reviews sem depender de posição (pop()).
    "review_card_next_button": './/a[contains(@data-smoke-attr, "pagination-next-arrow")]',
    # Pós-redesign (2026): título agora é um <h3> simples, sem classe confiável.
    "review_title": './/h3',
    # JguWG parece ser uma das poucas classes não-hasheadas (estável entre
    # rebuilds); a div pai mudou de classe várias vezes, então miramos
    # direto no span do comentário.
    # ATENÇÃO: em snapshot mais recente (ago/2026) essa classe não bateu com
    # o card real — se os comentários vierem vazios, é bem provável que o
    # TripAdvisor tenha trocado essa classe de novo. Veja o mesmo tratamento
    # dado à data abaixo (busca por conteúdo, não por classe) como referência
    # de como tornar isso mais resistente.
    "review_comment": './/span[contains(@class, "JguWG")]',
    # ANTIGO formato completo ("Feita em DD de mês de AAAA"), mantido como
    # fallback caso o TripAdvisor volte a usá-lo em algum layout/A-B test.
    "review_date_full": './/div[contains(@class, "BNe1O")]',
    # ATUAL (ago/2026): o dia não aparece mais. A data vem como texto solto
    # ("out. de 2025") numa div sem classe estável. Em vez de filtrar por
    # classe (o que já se mostrou instável — "biGQs" não bateu num teste
    # real), pegamos TODOS os div/span do card e testamos o TEXTO de cada
    # um contra o padrão "mês abrev. de ano" — mais lento, mas independe de
    # acertar o nome certo da classe.
    "review_date_candidates": './/div | .//span',
    # Rating: usar data-automation (estável) em vez da classe do svg, que
    # mudou de "UctUV d H0" pra variações só com "UctUV". A nota agora vem
    # como texto de um <title> filho (aria-labelledby), não mais aria-label
    # direto no svg.
    "review_rating": './/*[local-name()="svg" and @data-automation="bubbleRatingImage"]/*[local-name()="title"]',
    # Cidade do avaliador: primeira div.vYLts contém a cidade (span); a
    # segunda div.vYLts (sem span) contém "N contribuições".
    "local": './/div[contains(@class, "vYLts")]',
    # Tipo de viagem (categoria). Em snapshots anteriores vinha junto com uma
    # data curta ("mai. de 2026 • Solo"); se o TripAdvisor voltar a juntar
    # os dois, get_category() ainda separa pelo "•" corretamente.
    "category": './/div[contains(@class, "jXCrq")]',
}

# Transforma textos em dados estruturados (ex.: "out. de 2025" → {"month": 10, "year": 2025})
REGEXES = {
    "starts_with_number": r'^\d.+$',
    # Aceita nota inteira ou com casa decimal ("4 de 5 círculos" ou "4,5 de 5 círculos")
    "rating": r"^(\d+(?:[.,]\d+)?) de \d+ círculos$",
    "get_review_amount": r"^Mostrando.* de (.*) resultados$",
    # A categoria/tipo de viagem, quando vem com data embutida, é "mai. de 2026 • Solo"
    "get_category": r"^.*•\s*(.*)$",
    # Data completa antiga: "Feita em 15 de agosto de 2024"
    "full_date": r"^Feita em (\d{1,2}) de (\w+) de (\d{4})$",
    # Data curta atual, sem dia: "out. de 2025" / "out de 2025"
    "short_date": r"^(\w+)\.?\s+de\s+(\d{4})$",
}

# Domínios de anúncio/tracking de terceiros conhecidos. Bloqueá-los reduz o
# peso da página e evita banners pesados (ex.: anúncios de vídeo/imagem
# grande que aparecem de forma intermitente e atrasam a hidratação da
# página o suficiente pra estourar o timeout do h1). Não afeta o domínio do
# próprio Tripadvisor nem scripts essenciais de anti-bot/consentimento.
AD_TRACKING_DOMAINS = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "google-analytics.com",
    "adservice.google",
    "googletagservices.com",
    "googletagmanager.com",
    "2mdn.net",
    "pagead2.googlesyndication.com",
    "adnxs.com",
    "taboola.com",
    "outbrain.com",
    "criteo.com",
    "criteo.net",
    "amazon-adsystem.com",
    "moatads.com",
    "quantserve.com",
    "scorecardresearch.com",
    "hbomax.com",
    "max.com",
    "pubmatic.com",
    "rubiconproject.com",
    "casalemedia.com",
)


# Meses por extenso em pt-BR (formato completo antigo: "15 de agosto de 2024").
# Mapeados manualmente porque strptime("%B") depende do locale do SO.
MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# Meses abreviados em pt-BR (formato curto atual: "out. de 2025").
MESES_ABREV_PT = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
