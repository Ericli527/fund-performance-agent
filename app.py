from dotenv import load_dotenv

# Load .env before importing modules that read settings at import time
load_dotenv(override=True)

import gradio as gr
from agent_manager import AgentManager
from styles import CSS, JS, EXAMPLES, HEADER_HTML


async def run(query: str):
    async for status_update in AgentManager().run(query):
        yield status_update


with gr.Blocks(title="My Agent") as ui:
    gr.HTML(HEADER_HTML)

    with gr.Row(elem_classes="dr-query-row"):
        query_textbox = gr.Textbox(
            placeholder="Describe your task...",
            show_label=False,
            container=False,
            autofocus=True,
            elem_id="dr-query",
            scale=5,
        )
        run_button = gr.Button("Run", variant="primary", elem_id="dr-run", scale=1)

    gr.HTML('<div class="dr-examples-label">Try one</div>')
    gr.Examples(examples=EXAMPLES, inputs=query_textbox, elem_id="dr-examples")

    output = gr.Markdown(elem_id="dr-report")

    run_button.click(run, inputs=query_textbox, outputs=output)
    query_textbox.submit(run, inputs=query_textbox, outputs=output)


if __name__ == "__main__":
    ui.launch(css=CSS, js=JS, theme=gr.themes.Base())
