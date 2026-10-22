from dotenv import load_dotenv

# Load .env before importing modules that read settings at import time
load_dotenv(override=True)

import os
import gradio as gr
from agent_manager import AgentManager
from styles import CSS, JS, EXAMPLES, HEADER_HTML

FILE_TYPES = [".csv", ".xlsx", ".xls", ".pdf", ".docx", ".txt", ".md"]


async def run(query: str, files: list[str] | None, fund_id: str, benchmark_id: str):
    if not query.strip():
        yield "Please describe what you want analysed.", "", None, [], gr.update(visible=False)
        return
    try:
        async for report_md, summary_md, pdf_path, chart_paths in AgentManager().run(query, files, fund_id, benchmark_id):
            # Results stay hidden until the PDF is ready
            yield report_md, summary_md, pdf_path, chart_paths, gr.update(visible=pdf_path is not None)
    except Exception as e:
        yield f"**Something went wrong:** {e}", "", None, [], gr.update(visible=False)


with gr.Blocks(title="Fund Report Agent") as ui:
    gr.HTML(HEADER_HTML)

    with gr.Row(elem_classes="dr-query-row"):
        query_textbox = gr.Textbox(
            placeholder="e.g. Analyse the fund's performance and attribution vs its benchmark",
            show_label=False,
            container=False,
            autofocus=True,
            elem_id="dr-query",
            scale=5,
        )
        run_button = gr.Button("Analyse", variant="primary", elem_id="dr-run", scale=1)

    files = gr.File(label="Fund data and documents (CSV, Excel, PDF, Word, text)",
                    file_count="multiple", file_types=FILE_TYPES, type="filepath", elem_id="dr-files")

    with gr.Row():
        fund_id = gr.Textbox(label="Fund ISIN or ticker (optional)", placeholder="e.g. GB00B5L8VH15",
                             info="Downloads prices from EODHD instead of uploading a NAV file")
        benchmark_id = gr.Textbox(label="Benchmark ticker", placeholder="e.g. IUKD.LSE",
                                  info="An index fund or ETF to compare against")

    gr.HTML('<div class="dr-examples-label">Try one</div>')
    gr.Examples(examples=EXAMPLES, inputs=query_textbox, elem_id="dr-examples")

    with gr.Column(visible=False) as results:
        summary = gr.Markdown(elem_id="dr-summary")
        pdf_file = gr.File(label="PDF report", interactive=False)
        charts = gr.Gallery(label="Charts", columns=3, height="auto", object_fit="contain")
    report = gr.Markdown(elem_id="dr-report")

    inputs = [query_textbox, files, fund_id, benchmark_id]
    outputs = [report, summary, pdf_file, charts, results]
    run_button.click(run, inputs=inputs, outputs=outputs)
    query_textbox.submit(run, inputs=inputs, outputs=outputs)


def login() -> tuple[str, str] | None:
    """ Optional password protection, so a public demo can't spend your API credit """
    username, password = os.getenv("APP_USERNAME"), os.getenv("APP_PASSWORD")
    return (username, password) if username and password else None


if __name__ == "__main__":
    # Hosts such as Render set PORT and need the app to listen on all interfaces
    on_host = "PORT" in os.environ
    ui.queue(default_concurrency_limit=int(os.getenv("MAX_CONCURRENT_RUNS", 2)))
    ui.launch(
        css=CSS, js=JS, theme=gr.themes.Base(),
        server_name="0.0.0.0" if on_host else None,
        server_port=int(os.environ["PORT"]) if on_host else None,
        auth=login(),
    )
