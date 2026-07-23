import asyncio
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from playwright.async_api import (
    BrowserContext,
    Dialog,
    Download,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)
from pydantic import BaseModel, HttpUrl


app = FastAPI(
    title="Fiscaliza Dados Públicos API",
    version="0.10.0",
    description=(
        "API para acessar processos públicos do SEI, identificar "
        "documentos incompatíveis com a consolidação, gerar o PDF "
        "possível e preservar a rastreabilidade das exclusões."
    ),
)


PASTA_DOWNLOADS = Path("downloads").resolve()
PASTA_DOWNLOADS.mkdir(parents=True, exist_ok=True)

TIMEOUT_NAVEGACAO_MS = int(
    os.getenv("TIMEOUT_NAVEGACAO_MS", "60000")
)

# Tempo máximo para cada tentativa de geração.
TIMEOUT_TENTATIVA_PDF_MS = int(
    os.getenv("TIMEOUT_TENTATIVA_PDF_MS", "600000")
)

# Evita repetição indefinida caso vários documentos apresentem erro.
MAX_TENTATIVAS_PDF = int(
    os.getenv("MAX_TENTATIVAS_PDF", "10")
)


class ProcessoRequest(BaseModel):
    link_processo_url: HttpUrl


@app.get("/")
def raiz() -> dict[str, str]:
    return {
        "status": "online",
        "versao": "0.10.0",
        "mensagem": "Fiscaliza Dados Públicos API em funcionamento.",
    }


@app.get(
    "/downloads/{nome_arquivo}",
    name="baixar_arquivo",
)
def baixar_arquivo(nome_arquivo: str) -> FileResponse:
    nome_seguro = Path(nome_arquivo).name
    caminho_arquivo = (
        PASTA_DOWNLOADS / nome_seguro
    ).resolve()

    if caminho_arquivo.parent != PASTA_DOWNLOADS:
        raise HTTPException(
            status_code=400,
            detail="Nome de arquivo inválido.",
        )

    if not caminho_arquivo.exists():
        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado.",
        )

    if not caminho_arquivo.is_file():
        raise HTTPException(
            status_code=400,
            detail=(
                "O caminho informado não corresponde "
                "a um arquivo."
            ),
        )

    return FileResponse(
        path=str(caminho_arquivo),
        media_type="application/pdf",
        filename=caminho_arquivo.name,
    )


async def extrair_documentos(
    pagina: Page,
    link_processo: str,
) -> list[dict[str, str]]:
    documentos: list[dict[str, str]] = []

    todos_links = pagina.locator("a")
    quantidade_links = await todos_links.count()

    for indice in range(quantidade_links):
        elemento_link = todos_links.nth(indice)

        try:
            numero_documento = (
                await elemento_link.inner_text()
            ).strip()
        except Exception:
            continue

        if not re.fullmatch(
            r"\d{7,}",
            numero_documento,
        ):
            continue

        linha = elemento_link.locator(
            "xpath=ancestor::tr[1]"
        )

        if await linha.count() == 0:
            continue

        celulas = linha.locator("td")
        quantidade_celulas = await celulas.count()

        textos: list[str] = []

        for indice_celula in range(
            quantidade_celulas
        ):
            try:
                texto = (
                    await celulas
                    .nth(indice_celula)
                    .inner_text()
                ).strip()
            except Exception:
                texto = ""

            textos.append(texto)

        href = await elemento_link.get_attribute(
            "href"
        )

        documentos.append(
            {
                "numero_documento": numero_documento,
                "tipo_documento": (
                    textos[2]
                    if quantidade_celulas > 2
                    else ""
                ),
                "data_documento": (
                    textos[3]
                    if quantidade_celulas > 3
                    else ""
                ),
                "unidade": (
                    textos[4]
                    if quantidade_celulas > 4
                    else ""
                ),
                "url_documento": (
                    urljoin(link_processo, href)
                    if href
                    and not href.lower().startswith(
                        "javascript:"
                    )
                    else ""
                ),
            }
        )

    return documentos


async def selecionar_todos_documentos(
    pagina: Page,
) -> tuple[int, int]:
    checkboxes = pagina.locator(
        "input[type='checkbox']"
    )

    quantidade_total = await checkboxes.count()
    quantidade_selecionada = 0

    for indice in range(quantidade_total):
        checkbox = checkboxes.nth(indice)

        try:
            if not await checkbox.is_visible():
                continue

            if not await checkbox.is_enabled():
                continue

            if not await checkbox.is_checked():
                await checkbox.check()

            if await checkbox.is_checked():
                quantidade_selecionada += 1

        except Exception:
            continue

    return (
        quantidade_total,
        quantidade_selecionada,
    )


def extrair_documento_problematico(
    mensagem: str,
) -> dict[str, str] | None:
    """
    Exemplo de mensagem do SEI:

    Erro na manipulação do documento
    "Extrato EMP 34101.0001.25.00696-3 (20293539)".
    """

    padrao_completo = re.search(
        r'documento\s+"([^"]*?)\s*'
        r'\((\d{7,})\)"',
        mensagem,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if padrao_completo:
        return {
            "numero_documento": (
                padrao_completo.group(2).strip()
            ),
            "descricao_informada": (
                padrao_completo.group(1).strip()
            ),
        }

    numeros_entre_parenteses = re.findall(
        r"\((\d{7,})\)",
        mensagem,
    )

    if numeros_entre_parenteses:
        return {
            "numero_documento": (
                numeros_entre_parenteses[-1]
            ),
            "descricao_informada": "",
        }

    return None


async def desmarcar_documento(
    pagina: Page,
    numero_documento: str,
) -> bool:
    links = pagina.locator("a")
    quantidade_links = await links.count()

    for indice in range(quantidade_links):
        link = links.nth(indice)

        try:
            texto = (
                await link.inner_text()
            ).strip()
        except Exception:
            continue

        if texto != numero_documento:
            continue

        linha = link.locator(
            "xpath=ancestor::tr[1]"
        )

        if await linha.count() == 0:
            return False

        checkbox = linha.locator(
            "input[type='checkbox']"
        ).first

        if await checkbox.count() == 0:
            return False

        if not await checkbox.is_enabled():
            return False

        if await checkbox.is_checked():
            await checkbox.uncheck()

        return not await checkbox.is_checked()

    return False


async def contar_documentos_selecionados(
    pagina: Page,
) -> int:
    checkboxes = pagina.locator(
        "input[type='checkbox']"
    )

    quantidade = await checkboxes.count()
    selecionados = 0

    for indice in range(quantidade):
        checkbox = checkboxes.nth(indice)

        try:
            if (
                await checkbox.is_visible()
                and await checkbox.is_checked()
            ):
                selecionados += 1
        except Exception:
            continue

    return selecionados


async def tratar_dialogo(
    dialogo: Dialog,
    fila_eventos: asyncio.Queue,
    alertas: list[str],
) -> None:
    mensagem = dialogo.message.strip()

    if mensagem and mensagem not in alertas:
        alertas.append(mensagem)

    await fila_eventos.put(
        {
            "tipo": "dialogo",
            "mensagem": mensagem,
        }
    )

    try:
        await dialogo.accept()
    except Exception:
        try:
            await dialogo.dismiss()
        except Exception:
            pass


def registrar_pagina(
    pagina: Page,
    fila_eventos: asyncio.Queue,
    paginas_monitoradas: list[Page],
    alertas: list[str],
) -> None:
    if pagina in paginas_monitoradas:
        return

    paginas_monitoradas.append(pagina)

    def ao_download(
        download: Download,
    ) -> None:
        asyncio.create_task(
            fila_eventos.put(
                {
                    "tipo": "download",
                    "download": download,
                    "pagina": pagina,
                }
            )
        )

    def ao_dialogo(
        dialogo: Dialog,
    ) -> None:
        asyncio.create_task(
            tratar_dialogo(
                dialogo=dialogo,
                fila_eventos=fila_eventos,
                alertas=alertas,
            )
        )

    pagina.on("download", ao_download)
    pagina.on("dialog", ao_dialogo)


def registrar_contexto(
    contexto: BrowserContext,
    pagina_principal: Page,
    fila_eventos: asyncio.Queue,
    paginas_monitoradas: list[Page],
    alertas: list[str],
) -> None:
    registrar_pagina(
        pagina=pagina_principal,
        fila_eventos=fila_eventos,
        paginas_monitoradas=paginas_monitoradas,
        alertas=alertas,
    )

    def ao_abrir_pagina(
        nova_pagina: Page,
    ) -> None:
        registrar_pagina(
            pagina=nova_pagina,
            fila_eventos=fila_eventos,
            paginas_monitoradas=paginas_monitoradas,
            alertas=alertas,
        )

    contexto.on("page", ao_abrir_pagina)


async def limpar_fila(
    fila_eventos: asyncio.Queue,
) -> None:
    while not fila_eventos.empty():
        try:
            fila_eventos.get_nowait()
            fila_eventos.task_done()
        except asyncio.QueueEmpty:
            break


async def salvar_download(
    download: Download,
    request: Request,
) -> dict[str, Any]:
    erro_download = await download.failure()

    if erro_download:
        return {
            "download_realizado": False,
            "nome_arquivo": "",
            "caminho_arquivo": "",
            "tamanho_arquivo_bytes": 0,
            "download_url": "",
            "erro_download": erro_download,
            "mensagem_download": (
                "O navegador informou erro durante "
                f"o download: {erro_download}"
            ),
        }

    nome_original = (
        download.suggested_filename
        or "processo_sei.pdf"
    )

    nome_arquivo = Path(nome_original).name

    if not nome_arquivo.lower().endswith(".pdf"):
        nome_arquivo = (
            f"{nome_arquivo}.pdf"
        )

    caminho_destino = (
        PASTA_DOWNLOADS / nome_arquivo
    ).resolve()

    if caminho_destino.parent != PASTA_DOWNLOADS:
        raise HTTPException(
            status_code=400,
            detail="Nome de arquivo gerado inválido.",
        )

    await download.save_as(
        str(caminho_destino)
    )

    if not caminho_destino.exists():
        return {
            "download_realizado": False,
            "nome_arquivo": nome_arquivo,
            "caminho_arquivo": "",
            "tamanho_arquivo_bytes": 0,
            "download_url": "",
            "erro_download": "",
            "mensagem_download": (
                "O download foi iniciado, mas o "
                "arquivo não foi encontrado."
            ),
        }

    return {
        "download_realizado": True,
        "nome_arquivo": nome_arquivo,
        "caminho_arquivo": str(
            caminho_destino
        ),
        "tamanho_arquivo_bytes": (
            caminho_destino.stat().st_size
        ),
        "download_url": str(
            request.url_for(
                "baixar_arquivo",
                nome_arquivo=nome_arquivo,
            )
        ),
        "erro_download": "",
        "mensagem_download": (
            "PDF consolidado gerado e "
            "disponibilizado pela API."
        ),
    }


async def tentar_gerar_pdf(
    pagina: Page,
    fila_eventos: asyncio.Queue,
) -> dict[str, Any]:
    await limpar_fila(fila_eventos)

    botao_pdf = pagina.locator(
        "button[name='btnGerarPdf']"
    )

    if await botao_pdf.count() == 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "O botão Gerar PDF não foi "
                "localizado."
            ),
        )

    await botao_pdf.click()

    limite_segundos = (
        TIMEOUT_TENTATIVA_PDF_MS / 1000
    )

    while True:
        try:
            evento = await asyncio.wait_for(
                fila_eventos.get(),
                timeout=limite_segundos,
            )
        except asyncio.TimeoutError:
            return {
                "resultado": "timeout",
                "mensagem": (
                    "O SEI não iniciou o download "
                    "nem apresentou um erro dentro "
                    "do tempo previsto."
                ),
            }

        tipo_evento = evento.get("tipo")

        if tipo_evento == "download":
            return {
                "resultado": "download",
                "download": evento["download"],
                "pagina": evento["pagina"],
            }

        if tipo_evento == "dialogo":
            mensagem = evento.get(
                "mensagem",
                "",
            )

            documento_problematico = (
                extrair_documento_problematico(
                    mensagem
                )
            )

            if documento_problematico:
                return {
                    "resultado": (
                        "documento_problematico"
                    ),
                    "mensagem": mensagem,
                    "documento": (
                        documento_problematico
                    ),
                }

            return {
                "resultado": "dialogo",
                "mensagem": mensagem,
            }


@app.post("/analisar-processo")
async def analisar_processo(
    dados: ProcessoRequest,
    request: Request,
) -> dict[str, Any]:
    link = str(dados.link_processo_url)

    try:
        async with async_playwright() as playwright:
            navegador = (
                await playwright.chromium.launch(
                    headless=True,
                )
            )

            contexto = (
                await navegador.new_context(
                    accept_downloads=True,
                    viewport={
                        "width": 1440,
                        "height": 1000,
                    },
                    user_agent=(
                        "Mozilla/5.0 "
                        "(Macintosh; Intel Mac OS X "
                        "10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/150.0.0.0 "
                        "Safari/537.36"
                    ),
                )
            )

            pagina = await contexto.new_page()

            fila_eventos: asyncio.Queue = (
                asyncio.Queue()
            )

            paginas_monitoradas: list[Page] = []
            alertas_javascript: list[str] = []

            registrar_contexto(
                contexto=contexto,
                pagina_principal=pagina,
                fila_eventos=fila_eventos,
                paginas_monitoradas=(
                    paginas_monitoradas
                ),
                alertas=alertas_javascript,
            )

            resposta = await pagina.goto(
                link,
                wait_until="domcontentloaded",
                timeout=TIMEOUT_NAVEGACAO_MS,
            )

            if resposta is None:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "O SEI não retornou uma "
                        "resposta válida."
                    ),
                )

            await pagina.wait_for_timeout(3000)

            texto_pagina = await pagina.locator(
                "body"
            ).inner_text()

            processo_encontrado = (
                "Acesso Externo com "
                "Acompanhamento Integral "
                "do Processo"
                in texto_pagina
            )

            if not processo_encontrado:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "A página foi aberta, mas "
                        "o processo público do SEI "
                        "não foi identificado."
                    ),
                )

            documentos = await extrair_documentos(
                pagina=pagina,
                link_processo=link,
            )

            documentos_por_numero = {
                documento["numero_documento"]:
                documento
                for documento in documentos
            }

            (
                quantidade_checkboxes,
                quantidade_inicial_selecionada,
            ) = await selecionar_todos_documentos(
                pagina
            )

            documentos_excluidos: list[
                dict[str, str]
            ] = []

            historico_tentativas: list[
                dict[str, Any]
            ] = []

            resultado_download: dict[str, Any] = {
                "download_realizado": False,
                "nome_arquivo": "",
                "caminho_arquivo": "",
                "tamanho_arquivo_bytes": 0,
                "download_url": "",
                "erro_download": "",
                "mensagem_download": (
                    "PDF ainda não gerado."
                ),
            }

            pagina_origem_download = ""
            motivo_interrupcao = ""

            for tentativa in range(
                1,
                MAX_TENTATIVAS_PDF + 1,
            ):
                quantidade_selecionada = (
                    await contar_documentos_selecionados(
                        pagina
                    )
                )

                resultado_tentativa = (
                    await tentar_gerar_pdf(
                        pagina=pagina,
                        fila_eventos=fila_eventos,
                    )
                )

                tipo_resultado = (
                    resultado_tentativa[
                        "resultado"
                    ]
                )

                registro_tentativa: dict[
                    str,
                    Any,
                ] = {
                    "tentativa": tentativa,
                    "documentos_selecionados": (
                        quantidade_selecionada
                    ),
                    "resultado": tipo_resultado,
                    "mensagem": (
                        resultado_tentativa.get(
                            "mensagem",
                            "",
                        )
                    ),
                }

                historico_tentativas.append(
                    registro_tentativa
                )

                if tipo_resultado == "download":
                    download = (
                        resultado_tentativa[
                            "download"
                        ]
                    )

                    pagina_download = (
                        resultado_tentativa[
                            "pagina"
                        ]
                    )

                    pagina_origem_download = (
                        pagina_download.url
                    )

                    resultado_download = (
                        await salvar_download(
                            download=download,
                            request=request,
                        )
                    )

                    break

                if (
                    tipo_resultado
                    == "documento_problematico"
                ):
                    documento_erro = (
                        resultado_tentativa[
                            "documento"
                        ]
                    )

                    numero_documento = (
                        documento_erro[
                            "numero_documento"
                        ]
                    )

                    numeros_ja_excluidos = {
                        item["numero_documento"]
                        for item in documentos_excluidos
                    }

                    if (
                        numero_documento
                        in numeros_ja_excluidos
                    ):
                        motivo_interrupcao = (
                            "O SEI repetiu o erro "
                            "para um documento que "
                            "já havia sido excluído."
                        )
                        break

                    desmarcado = (
                        await desmarcar_documento(
                            pagina=pagina,
                            numero_documento=(
                                numero_documento
                            ),
                        )
                    )

                    if not desmarcado:
                        motivo_interrupcao = (
                            "O SEI indicou um "
                            "documento problemático, "
                            "mas a API não conseguiu "
                            "desmarcá-lo."
                        )
                        break

                    dados_documento = (
                        documentos_por_numero.get(
                            numero_documento,
                            {},
                        )
                    )

                    documentos_excluidos.append(
                        {
                            "numero_documento": (
                                numero_documento
                            ),
                            "tipo_documento": (
                                dados_documento.get(
                                    "tipo_documento",
                                    documento_erro.get(
                                        "descricao_informada",
                                        "",
                                    ),
                                )
                            ),
                            "data_documento": (
                                dados_documento.get(
                                    "data_documento",
                                    "",
                                )
                            ),
                            "unidade": (
                                dados_documento.get(
                                    "unidade",
                                    "",
                                )
                            ),
                            "motivo": (
                                resultado_tentativa[
                                    "mensagem"
                                ]
                            ),
                        }
                    )

                    continue

                motivo_interrupcao = (
                    resultado_tentativa.get(
                        "mensagem",
                        "A geração foi interrompida.",
                    )
                )
                break

            quantidade_final_selecionada = (
                await contar_documentos_selecionados(
                    pagina
                )
            )

            download_realizado = (
                resultado_download[
                    "download_realizado"
                ]
            )

            pdf_parcial = (
                download_realizado
                and len(documentos_excluidos) > 0
            )

            if (
                not download_realizado
                and not motivo_interrupcao
            ):
                motivo_interrupcao = (
                    "O limite máximo de tentativas "
                    "foi atingido."
                )

            resultado = {
                "status": (
                    "pdf_disponivel_parcial"
                    if pdf_parcial
                    else (
                        "pdf_disponivel"
                        if download_realizado
                        else "pdf_nao_disponivel"
                    )
                ),
                "versao_api": "0.10.0",
                "http_status": resposta.status,
                "link_processo_url": link,
                "titulo_pagina": (
                    await pagina.title()
                ),
                "processo_encontrado": (
                    processo_encontrado
                ),
                "quantidade_documentos_total": (
                    len(documentos)
                ),
                "quantidade_checkboxes": (
                    quantidade_checkboxes
                ),
                "quantidade_inicial_selecionada": (
                    quantidade_inicial_selecionada
                ),
                "quantidade_documentos_incluidos": (
                    quantidade_final_selecionada
                ),
                "quantidade_documentos_excluidos": (
                    len(documentos_excluidos)
                ),
                "pdf_parcial": pdf_parcial,
                "download_realizado": (
                    download_realizado
                ),
                "nome_arquivo": (
                    resultado_download[
                        "nome_arquivo"
                    ]
                ),
                "caminho_arquivo": (
                    resultado_download[
                        "caminho_arquivo"
                    ]
                ),
                "tamanho_arquivo_bytes": (
                    resultado_download[
                        "tamanho_arquivo_bytes"
                    ]
                ),
                "download_url": (
                    resultado_download[
                        "download_url"
                    ]
                ),
                "mensagem_download": (
                    resultado_download[
                        "mensagem_download"
                    ]
                ),
                "erro_download": (
                    resultado_download[
                        "erro_download"
                    ]
                ),
                "pagina_origem_download": (
                    pagina_origem_download
                ),
                "max_tentativas_pdf": (
                    MAX_TENTATIVAS_PDF
                ),
                "quantidade_tentativas_realizadas": (
                    len(historico_tentativas)
                ),
                "motivo_interrupcao": (
                    motivo_interrupcao
                ),
                "alertas_javascript": (
                    alertas_javascript
                ),
                "documentos_excluidos_pdf": (
                    documentos_excluidos
                ),
                "historico_tentativas": (
                    historico_tentativas
                ),
                "documentos": documentos,
            }

            await contexto.close()
            await navegador.close()

            return resultado

    except HTTPException:
        raise

    except PlaywrightTimeoutError as erro:
        raise HTTPException(
            status_code=504,
            detail=(
                "Tempo excedido ao acessar "
                f"o SEI: {erro}"
            ),
        ) from erro

    except Exception as erro:
        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao acessar ou baixar "
                "o processo do SEI: "
                f"{type(erro).__name__}: {erro}"
            ),
        ) from erro