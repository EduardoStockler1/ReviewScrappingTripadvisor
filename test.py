from playwright.sync_api import sync_playwright, TimeoutError
import time
import re

URL = (
    "https://www.tripadvisor.com.br/"
    "Attraction_Review-g303441-d1872890-Reviews-"
    "Museu_Oscar_Niemeyer-Curitiba_State_of_Parana.html"
)

ACCEPT_COOKIES_XPATH = '//*[@id="onetrust-accept-btn-handler"]'

INTERSTITIAL_TIMEOUT = 60

def dump_frames_debug(page):
    print("Frames Encontrados:")

    frames = page.frames

    print(f"Total de frames: {len(frames)}\n")

    for i, frame in enumerate(frames):
        parent = frame.parent_frame

        if parent is None:
            parent_index = None
        else:
            try:
                parent_index = frames.index(parent)
            except ValueError:
                parent_index = "?"

        # print(
        #     f"[FRAME {i}] "
        #     f"parent={parent_index} "
        #     f"name={frame.name!r}"
        # )
        # print(f"          url={frame.url!r}")

def find_close_button_in_frame(frame):
    selectors = [
        '[data-automation="interstitialClose"] button',
        '[data-automation="interstitialClose"]',
        '[data-testid="interstitialClose"]',
        '[data-testid*="close"]',
        '[data-automation*="close"]',

        'button[aria-label="Close"]',
        'button[aria-label="Fechar"]',
        'button[aria-label*="Close"]',
        'button[aria-label*="Fechar"]',

        'button[title="Close"]',
        'button[title="Fechar"]',
        'button[title*="Close"]',
        'button[title*="Fechar"]',

        'button[data-testid*="close"]',
        'button[class*="close"]',
        '[class*="close-button"]',
        '[class*="closeButton"]',
        '[class*="CloseButton"]',
    ]

    for selector in selectors:
        try:
            locator = frame.locator(selector).first

            if locator.count() == 0:
                continue

            if locator.is_visible():
                print(f"    Botão encontrado: {selector}")
                return locator

        except Exception:
            continue

    # Tenta encontrar pelo nome do botão
    try:
        locator = frame.get_by_role(
            "button",
            name=re.compile(r"fechar|close|dismiss", re.IGNORECASE)
        ).first

        if locator.count() > 0 and locator.is_visible():
            print("    Botão encontrado pelo nome.")
            return locator

    except Exception:
        pass

    # Tenta encontrar elementos com texto de fechamento
    try:
        locator = frame.get_by_text(
            re.compile(r"^(fechar|close|×|✕)$", re.IGNORECASE)
        ).first

        if locator.count() > 0 and locator.is_visible():
            print("Elemento de fechamento encontrado pelo texto.")
            return locator

    except Exception:
        pass

    return None


def frame_has_interstitial(frame):
    selectors = [
        '[data-automation*="interstitial"]',
        '[data-testid*="interstitial"]',
        '[class*="interstitial"]',
        '[id*="interstitial"]',
    ]

    for selector in selectors:
        try:
            locator = frame.locator(selector)

            if locator.count() > 0:
                for i in range(min(locator.count(), 3)):
                    try:
                        if locator.nth(i).is_visible():
                            return True
                    except Exception:
                        pass

        except Exception:
            pass

    return False


# ============================================================
# FECHA O INTERSTITIAL PROCURANDO EM TODOS OS FRAMES
# ============================================================

def close_interstitial(page, timeout=60):
    print("PROCURANDO INTERSTITIAL")
    deadline = time.monotonic() + timeout
    tentativa = 0

    while time.monotonic() < deadline:
        tentativa += 1

        try:
            frames = page.frames
        except Exception:
            frames = []

        print(f"\nTentativa {tentativa} - "f"{len(frames)} frame(s) encontrados")


        # Procura em todos os frames
        for i, frame in enumerate(frames):
            try:
                print(
                    f"  Verificando frame [{i}]: "
                    f"url={frame.url!r} "
                    f"name={frame.name!r}"
                )

                button = find_close_button_in_frame(frame)

                if button is None:
                    continue

                print("  Botão de fechar encontrado.")

                try:
                    button.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass

                clicked = False

                try:
                    button.click(timeout=5000)
                    clicked = True
                    print("    Clique realizado.")

                except Exception as click_error:
                    print(
                        f"    O clique normal falhou: {click_error}"
                    )
                    print("    Tentando novamente com force=True.")

                    try:
                        button.click(
                            force=True,
                            timeout=5000
                        )
                        clicked = True
                        print("    Clique realizado com force=True.")

                    except Exception as force_error:
                        print(
                            f"    Não foi possível clicar: {force_error}"
                        )

                if clicked:
                    try:
                        button.wait_for(
                            state="hidden",
                            timeout=10000
                        )
                        print("    Botão fechado.")

                    except Exception:
                        print(
                            "    O botão não confirmou o fechamento. "
                            "Verificando novamente."
                        )

                    time.sleep(1)

                    # Verifica se ainda existe algum botão visível
                    # em qualquer frame.
                    still_open = False

                    for check_frame in page.frames:
                        try:
                            check_button = find_close_button_in_frame(
                                check_frame
                            )

                            if check_button is not None:
                                still_open = True
                                break

                        except Exception:
                            continue

                    if not still_open:
                        print("\nInterstitial fechado.")
                        return True

                    print(
                        "    Ainda existe um elemento de fechamento "
                        "visível. Continuando a busca."
                    )

            except Exception as error:
                print(
                    f"    Erro no frame [{i}]: "
                    f"{type(error).__name__}: {error}"
                )

        try:
            main_frame = page.main_frame

            if frame_has_interstitial(main_frame):
                print(
                    "  Possível interstitial encontrado "
                    "no frame principal."
                )

                button = find_close_button_in_frame(main_frame)

                if button is not None:
                    print(
                        "  Botão de fechamento encontrado "
                        "no frame principal."
                    )

                    try:
                        button.click(timeout=5000)

                    except Exception:
                        try:
                            button.click(
                                force=True,
                                timeout=5000
                            )
                        except Exception:
                            pass

                    time.sleep(1)

                    if find_close_button_in_frame(main_frame) is None:
                        print("\nInterstitial fechado.")
                        return True

        except Exception as error:
            print(
                f"  Erro verificando o frame principal: "
                f"{type(error).__name__}: {error}"
            )

        if tentativa % 5 == 0:
            print("\nFrames atuais:")
            dump_frames_debug(page)

        time.sleep(1)

    print(
        "\nNão foi possível fechar o interstitial "
        "dentro do tempo definido."
    )

    dump_frames_debug(page)

    return False

def accept_cookies(page):
    try:

        cookie_button = page.locator(
            f"xpath={ACCEPT_COOKIES_XPATH}"
        )

        cookie_button.wait_for(
            state="visible",
            timeout=30000
        )
        cookie_button.click(timeout=5000)
        try:
            cookie_button.wait_for(
                state="hidden",
                timeout=10000
            )
        except TimeoutError:
            pass

    except TimeoutError:

        print(
            "Nenhum popup de cookies apareceu "
            "ou ele não ficou disponível a tempo."
        )

    except Exception as error:

        print(
            f"Erro ao tratar os cookies: {error}"
        )


with sync_playwright() as playwright:

    print("\nIniciando navegador...")

    browser = playwright.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
    )

    context = browser.new_context(
        locale="pt-BR",

        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),

        viewport={
            "width": 1366,
            "height": 900,
        },
    )

    context.clear_cookies()

    page = context.new_page()
    
    print("\nAbrindo TripAdvisor...")

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print("Página carregada.")

    accept_cookies(page)

    print("\nAguardando o carregamento dos interstitials...")

    time.sleep(1)

    dump_frames_debug(page)

    closed = close_interstitial(
        page,
        timeout=INTERSTITIAL_TIMEOUT,
    )

    if closed:
        print("\n" + "=" * 80)
        print("Interstitial fechado. Continuando a página.")
        print("=" * 80)

    else:
        print("\n" + "=" * 80)
        print("O interstitial não foi fechado.")
        print("=" * 80)

    dump_frames_debug(page)

    input(
        "\nPressione ENTER para fechar o navegador..."
    )

    browser.close()

