from playwright.sync_api import sync_playwright, TimeoutError
import time
import re

INTERSTITIAL_TIMEOUT = 60

def dump_frames_debug(page):
    print("\n" + "=" * 80)
    print("DEBUG — FRAMES")
    print("=" * 80)

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

        print(
            f"[FRAME {i}] "
            f"parent={parent_index} "
            f"name={frame.name!r}"
        )
        # print(f"          url={frame.url!r}")

    print("=" * 80)

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
                print(f"Botão encontrado: {selector}")
                return locator

        except Exception:
            continue

    try:
        locator = frame.get_by_role(
            "button",
            name=re.compile(r"fechar|close|dismiss", re.IGNORECASE)
        ).first

        if locator.count() > 0 and locator.is_visible():
            print("Botão encontrado por role/name")
            return locator

    except Exception:
        pass

    try:
        locator = frame.get_by_text(
            re.compile(r"^(fechar|close|×|✕)$", re.IGNORECASE)
        ).first

        if locator.count() > 0 and locator.is_visible():
            print("Botão de fechamento encontrado por texto")
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

def close_interstitial(page, timeout=60):
    print("Procurando interstitial...")

    deadline = time.monotonic() + timeout
    tentativa = 0

    while time.monotonic() < deadline:
        tentativa += 1

        try:
            frames = page.frames
        except Exception:
            frames = []

        print(f"\nTentativa {tentativa} - {len(frames)} frame(s)")

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

                print("\n Botão de close encontrado. Agora só clicar....")

                try:
                    button.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass

                clicked = False

                try:
                    button.click(timeout=5000)
                    clicked = True
                    print("Clique normal executado.")

                except Exception as click_error:
                    print(f"Clique normal falhou: {click_error}")
                    print("Tentando force=True...")

                    try:
                        button.click(force=True, timeout=5000)
                        clicked = True
                        print("    ✅ Clique force=True executado.")
                    except Exception as force_error:
                        print(f"Clique force=True falhou: {force_error}")

                if clicked:
                    try:
                        button.wait_for(state="hidden", timeout=10000)
                        print("Botão desapareceu.")
                    except Exception:
                        print(
                            "Botão não confirmou desaparecimento; "
                            "verificando o DOM novamente."
                        )

                    time.sleep(1)

                    still_open = False

                    for check_frame in page.frames:
                        try:
                            check_button = find_close_button_in_frame(check_frame)

                            if check_button is not None:
                                still_open = True
                                break

                        except Exception:
                            continue

                    if not still_open:
                        print("\n Intersential Fechou")
                        return True

                    print(
                        "Ainda existe um elemento de fechamento visível"
                    )

            except Exception as error:
                print(
                    f"Erro no frame [{i}]: "
                    f"{type(error).__name__}: {error}"
                )

        try:
            main_frame = page.main_frame

            if frame_has_interstitial(main_frame):
                print("Possível interstitial detectado no frame principal.")

                button = find_close_button_in_frame(main_frame)

                if button is not None:
                    print("\nBOTÃO DO INTERSTITIAL ENCONTRADO NO FRAME PRINCIPAL!")

                    try:
                        button.click(timeout=5000)
                    except Exception:
                        try:
                            button.click(force=True, timeout=5000)
                        except Exception:
                            pass

                    time.sleep(1)

                    if find_close_button_in_frame(main_frame) is None:
                        print("\n Intersential Fechou no frame principal")
                        return True

        except Exception as error:
            print(
                f"Erro verificando frame principal: "
                f"{type(error).__name__}: {error}"
            )

        if tentativa % 5 == 0:
            print("\nDump dos frames atuais:")
            dump_frames_debug(page)

        time.sleep(1)

    print("\nNão foi possível fechar o interstitial dentro do timeout.")
    dump_frames_debug(page)

    return False


