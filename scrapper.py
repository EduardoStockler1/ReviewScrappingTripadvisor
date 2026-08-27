# coding: utf-8
import datetime
import os
import random
import re
import time
import unicodedata
from logger import debug, error, info
from typing import Dict, List, Optional, Union, Tuple

from playwright.sync_api import (
    sync_playwright,
    Locator,
    TimeoutError,
)

from config import HEADLESS

try:
    # Opcionais: se não existirem no config.py, caem em valores padrão.
    from config import STORAGE_STATE_PATH
except ImportError:
    STORAGE_STATE_PATH = "storage_state.json"

try:
    from config import MIN_DELAY_BETWEEN_ACTIONS, MAX_DELAY_BETWEEN_ACTIONS
except ImportError:
    MIN_DELAY_BETWEEN_ACTIONS = 1.5
    MAX_DELAY_BETWEEN_ACTIONS = 4.0

# Indícios de que a página atual é um desafio anti-bot (Cloudflare/PerimeterX)
# em vez do conteúdo real do TripAdvisor.
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
# aqui não adianta nada — é preciso parar e reduzir o ritmo de requisições.
HARD_BLOCK_TEXT_HINTS = (
    "acesso está temporariamente restrito",
    "temporarily restricted",
    "access to this page has been denied",
)

# Limite de reviews a coletar no total (soma de todas as páginas) — útil
# pra testar o script rapidamente sem esperar todas as páginas carregarem.
# None = sem limite, coleta tudo.
MAX_REVIEWS = 50

CSS_CLASSES = {
    "obstacles": {
        "bottom_ads": "ZHIlj E s f e"
    }
}


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


class Scrapper:

    # =========================================================================
    # 1) CRIAÇÃO / FECHAMENTO DO NAVEGADOR
    # =========================================================================

    def __init__(self):
        self.playwright = sync_playwright().start()

        # Limita quantas vezes salvamos o HTML de um card de review com
        # campo ausente, pra não encher o disco se o problema for
        # sistemático (todas as milhares de reviews com o mesmo defeito).
        self.__review_dumps_done = 0

        # Soma de reviews já extraídos em todas as páginas — usado pelo
        # limite de teste MAX_REVIEWS (ver scrap_page/has_reached_review_limit).
        self.__total_reviews_collected = 0

        # Args que reduzem sinais óbvios de automação. Não é infalível contra
        # PerimeterX/Cloudflare, mas evita os detectores mais básicos.
        self.browser = self.playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
            ]
        )

        # Contexto persistente: se já existir uma sessão salva (depois de
        # você resolver o captcha manualmente uma vez com HEADLESS=False),
        # ela é reaproveitada aqui — evita começar do zero "anônimo" a cada
        # execução, o que é justamente o padrão que dispara o desafio depois
        # de várias requisições.
        context_kwargs = {
            "locale": "pt-BR",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1366, "height": 900},
        }
        if os.path.exists(STORAGE_STATE_PATH):
            debug(f"Reaproveitando sessão salva em {STORAGE_STATE_PATH}")
            context_kwargs["storage_state"] = STORAGE_STATE_PATH

        self.context = self.browser.new_context(**context_kwargs)

        # Bloqueia requisições pra domínios de anúncio/tracking conhecidos.
        # Registramos uma regex específica em vez de "**/*" + filtro em
        # Python: dessa forma o próprio Playwright só aciona nosso callback
        # quando a URL já bate com o padrão dos domínios de anúncio, sem
        # round-trip pro nosso processo em toda requisição legítima da
        # página (imagens de review, chamadas de API etc.), que estava
        # adicionando overhead suficiente pra atrasar o carregamento.
        ad_domains_pattern = re.compile(
            "|".join(re.escape(domain) for domain in AD_TRACKING_DOMAINS)
        )
        self.context.route(ad_domains_pattern, lambda route: route.abort())

        self.page = self.context.new_page()

        # navigator.webdriver=true é o sinal mais básico e mais checado por
        # scripts anti-bot. Sobrescrevemos antes de qualquer script da
        # página rodar.
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    # Permite usar "with Scrapper() as s:" garantindo o fechamento do browser
    # mesmo se uma exceção estourar no meio da raspagem.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        debug("Fechando navegador")
        try:
            self.context.close()
        finally:
            try:
                self.browser.close()
            finally:
                self.playwright.stop()

    def save_session(self):
        """Persiste cookies/local storage atuais em disco, para reuso nas
        próximas execuções (evita repetir o desafio anti-bot a cada run)."""
        try:
            self.context.storage_state(path=STORAGE_STATE_PATH)
            debug(f"Sessão salva em {STORAGE_STATE_PATH}")
        except Exception as e:
            error(f"Não foi possível salvar a sessão: {e}")

    # =========================================================================
    # 2) ABRIR A PÁGINA (+ desafios anti-bot, cookies, obstáculos)
    # =========================================================================

    def open_page(self, url: str, cookies: bool = True):
        t0 = time.monotonic()
        info("[TIMING] Abrindo página {}".format(url))
        # domcontentloaded é mais confiável que networkidle em páginas com
        # anúncios/telemetria que nunca "silenciam" a rede.
        self.page.goto(
            url,
            wait_until="domcontentloaded"
        )
        info(f"[TIMING] goto concluído em {time.monotonic() - t0:.1f}s")

        # Verifica ANTES de tentar aceitar cookies/H1: se caiu num desafio
        # anti-bot, não adianta procurar esses elementos, eles não existem
        # nessa tela.
        self.__wait_out_challenge()
        info(f"[TIMING] challenge check concluído em {time.monotonic() - t0:.1f}s")

        if cookies:
            self.__handle_cookies()
            info(f"[TIMING] cookies tratados em {time.monotonic() - t0:.1f}s")
            # O layout muda ao fechar o banner (re-render); um pequeno
            # respiro evita que os próximos locators disputem com esse
            # re-render em andamento.
            self.page.wait_for_timeout(1000)

        self.__handle_obstacles()
        info(f"[TIMING] obstáculos tratados em {time.monotonic() - t0:.1f}s")

    def __is_challenge_page(self) -> bool:
        title = unicodedata.normalize("NFC", self.page.title() or "").lower()
        return any(hint in title for hint in CHALLENGE_TITLE_HINTS)

    def __is_hard_block_page(self) -> bool:
        # Esse bloqueio específico usa o layout normal do site (logo do
        # Tripadvisor, título da página normal), então checamos pelo texto
        # visível do corpo, não pelo <title>.
        try:
            body_text = self.page.locator("body").text_content(timeout=3000) or ""
        except TimeoutError:
            return False
        body_text = unicodedata.normalize("NFC", body_text).lower()
        return any(hint in body_text for hint in HARD_BLOCK_TEXT_HINTS)

    def __wait_out_challenge(self):
        """Se detectar uma tela de desafio (captcha), dá tempo extra pra você
        resolver manualmente (só faz sentido com HEADLESS=False). Depois de
        resolvido, salva a sessão pra não precisar repetir no próximo run.

        Se for um BLOQUEIO TERMINAL (sem captcha, só uma mensagem de acesso
        restrito), não há nada pra esperar — falha imediatamente com uma
        mensagem clara, em vez de travar 3 minutos à toa."""

        if self.__is_hard_block_page():
            raise RuntimeError(
                "Bloqueio anti-bot terminal do TripAdvisor (sem captcha pra "
                "resolver, IP provavelmente sinalizado). Não adianta tentar "
                "de novo imediatamente — espere um período bem mais longo "
                "(horas), reduza THREADS para 1, aumente os delays entre "
                "requisições e considere trocar de IP se o problema persistir."
            )

        if not self.__is_challenge_page():
            return

        if HEADLESS:
            raise RuntimeError(
                "Desafio anti-bot detectado com HEADLESS=True (não dá pra "
                "resolver captcha sem tela). Rode uma vez com HEADLESS=False "
                "no config.py, resolva o captcha manualmente, e a sessão "
                "será salva para as próximas execuções."
            )

        info("Desafio anti-bot detectado — resolva manualmente na janela do navegador...")
        # Espera bastante (o usuário precisa clicar/resolver o captcha).
        # Consideramos "resolvido" quando o h1 da página finalmente aparece.
        self.page.locator(f'xpath={XPATHS["place_name"]}').wait_for(
            state="visible", timeout=180000
        )
        info("Desafio resolvido, salvando sessão")
        self.save_session()

    def __handle_cookies(self):
        cookie_button = self.page.locator(f'xpath={XPATHS["accept_cookies"]}')
        try:
            # Páginas com bastante anúncio/tracking de terceiros (ex.: banners
            # patrocinados) atrasam a injeção do script do OneTrust. 15s se
            # mostrou curto demais em alguns casos; damos mais margem aqui.
            cookie_button.wait_for(state="visible", timeout=30000)
            cookie_button.click(timeout=5000)

            # Não basta ter clicado: confirmamos que o botão realmente sumiu
            # do DOM antes de seguir, já que o clique pode falhar
            # silenciosamente se o layout mudar no meio do processo.
            cookie_button.wait_for(state="hidden", timeout=10000)

            debug("Cookies aceitos")

        except TimeoutError:
            debug("Sem popup de cookies (ou não desapareceu a tempo)")
            self.__dump_debug_snapshot("cookie_banner_issue")

    def __handle_obstacles(self):
        self.__handle_interstitial()

        bottom_ads = self.__have_ads_at_bottom()
        if bottom_ads is not None:
            self.__handle_ads(bottom_ads)

    def __handle_interstitial(self, wait_timeout: int = 15000):
        """Fecha o modal promocional nativo do Tripadvisor (cupom/desconto),
        que aparece de forma intermitente sobre a página e pode atrasar ou
        bloquear a hidratação do h1 se não for fechado.

        wait_timeout menor (ex.: 1000ms) permite chamar isso repetidamente
        num loop de polling sem gastar muito tempo em cada tentativa."""
        t0 = time.monotonic()
        close_button = self.page.locator(f'xpath={XPATHS["interstitial_close"]}')
        try:
            # wait_for(visible) espera o modal aparecer (ele é injetado via
            # JS, pode demorar); force=True ignora checagens de
            # actionability que às vezes falham em modais com animação de
            # entrada/saída.
            close_button.first.wait_for(state="visible", timeout=wait_timeout)
            close_button.first.click(force=True, timeout=5000)
            self.page.wait_for_timeout(500)
            info(f"[TIMING] modal interstitial fechado em {time.monotonic() - t0:.1f}s")
            return True
        except TimeoutError:
            return False

    def __have_ads_at_bottom(self) -> Optional[Locator]:
        debug("Verificando se há anúncios no final da página")

        bottom_ads = self.page.locator(f'xpath={XPATHS["bottom_ads"]}')

        if bottom_ads.count() > 0:
            return bottom_ads

        return None

    def __handle_ads(self, bottom_ads: Locator):
        debug("Fechando anúncios")
        try:
            bottom_ads.locator(f'xpath={XPATHS["bottom_ads_closer"]}').click(timeout=5000)
        except TimeoutError:
            debug("Botão de fechar anúncio não encontrado/clicável")

    def get_page_title(self, max_wait_seconds: int = 120, poll_seconds: int = 5):
        t0 = time.monotonic()
        info("[TIMING] Esperando h1 (com polling do interstitial)...")

        while time.monotonic() - t0 < max_wait_seconds:
            # Checagem rápida (não bloqueia muito se não tiver nada): se o
            # anúncio apareceu nesse meio-tempo, fecha antes de tentar o h1
            # de novo.
            if self.__handle_interstitial(wait_timeout=500):
                info(f"[TIMING] interstitial fechado durante polling em {time.monotonic() - t0:.1f}s")

            try:
                result = self.page.locator(
                    f'xpath={XPATHS["place_name"]}'
                ).text_content(timeout=poll_seconds * 1000)
                info(f"[TIMING] h1 obtido em {time.monotonic() - t0:.1f}s")
                return result
            except TimeoutError:
                continue

        info(f"[TIMING] h1 NÃO apareceu após {time.monotonic() - t0:.1f}s (polling esgotado)")
        self.__dump_debug_snapshot("get_page_title_timeout")
        raise TimeoutError(
            f"h1 não apareceu após {max_wait_seconds}s de polling, mesmo "
            "tentando fechar o interstitial repetidamente."
        )

    # =========================================================================
    # 3) PAGINAÇÃO
    # =========================================================================

    def wait_reviews_to_load(self):
        self.page.locator(
            f'xpath={XPATHS["pagination_info"]}'
        ).wait_for()

    def get_review_amount(self):
        debug("Obtendo quantidade de reviews no ponto turístico")
        pagination_info = self.page.locator(f'xpath={XPATHS["pagination_info"]}').text_content()
        pattern = re.compile(REGEXES["get_review_amount"])
        amount = 0
        try:
            review_amount_str = re.match(pattern, pagination_info).group(1)
            amount = int(review_amount_str.replace(".", ""))
            debug(f"{amount} reviews no total")
        except Exception as e:
            error("Erro ao obter a quantidade de reviews: {}".format(e))

        return amount

    def has_next_page(self):
        debug("Verificando se há próxima página")

        next_button = self.page.locator(f'xpath={XPATHS["next_page_button"]}')

        if next_button.count() == 0:
            return False

        # O botão pode continuar presente no DOM na última página, porém
        # desabilitado. count() > 0 sozinho não é suficiente.
        aria_disabled = next_button.first.get_attribute("aria-disabled")
        class_attr = next_button.first.get_attribute("class") or ""

        if aria_disabled == "true" or "disabled" in class_attr.lower():
            return False

        return True

    def go_to_next_page(self, page_title):

        info(f"{page_title} -> Indo para próxima página")

        # Pausa curta antes de navegar: evita o padrão "clique instantâneo
        # em intervalos idênticos" que é um dos sinais mais fáceis de
        # detectar em automação.
        self.__human_delay()

        self.page.locator(
            f'xpath={XPATHS["next_page_button"]}'
        ).click()

        self.__wait_out_challenge()

    def __human_delay(self):
        """Pausa curta e aleatória entre ações, pra não parecer um robô
        martelando requisições em intervalos perfeitamente regulares."""
        time.sleep(random.uniform(MIN_DELAY_BETWEEN_ACTIONS, MAX_DELAY_BETWEEN_ACTIONS))

    # =========================================================================
    # 4) EXTRAIR OS REVIEWS DA PÁGINA ATUAL
    # =========================================================================

    def scrap_page(self) -> Tuple[List[Dict], int]:
        debug("Extraindo reviews da página")
        raw_reviews = self.page.locator(f'xpath={XPATHS["review_cards"]}').all()
        page_reviews = []

        counter = 0
        skipped = 0
        for review in raw_reviews:
            # Limite de teste: para de extrair assim que atingir o total
            # (soma de todas as páginas já processadas), mesmo no meio desta.
            if MAX_REVIEWS is not None and self.__total_reviews_collected >= MAX_REVIEWS:
                info(f"Limite de {MAX_REVIEWS} reviews atingido. Parando a extração.")
                break

            # Em vez de assumir por posição (pop()) que o último elemento é um
            # botão, filtramos explicitamente qualquer card que contenha o
            # botão de paginação dentro dele.
            if review.locator(f'xpath={XPATHS["review_card_next_button"]}').count() > 0:
                continue

            new_data = self.handle_review(review)

            if new_data is not None:
                info("Review extraído: {}".format(new_data))
                page_reviews.append(new_data)
                counter += 1
                self.__total_reviews_collected += 1
            else:
                skipped += 1

        info(f"Encontrados {counter} reviews ({skipped} ignorados por erro de parsing). "
             f"Total acumulado: {self.__total_reviews_collected}.")
        return page_reviews, counter

    def has_reached_review_limit(self) -> bool:
        """Usado pelo loop externo de paginação para saber se deve parar
        de chamar go_to_next_page() (limite de teste já atingido)."""
        return MAX_REVIEWS is not None and self.__total_reviews_collected >= MAX_REVIEWS

    def handle_review(self, review) -> Optional[Dict]:
        # Qualquer falha ao extrair um campo (elemento ausente, formato
        # inesperado etc.) agora resulta em None em vez de derrubar a
        # raspagem inteira da página.
        try:
            # .first: o card pode conter uma resposta do estabelecimento
            # logo abaixo, que às vezes reusa elementos parecidos (outro
            # h3, outro texto) — sem .first isso vira "strict mode
            # violation" por casar mais de um elemento.
            title = self.__safe_text(
                review.locator(f'xpath={XPATHS["review_title"]}')
            )

            comment = self.__safe_text(
                review.locator(f'xpath={XPATHS["review_comment"]}')
            )

            raw_date = self.get_review_date(review)
            date = self.parse_date(raw_date) if raw_date else None

            # Pós-redesign: a nota vem como texto do <title> filho do svg
            # (aria-labelledby), não mais como atributo aria-label direto.
            raw_rating = self.__safe_text(
                review.locator(f'xpath={XPATHS["review_rating"]}')
            )
            rating = self.parse_rating(raw_rating)

            local = self.get_local(review)

            category = self.get_category(review)

            # Se algum campo essencial veio vazio, salva o HTML desse card
            # específico (limitado a poucas vezes por execução) — assim dá
            # pra diagnosticar rapidamente se algum seletor mudou de novo,
            # sem precisar de mais uma rodada de prints manuais.
            if title is None or comment is None or raw_date is None:
                self.__dump_review_html_once(review, "campo_ausente")

            return {
                "title": title,
                "comment": comment,
                "date": date,
                "rating": rating,
                "local": local,
                "category": category,
            }
        except Exception as e:
            error(f"Erro ao processar review, ignorando: {e}")
            return None

    def __get_date_category_raw_text(self, review: Locator) -> str:
        """
        Texto bruto da div que junta data curta e categoria de viagem
        (ex.: "ago. de 2026 • Casal", ou só "ago. de 2026" quando o
        avaliador não marcou tipo de viagem). Usado tanto por
        get_review_date quanto por get_category — é a MESMA div nos dois
        casos, só cortamos em pedaços diferentes.
        """
        locator = review.locator(f'xpath={XPATHS["category"]}')
        if locator.count() == 0:
            return ""
        return (locator.first.text_content() or "").strip()

    def get_review_date(self, review: Locator) -> Optional[str]:
        """
        Retorna o texto bruto da data (ainda sem parsear), tentando três
        formas, da mais específica pra mais genérica:

        1. Formato completo antigo ("Feita em DD de mês de AAAA"), via a
           classe conhecida BNe1O — mantido como fallback caso volte.
        2. A parte ANTES do "•" na div de categoria (ver
           __get_date_category_raw_text): é onde a data mora quando vem
           junto com o tipo de viagem ("ago. de 2026 • Casal").
        3. Fallback: varre todo div/span do card em busca de um texto que
           seja SÓ a data (sem categoria colada), pro caso de vir isolada.
        """
        debug("Obtendo data do review")

        full_date = self.__safe_text(review.locator(f'xpath={XPATHS["review_date_full"]}'))
        if full_date:
            return full_date

        short_date_pattern = re.compile(REGEXES["short_date"], re.IGNORECASE)

        combined_text = self.__get_date_category_raw_text(review)
        if combined_text:
            date_part = combined_text.split("•")[0].strip()
            if short_date_pattern.match(date_part):
                return date_part

        candidates = review.locator(f'xpath={XPATHS["review_date_candidates"]}')
        for i in range(candidates.count()):
            text = (candidates.nth(i).text_content() or "").strip()
            if short_date_pattern.match(text):
                return text

        return None

    def parse_date(self, date: str) -> Optional[str]:
        """
        Aceita os dois formatos vindos de get_review_date:
          - completo: "Feita em 15 de agosto de 2024" -> "15/08/2024"
          - curto (sem dia): "out. de 2025" -> "10/2025"
        """
        debug("Parseando data")
        date = date.strip()

        full_match = re.match(REGEXES["full_date"], date)
        if full_match:
            dia, mes_nome, ano = full_match.groups()
            mes = MESES_PT.get(mes_nome.lower())
            if mes is None:
                error(f"Mês não reconhecido: '{mes_nome}'")
                return None
            try:
                return datetime.date(int(ano), mes, int(dia)).strftime("%d/%m/%Y")
            except ValueError as e:
                error(f"Data inválida ({date}): {e}")
                return None

        short_match = re.match(REGEXES["short_date"], date, re.IGNORECASE)
        if short_match:
            mes_abrev, ano = short_match.groups()
            mes = MESES_ABREV_PT.get(mes_abrev.lower().rstrip('.'))
            if mes is None:
                error(f"Mês abreviado não reconhecido: '{mes_abrev}'")
                return None
            # Sem dia disponível nesse formato — retornamos só mês/ano em vez
            # de inventar um dia (ex.: "01") que passaria uma precisão falsa.
            return f"{mes:02d}/{ano}"

        error(f"Formato de data inesperado: '{date}'")
        return None

    def parse_rating(self, rating_str: Optional[str]) -> Optional[float]:
        debug("Parseando avaliação do turista")

        if not rating_str:
            error("Rating vazio ou ausente")
            return None

        pattern = re.compile(REGEXES["rating"])
        try:
            match = re.match(pattern, rating_str)
            if not match:
                raise ValueError(f"Não bateu com o padrão esperado: '{rating_str}'")
            return float(match.group(1).replace(",", "."))
        except Exception as e:
            error("Erro ao parsear o rating ({}): {}".format(rating_str, e))
            return None

    def get_local(self, review: Locator) -> str:
        debug("Obtendo local no turista")
        # Pós-redesign: cidade e contribuições vêm em divs "vYLts" separadas
        # (a primeira é a cidade, dentro de um <span>; a segunda é só texto
        # "N contribuições"). Não precisa mais de regex pra separar número
        # colado no texto, como no formato antigo.
        vylts_divs = review.locator(f'xpath={XPATHS["local"]}')
        count = vylts_divs.count()

        if count == 0:
            return ""

        first = vylts_divs.nth(0)
        span = first.locator("xpath=.//span")

        if span.count() > 0:
            return (span.first.text_content() or "").strip()

        # Fallback: se não tiver span dentro, mas o texto não parecer ser
        # "N contribuições", assume que é a cidade mesmo.
        text = (first.text_content() or "").strip()
        if "contribui" in text.lower():
            return ""
        return text

    def get_category(self, review):
        combined_text = self.__get_date_category_raw_text(review)
        if not combined_text:
            return ""

        match = re.match(REGEXES["get_category"], combined_text)
        return match.group(1) if match else ""

    def __safe_text(self, locator: Locator, timeout: int = 3000) -> Optional[str]:
        """Pega o texto do primeiro elemento que casar, sem pagar o preço de
        um timeout longo (30s padrão) quando o elemento simplesmente não
        existe nesse card. count()==0 é praticamente instantâneo (não
        espera nada aparecer), então cobre o caso mais comum de falha
        rápido; o timeout curto no text_content cobre o caso raro de o
        elemento existir mas ainda estar renderizando."""
        if locator.count() == 0:
            return None
        try:
            return locator.first.text_content(timeout=timeout)
        except TimeoutError:
            return None

    # =========================================================================
    # 5) DIAGNÓSTICO (screenshots/HTML salvos em caso de falha)
    # =========================================================================

    def __dump_debug_snapshot(self, label: str):
        """Salva screenshot + HTML da página no momento da falha, em
        debug_snapshots/, pra diagnosticar bloqueios/telas inesperadas sem
        precisar reproduzir manualmente."""
        try:
            os.makedirs("debug_snapshots", exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base = f"debug_snapshots/{label}_{stamp}"
            self.page.screenshot(path=f"{base}.png", full_page=True)
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(self.page.content())
            error(f"Snapshot de diagnóstico salvo em {base}.png / {base}.html")
        except Exception as e:
            error(f"Não foi possível salvar snapshot de diagnóstico: {e}")

    def __dump_review_html_once(self, review: Locator, label: str, max_dumps: int = 3):
        """Salva o outerHTML de um card de review específico quando um campo
        essencial vem ausente, limitado a poucas vezes por execução (o
        problema costuma ser sistemático — não precisa de milhares de
        arquivos iguais pra diagnosticar)."""
        if self.__review_dumps_done >= max_dumps:
            return
        try:
            os.makedirs("debug_snapshots", exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = f"debug_snapshots/review_{label}_{stamp}.html"
            html = review.evaluate("el => el.outerHTML")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            self.__review_dumps_done += 1
            error(f"HTML do card de review salvo em {path}")
        except Exception as e:
            error(f"Não foi possível salvar HTML do card de review: {e}")

    def print_element(self, element):
        element.screenshot(path=f"{os.getcwd()}/element.png")