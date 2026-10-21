from dotenv import load_dotenv

# Load .env before importing modules that read settings at import time
load_dotenv(override=True)

import gradio as gr
from agent_manager import AgentManager
from styles import CSS, JS, EXAMPLES, HEADER_HTML

FILE_TYPES = [".csv", ".xlsx", ".xls", ".pdf", ".docx", ".txt", ".md"]


async def run(query: str, files: list[str] | None):
    if not query.strip():
        yield "Please describe what you want analysed.", "", None, [], gr.update(visible=False)
        return
    try:
        async for report_md, summary_md, pdf_path, chart_paths in AgentManager().run(query, files):
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

    gr.HTML('<div class="dr-examples-label">Try one</div>')
    gr.Examples(examples=EXAMPLES, inputs=query_textbox, elem_id="dr-examples")

    with gr.Column(visible=False) as results:
        summary = gr.Markdown(elem_id="dr-summary")
        pdf_file = gr.File(label="PDF report", interactive=False)
        charts = gr.Gallery(label="Charts", columns=2, height="auto", object_fit="contain")
    report = gr.Markdown(elem_id="dr-report")

    inputs = [query_textbox, files]
    outputs = [report, summary, pdf_file, charts, results]
    run_button.click(run, inputs=inputs, outputs=outputs)
    query_textbox.submit(run, inputs=inputs, outputs=outputs)


if __name__ == "__main__":
    ui.launch(css=CSS, js=JS, theme=gr.themes.Base())
