import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from pydantic import BaseModel, HttpUrl

app = FastAPI(
    title="Fiscaliza Dados Públicos API",
    version="0.7.0",
    description=(
        "Prova de conceito para acessar processos públicos do SEI, "
        "gerar o PDF consolidado e disponibilizar o arquivo pela API."
    ),
)

PASTA_DOWNLOADS = Path("downloads").resolve()
PASTA_DOWNLOADS.mkdir(parents=True, exist_ok=True)


class ProcessoRequest(BaseModel):
    link_processo_url: HttpUrl


@app.get("/")
def raiz() -> dict[str, str]:
    return {
        "status": "online",
        "mensagem": "Fiscaliza Dados Públicos API em funcionamento.",
    }


@app.get(
    "/downloads/{nome_arquivo}",
    name="baixar_arquivo",
)
def baixar_arquivo(nome_arquivo: str) -> FileResponse:
    nome_seguro = Path(nome_arquivo).name
    caminho_arquivo = (PASTA_DOWNLOADS / nome_seguro).resolve()

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
            detail="O caminho informado não corresponde a um arquivo.",
        )

    return FileResponse(
        path=str(caminho_arquivo),
        media_type="application/pdf",
        filename=caminho_arquivo.name,
    )


@app.post("/analisar-processo")
async def analisar_processo(
    dados: ProcessoRequest,
    request: Request,
) -> dict[str, Any]:
    link = str(dados.link_processo_url)

    try:
        async with async_playwright() as playwright:
            navegador = await playwright.chromium.launch(
                headless=True,
            )

            contexto = await navegador.new_context(
                accept_downloads=True,
                viewport={
                    "width": 1440,
                    "height": 1000,
                },
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/150.0.0.0 Safari/537.36"
                ),
            )

            pagina = await contexto.new_page()

            resposta = await pagina.goto(
                link,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if resposta is None:
                raise HTTPException(
                    status_code=502,
                    detail="O SEI não retornou uma resposta válida.",
                )

            await pagina.wait_for_timeout(3000)

            texto_pagina = await pagina.locator("body").inner_text()

            processo_encontrado = (
                "Acesso Externo com Acompanhamento Integral do Processo"
                in texto_pagina
            )

            if not processo_encontrado:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "A página foi aberta, mas o processo público "
                        "do SEI não foi identificado."
                    ),
                )

            documentos: list[dict[str, str]] = []

            todos_links = pagina.locator("a")
            quantidade_total_links = await todos_links.count()

            for indice in range(quantidade_total_links):
                elemento_link = todos_links.nth(indice)

                texto_link = (
                    await elemento_link.inner_text()
                ).strip()

                if not re.fullmatch(r"\d{7,}", texto_link):
                    continue

                href = await elemento_link.get_attribute("href")

                linha = elemento_link.locator(
                    "xpath=ancestor::tr[1]"
                )

                if await linha.count() == 0:
                    continue

                celulas = linha.locator("td")
                quantidade_celulas = await celulas.count()

                textos_celulas: list[str] = []

                for indice_celula in range(quantidade_celulas):
                    texto_celula = (
                        await celulas
                        .nth(indice_celula)
                        .inner_text()
                    ).strip()

                    textos_celulas.append(texto_celula)

                tipo_documento = (
                    textos_celulas[2]
                    if quantidade_celulas > 2
                    else ""
                )

                data_documento = (
                    textos_celulas[3]
                    if quantidade_celulas > 3
                    else ""
                )

                unidade = (
                    textos_celulas[4]
                    if quantidade_celulas > 4
                    else ""
                )

                url_documento = (
                    urljoin(link, href)
                    if href
                    else ""
                )

                documentos.append(
                    {
                        "numero_documento": texto_link,
                        "tipo_documento": tipo_documento,
                        "data_documento": data_documento,
                        "unidade": unidade,
                        "url_documento": url_documento,
                    }
                )

            checkboxes = pagina.locator(
                "input[type='checkbox']"
            )

            quantidade_checkboxes = await checkboxes.count()
            quantidade_selecionados = 0

            for indice in range(quantidade_checkboxes):
                checkbox = checkboxes.nth(indice)

                if not await checkbox.is_visible():
                    continue

                if not await checkbox.is_enabled():
                    continue

                if not await checkbox.is_checked():
                    await checkbox.check()

                if await checkbox.is_checked():
                    quantidade_selecionados += 1

            botao_pdf = pagina.locator(
                "button[name='btnGerarPdf']"
            )

            if await botao_pdf.count() == 0:
                raise HTTPException(
                    status_code=422,
                    detail="O botão Gerar PDF não foi localizado.",
                )

            download_realizado = False
            nome_arquivo = ""
            caminho_arquivo = ""
            tamanho_arquivo_bytes = 0
            download_url = ""
            mensagem_download = ""

            try:
                async with pagina.expect_download(
                    timeout=120000,
                ) as download_info:
                    await botao_pdf.click()

                download = await download_info.value

                nome_original = (
                    download.suggested_filename
                    or "processo_sei.pdf"
                )

                nome_arquivo = Path(nome_original).name

                if not nome_arquivo.lower().endswith(".pdf"):
                    nome_arquivo = f"{nome_arquivo}.pdf"

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

                download_realizado = caminho_destino.exists()

                if download_realizado:
                    caminho_arquivo = str(caminho_destino)
                    tamanho_arquivo_bytes = (
                        caminho_destino.stat().st_size
                    )

                    download_url = str(
                        request.url_for(
                            "baixar_arquivo",
                            nome_arquivo=nome_arquivo,
                        )
                    )

                    mensagem_download = (
                        "PDF consolidado gerado e disponibilizado "
                        "pela API."
                    )
                else:
                    mensagem_download = (
                        "O SEI iniciou o download, mas o arquivo "
                        "não foi localizado após o salvamento."
                    )

            except PlaywrightTimeoutError:
                mensagem_download = (
                    "O botão Gerar PDF não iniciou um download "
                    "dentro do tempo esperado."
                )

            resultado = {
                "status": (
                    "pdf_disponivel"
                    if download_realizado
                    else "pdf_nao_disponivel"
                ),
                "http_status": resposta.status,
                "link_processo_url": link,
                "titulo_pagina": await pagina.title(),
                "processo_encontrado": processo_encontrado,
                "quantidade_documentos": len(documentos),
                "quantidade_checkboxes": quantidade_checkboxes,
                "quantidade_documentos_selecionados": (
                    quantidade_selecionados
                ),
                "download_realizado": download_realizado,
                "nome_arquivo": nome_arquivo,
                "caminho_arquivo": caminho_arquivo,
                "tamanho_arquivo_bytes": tamanho_arquivo_bytes,
                "download_url": download_url,
                "mensagem_download": mensagem_download,
                "documentos": documentos,
            }

            await contexto.close()
            await navegador.close()

            return resultado

    except HTTPException:
        raise

    except Exception as erro:
        raise HTTPException(
            status_code=500,
            detail=(
                "Erro ao acessar ou baixar o processo do SEI: "
                f"{type(erro).__name__}: {erro}"
            ),
        ) from erro