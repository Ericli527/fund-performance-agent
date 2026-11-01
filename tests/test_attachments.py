"""Attachment classification and mapping do not invoke AI or guess ambiguous roles."""
from pathlib import Path
from docx import Document
from fund_performance.attachments import (BENCHMARK, CONFIRM, DEMO_INPUT, FACTSHEET, KID, PEER, PRICE, SUPPORTING,
                                          add_files, apply_roles, classify, engine_inputs, remove_attachment, rows, select_type,
                                          supporting_inputs, validate)

ROOT = Path(__file__).resolve().parents[1]


def test_price_is_read_and_ambiguous_factsheet_requires_confirmation(tmp_path):
    price = ROOT / 'demo/sample_index_fund/prices.csv'
    assert classify(str(price))[0] == PRICE
    doc = Document()
    doc.add_paragraph('Fund factsheet: Example fund')
    path = tmp_path / 'document.docx'
    doc.save(path)
    assert classify(str(path))[0] == CONFIRM
    kid = Document()
    kid.add_paragraph('Key Investor Information')
    kidpath = tmp_path / 'kid.docx'
    kid.save(kidpath)
    assert classify(str(kidpath))[0] == KID
    mixed = Document()
    mixed.add_paragraph('Fund factsheet. See the Key Investor Information document.')
    mixedpath = tmp_path / 'mixed.docx'
    mixed.save(mixedpath)
    assert classify(str(mixedpath))[0] == CONFIRM


def test_user_roles_removal_and_multiple_peers_map_exact_files(tmp_path):
    price = str(ROOT / 'demo/sample_index_fund/prices.csv')
    docs = []
    for name in ('fund', 'peer1', 'peer2'):
        p = tmp_path / f'{name}.docx'
        doc = Document()
        doc.add_paragraph('Fund factsheet and investment objectives')
        doc.save(p)
        docs.append(str(p))
    entries = add_files([], [price, *docs])
    table = rows(entries)
    for row, role in zip(table, [PRICE, FACTSHEET, PEER, PEER]):
        row[2] = role
    selected, error = apply_roles(entries, table)
    assert not error and not validate('Assess the fund', selected)
    assert engine_inputs(selected) == (price, docs[0], None, docs[1:], [])
    selected, error = apply_roles(entries, table[:-1])
    assert not error and engine_inputs(selected)[3] == [docs[1]]
    assert validate('', selected) == ['Enter a review question.']


def test_monthly_factsheet_reference_to_kid_is_not_classified_as_kid(tmp_path, monkeypatch):
    from fund_performance import attachments
    path = tmp_path / 'Monthly FactSheet.pdf'
    path.write_bytes(b'dummy')
    monkeypatch.setattr(attachments, 'read_document', lambda _: 'Monthly Fund Fact Sheet. See the KID for details.')
    assert classify(str(path))[0] == FACTSHEET
    monkeypatch.setattr(attachments, 'read_document', lambda _: 'Key Investor Information Document for the fund')
    assert classify(str(path))[0] == CONFIRM


def test_type_override_refreshes_validation_and_supports_multiple_documents(tmp_path, monkeypatch):
    from fund_performance import web
    monkeypatch.setattr(web, 'live_demo_allowed', lambda: True)
    files = []
    for name in ('fund', 'peer1', 'peer2', 'extra1', 'extra2'):
        path = tmp_path / f'{name}.docx'
        doc = Document()
        doc.add_paragraph('Fund factsheet and investment objectives')
        doc.save(path)
        files.append(str(path))
    price = str(ROOT / 'demo/sample_index_fund/prices.csv')
    entries = add_files([], [price, *files])
    table = rows(entries)
    status = {fn.name: fn.fn for fn in web.build_ui().fns.values()}['update_status']
    assert status('Review', entries, table, None)[1]['interactive'] is False
    for attachment_id, role in zip([entry['id'] for entry in entries[1:]],
                                   (FACTSHEET, PEER, PEER, SUPPORTING, SUPPORTING)):
        entries, table = select_type(entries, table, attachment_id, role)
    assert status('Review', entries, table, None)[1]['interactive'] is True
    assert engine_inputs(entries)[3] == files[1:3]
    assert supporting_inputs(entries) == files[3:]
    entries, table = select_type(entries, table, entries[1]['id'], KID)
    message, button = status('Review', entries, table, None)
    assert not button['interactive'] and 'main fund factsheet' in message


def test_dynamic_type_controls_create_private_dropdown_events(tmp_path):
    import gradio as gr
    from gradio.context import LocalContext
    from fund_performance.web import build_ui
    path = tmp_path / 'fund.docx'
    doc = Document()
    doc.add_paragraph('Fund factsheet and investment objectives')
    doc.save(path)
    entries = add_files([], [str(path)])
    ui = build_ui()
    renderable = ui.default_config.renderables[0]
    token = LocalContext.blocks_config.set(ui.default_config)
    try:
        renderable.apply(entries, rows(entries))
    finally:
        LocalContext.blocks_config.reset(token)
    controls = [b for b in ui.blocks.values() if isinstance(b, gr.Dropdown) and b.label == path.name]
    assert len(controls) == 1 and SUPPORTING in [value for _, value in controls[0].choices]
    assert FACTSHEET in [value for _, value in controls[0].choices]
    assert all(fn.api_visibility == 'private' for fn in ui.fns.values())
    render_trigger = next(fn for fn in ui.fns.values() if fn.name == 'apply')
    assert render_trigger.concurrency_limit == 1 and render_trigger.concurrency_id == 'attachment-render'
    removals = [fn for fn in ui.fns.values() if fn.name == 'remove_file']
    assert removals and removals[0].concurrency_id == 'attachment-mutations'
    state, table, message = removals[0].fn(entries, rows(entries))
    assert state == [] and table == [] and message == 'Attachment removed.' and path.exists()


def test_selector_render_errors_are_logged_and_shown(monkeypatch, capsys):
    import gradio as gr
    from gradio.context import LocalContext
    from fund_performance import attachments, web
    def fail(*args):
        raise RuntimeError('synthetic selector error')
    monkeypatch.setattr(attachments, 'apply_roles', fail)
    ui = web.build_ui()
    token = LocalContext.blocks_config.set(ui.default_config)
    try:
        ui.default_config.renderables[0].apply([], [])
    finally:
        LocalContext.blocks_config.reset(token)
    assert 'synthetic selector error' in capsys.readouterr().err
    assert any(isinstance(block, gr.Markdown) and 'could not be displayed' in str(block.value)
               for block in ui.blocks.values())


def test_upload_processing_feedback_precedes_slow_classification(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fund_performance import attachments, web
    started, finish = Event(), Event()
    original = attachments.add_files
    def slow(existing, paths):
        started.set()
        assert finish.wait(5)
        return original(existing, paths)
    monkeypatch.setattr(attachments, 'add_files', slow)
    callback = {fn.name: fn.fn for fn in web.build_ui().fns.values()}['upload_files']
    path = tmp_path / 'fund.docx'
    doc = Document()
    doc.add_paragraph('Fund factsheet')
    doc.save(path)
    stream = callback([str(path)], [], [])
    initial = next(stream)
    assert initial[3]['interactive'] is False and initial[-1] is True
    assert 'Processing' in initial[8] and not started.is_set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(next, stream)
        assert started.wait(5) and not pending.done()
        finish.set()
        final = pending.result(timeout=5)
    assert len(final[0]) == 1 and final[1]['value'][0][1] == 'fund.docx'
    assert final[3]['interactive'] is True and final[-1] is False


def test_sequential_overlapping_uploads_do_not_discard_newer_files(tmp_path):
    from fund_performance.web import build_ui
    callback = {fn.name: fn.fn for fn in build_ui().fns.values()}['upload_files']
    paths = []
    for name in ('one.docx', 'two.docx', 'three.docx'):
        path = tmp_path / name
        doc = Document()
        doc.add_paragraph('Fund factsheet')
        doc.save(path)
        paths.append(str(path))
    initial, result = list(callback(paths[:2], [], []))
    assert len(result[0]) == 2
    # A queued second request can carry an old table even when the server state has advanced.
    _, second = list(callback(paths[2:], result[0], []))
    assert [Path(e['path']).name for e in second[0]] == ['one.docx', 'two.docx', 'three.docx']
    assert len({entry['id'] for entry in second[0]}) == 3


def test_stale_table_cannot_restore_a_removed_attachment(tmp_path):
    paths = []
    for name in ('one.docx', 'two.docx'):
        path = tmp_path / name
        doc = Document()
        doc.add_paragraph('Fund factsheet')
        doc.save(path)
        paths.append(str(path))
    state = add_files([], paths)
    stale = rows(state)
    current, _ = remove_attachment(state, stale, state[0]['id'])
    result, table = select_type(current, stale, current[0]['id'], FACTSHEET)
    assert result == current and table == rows(current) and len(table) == 1


def test_remove_and_clear_preserve_other_files_and_update_validation(tmp_path, monkeypatch):
    from fund_performance import web
    monkeypatch.setattr(web, 'live_demo_allowed', lambda: True)
    price = str(ROOT / 'demo/sample_index_fund/prices.csv')
    doc_path = tmp_path / 'fund.docx'
    doc = Document()
    doc.add_paragraph('Fund factsheet')
    doc.save(doc_path)
    state = add_files([], [price, str(doc_path)])
    table = rows(state)
    state, table = select_type(state, table, state[1]['id'], FACTSHEET)
    callbacks = {fn.name: fn.fn for fn in web.build_ui().fns.values()}
    assert callbacks['update_status']('Review', state, table, None)[1]['interactive']
    state, table = remove_attachment(state, table, state[1]['id'])
    assert len(state) == 1 and doc_path.exists()
    assert not callbacks['update_status']('Review', state, table, None)[1]['interactive']
    cleared = callbacks['clear_files']()
    assert cleared[:3] == ([], [], None) and cleared[4]['value'] is None
    assert callbacks['choose_case']('sample_index_fund')[0]


def test_failed_file_does_not_lose_successful_uploads(tmp_path, monkeypatch, caplog):
    from fund_performance import attachments, web
    original = attachments.classify
    def sometimes_fails(path, **kwargs):
        if Path(path).name == 'bad.docx':
            raise RuntimeError('synthetic inspection failure')
        return original(path, **kwargs)
    monkeypatch.setattr(attachments, 'classify', sometimes_fails)
    good, bad = tmp_path / 'good.docx', tmp_path / 'bad.docx'
    doc = Document()
    doc.add_paragraph('Fund factsheet')
    doc.save(good)
    bad.write_bytes(b'bad')
    callback = {fn.name: fn.fn for fn in web.build_ui().fns.values()}['upload_files']
    _, final = list(callback([str(good), str(bad)], [], []))
    assert len(final[0]) == 2 and final[0][1]['role'] == CONFIRM
    assert 'could not be read' in final[8] and 'synthetic inspection failure' in caplog.text
    state, table = select_type(final[0], final[1]['value'], final[0][1]['id'], FACTSHEET)
    assert any('could not be processed' in issue for issue in validate('Review', state))


def test_unexpected_upload_error_is_logged_and_existing_state_is_kept(tmp_path, monkeypatch, capsys):
    from fund_performance import attachments, web
    path = tmp_path / 'existing.docx'
    doc = Document()
    doc.add_paragraph('Fund factsheet')
    doc.save(path)
    state = add_files([], [str(path)])
    def fail(*args):
        raise RuntimeError('synthetic upload failure')
    monkeypatch.setattr(attachments, 'add_files', fail)
    callback = {fn.name: fn.fn for fn in web.build_ui().fns.values()}['upload_files']
    _, final = list(callback(['new.docx'], state, rows(state)))
    assert final[0] == state and final[1]['value'] == rows(state)
    assert 'Existing attachments were kept' in final[8] and final[-1] is False
    assert 'synthetic upload failure' in capsys.readouterr().err


def test_validation_reuses_inspection_until_the_file_changes(tmp_path, monkeypatch):
    from fund_performance import attachments
    path = tmp_path / 'fund.docx'
    doc = Document()
    doc.add_paragraph('Fund factsheet')
    doc.save(path)
    original = attachments.read_document
    calls = []
    def counted(p):
        calls.append(p)
        return original(p)
    monkeypatch.setattr(attachments, 'read_document', counted)
    entries = add_files([], [str(path)])
    entries[0]['role'] = FACTSHEET
    validate('Review', entries)
    validate('Review again', entries)
    assert len(calls) == 1
    doc.add_paragraph('Updated')
    doc.save(path)
    validate('Review', entries)
    assert len(calls) == 2


def test_multiple_uploads_stream_processing_and_table_over_http(tmp_path):
    import json
    import socket
    import requests
    from fund_performance.web import build_ui
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    ui = build_ui()
    ui.queue()
    ui.launch(server_name='127.0.0.1', server_port=port, prevent_thread_lock=True, quiet=True)
    try:
        paths = []
        for name in ('first.docx', 'second.docx'):
            path = tmp_path / name
            doc = Document()
            doc.add_paragraph('Fund factsheet')
            doc.save(path)
            paths.append(path)
        session = requests.Session()
        base = f'http://127.0.0.1:{port}'
        files = [('files', (path.name, path.read_bytes(), 'application/octet-stream')) for path in paths]
        uploaded = session.post(base + '/gradio_api/upload', files=files, timeout=20)
        uploaded.raise_for_status()
        payload = [{'path': path, 'orig_name': Path(path).name, 'meta': {'_type': 'gradio.FileData'}}
                   for path in uploaded.json()]
        fn = next(fn for fn in ui.fns.values() if fn.name == 'upload_files')
        table = {'headers': ['ID', 'File', 'Type', 'Notes', 'Document date'], 'data': []}
        joined = session.post(base + '/gradio_api/queue/join', json={'data': [payload, None, table],
            'event_data': None, 'fn_index': fn._id, 'session_hash': 'upload-test'}, timeout=20)
        joined.raise_for_status()
        event = joined.json()['event_id']
        messages = []
        with session.get(base + '/gradio_api/queue/data', params={'session_hash': 'upload-test'},
                         stream=True, timeout=30) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith('data: '):
                    continue
                message = json.loads(line[6:])
                if message.get('event_id') == event:
                    messages.append(message)
                    if message.get('msg') == 'process_completed':
                        break
        first = next(m for m in messages if m.get('msg') == 'process_generating')
        last = messages[-1]
        assert 'Processing' in first['output']['data'][8]
        assert first['output']['data'][3]['interactive'] is False
        assert last['success'] and last['output']['data'][3]['interactive'] is True
        table_rows = last['output']['data'][1]['value']['data']
        assert [row[1] for row in table_rows] == ['first.docx', 'second.docx']
    finally:
        ui.close()


def test_overlapping_http_uploads_keep_both_files(tmp_path, monkeypatch):
    import json
    import socket
    import threading
    import requests
    from fund_performance import attachments
    from fund_performance.web import build_ui
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    ui = build_ui()
    ui.queue()
    ui.launch(server_name='127.0.0.1', server_port=port, prevent_thread_lock=True, quiet=True)
    started, release = threading.Event(), threading.Event()
    original = attachments.classify
    def slow(path, **kwargs):
        if Path(path).name == 'first.docx':
            started.set()
            assert release.wait(10)
        return original(path, **kwargs)
    monkeypatch.setattr(attachments, 'classify', slow)
    try:
        paths = []
        for name in ('first.docx', 'second.docx'):
            path = tmp_path / name
            doc = Document()
            doc.add_paragraph('Fund factsheet')
            doc.save(path)
            paths.append(path)
        base = f'http://127.0.0.1:{port}'
        session = requests.Session()
        files = [('files', (path.name, path.read_bytes(), 'application/octet-stream')) for path in paths]
        uploaded = session.post(base + '/gradio_api/upload', files=files, timeout=20)
        uploaded.raise_for_status()
        cached = uploaded.json()
        fn = next(fn for fn in ui.fns.values() if fn.name == 'upload_files')
        table = {'headers': ['ID', 'File', 'Type', 'Notes', 'Document date'], 'data': []}
        def join(path):
            file_data = {'path': path, 'orig_name': Path(path).name, 'meta': {'_type': 'gradio.FileData'}}
            response = session.post(base + '/gradio_api/queue/join', json={'data': [[file_data], None, table],
                'event_data': None, 'fn_index': fn._id, 'session_hash': 'overlapping-upload-test'}, timeout=20)
            response.raise_for_status()
            return response.json()['event_id']
        messages = []
        def listen():
            with requests.get(base + '/gradio_api/queue/data', params={'session_hash': 'overlapping-upload-test'},
                              stream=True, timeout=30) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if line and line.startswith('data: '):
                        messages.append(json.loads(line[6:]))
                        if sum(item.get('msg') == 'process_completed' for item in messages) >= 2:
                            break
        first = join(cached[0])
        listener = threading.Thread(target=listen, daemon=True)
        listener.start()
        assert started.wait(10)
        second = join(cached[1])
        release.set()
        listener.join(30)
        assert not listener.is_alive()
        results = {item['event_id']: item for item in messages if item.get('msg') == 'process_completed'}
        assert results[first]['success'] and results[second]['success']
        final = results[second]['output']['data'][1]['value']['data']
        assert [row[1] for row in final] == ['first.docx', 'second.docx']
    finally:
        release.set()
        ui.close()


def test_unreadable_and_unsupported_files_are_blocked(tmp_path):
    bad = tmp_path / 'bad.pdf'
    bad.write_text('not a pdf')
    entries = add_files([], [str(bad)])
    assert entries[0]['role'] == CONFIRM
    rows_in = rows(entries)
    rows_in[0][2] = FACTSHEET
    selected, _ = apply_roles(entries, rows_in)
    assert any('could not be read' in issue for issue in validate('question', selected))
    rows_in[0][2] = BENCHMARK
    selected, _ = apply_roles(entries, rows_in)
    assert any('could not be read' in issue for issue in validate('question', selected))
    rows_in[0][2] = DEMO_INPUT
    assert apply_roles(entries, rows_in)[1]
    assert classify(str(tmp_path / 'unknown.txt'))[0] == CONFIRM
    benchmark = tmp_path / 'index.csv'
    benchmark.write_text('date,index_level\n2025-01-31,100\n2025-02-28,101\n')
    assert classify(str(benchmark))[0] == BENCHMARK


def test_synthetic_demo_callback_maps_prevalidated_inputs_and_rejects_edits():
    from fund_performance.web import build_ui
    ui = build_ui()
    callbacks = {fn.name: fn.fn for fn in ui.fns.values()}
    state, table, demo_id, mode, status = callbacks['choose_case']('sample_index_fund')
    assert demo_id == 'sample_index_fund' and mode == 'quick'
    message, button = callbacks['update_status']('What happened?', state, table, demo_id)
    assert button['interactive'] is True
    table = table[:-1]
    message, button = callbacks['update_status']('What happened?', state, table, demo_id)
    assert button['interactive'] is False and 'reload' in message


def test_unavailable_cases_never_substitute_synthetic_data(tmp_path, monkeypatch):
    from fund_performance import web
    monkeypatch.setenv('FUND_DEMO_DATA', str(tmp_path / 'absent'))
    callbacks = {fn.name: fn.fn for fn in web.build_ui().fns.values()}
    for demo_id in ('fidelity_us', 'vanguard_global'):
        state, table, chosen, mode, status = callbacks['choose_case'](demo_id)
        assert state == [] and table == [] and chosen is None and 'unavailable' in status


def test_synthetic_json_cannot_leak_into_a_custom_upload():
    from fund_performance.web import build_ui
    callbacks = {fn.name: fn.fn for fn in build_ui().fns.values()}
    state, table, demo_id, mode, _ = callbacks['choose_case']('sample_index_fund')
    message, button = callbacks['update_status']('Question?', state, table, None)
    assert button['interactive'] is False and 'only be used with the synthetic demo' in message


def test_question_cards_and_responsive_layout():
    from fund_performance.web import CSS, REVIEW_TYPES, build_ui
    assert list(REVIEW_TYPES) == ['overall', 'performance', 'fees_value', 'custom']
    assert 'repeat(4, minmax(0, 1fr))' in CSS
    assert '@media (max-width: 760px)' in CSS and 'grid-template-columns: 1fr' in CSS
    ui = build_ui()
    assert any(getattr(c, 'value', None) == 'overall' for c in ui.blocks.values())


def test_page_passes_edited_question_and_demo_inputs_to_existing_workflow(monkeypatch):
    import asyncio
    from fund_performance import web
    callbacks = {fn.name: fn.fn for fn in web.build_ui().fns.values()}
    state, table, demo_id, mode, _ = callbacks['choose_case']('sample_index_fund')
    seen = {}

    async def fake_review(question, price, factsheet, kid, peers, jsons, offline, limits, on_step):
        seen.update(question=question, price=price, jsons=jsons, offline=offline)
        for stage in range(1, 6):
            on_step(f'✓ Step {stage} of 5 · Stage {stage} · done')
        return web.Outcome('finished')

    monkeypatch.setattr(web, 'start_review', fake_review)
    async def collect():
        return [v async for v in callbacks['on_run']('My edited question?', state, table, demo_id, mode)]
    events = asyncio.run(collect())
    assert seen['question'] == 'My edited question?' and seen['offline'] is True
    assert len(seen['jsons']) == 3 and seen['price'].endswith('prices.csv')
    assert all(f'Step {n} of 5' in events[-1][0] for n in range(1, 6))


def test_dashboard_fallback_answer_and_research_sources_are_visible():
    from test_dashboard import data
    from fund_performance.dashboard import dashboard_html
    d = data()
    d['sources'] = [{'number': 1, 'query': 'Benchmark research', 'date': '2026-09-01', 'url': 'https://example.org'}]
    html = dashboard_html(d, 'analyst')
    assert 'Answer</p>' in html and 'The four ratings' in html
    assert 'Research sources' in html and '2026-09-01' in html


def test_page_requires_confirmed_identity_and_per_document_dates(tmp_path, monkeypatch):
    from fund_performance import web
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    monkeypatch.setenv('AI_RUNS_ENABLED', 'true')
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv(web.OFFLINE_ENV, raising=False)
    from fund_performance.io import read_prices
    original = read_prices(ROOT / 'demo/sample_index_fund/prices.csv').prices
    price_file = tmp_path / 'prices.csv'
    original[['date', 'nav']].to_csv(price_file, index=False)
    price = str(price_file)
    doc = Document()
    doc.add_paragraph('Sample World benchmark evidence')
    docpath = tmp_path / 'benchmark.docx'
    doc.save(docpath)
    factsheet = tmp_path / 'fund.docx'
    doc.save(factsheet)
    series = tmp_path / 'benchmark.csv'
    original[['date', 'index_level']].to_csv(series, index=False)
    entries = add_files([], [price, str(factsheet), str(series), str(docpath)])
    table = rows(entries)
    for row, role in zip(table, [PRICE, FACTSHEET, BENCHMARK, BENCHMARK]):
        row[2] = role
    callbacks = {fn.name: fn.fn for fn in web.build_ui().fns.values()}
    message, button = callbacks['update_status']('Question?', entries, table, None)
    assert not button['interactive'] and 'name' in message and 'document date' in message
    table[-1][4] = '2026-09-01'
    message, button = callbacks['update_status']('Question?', entries, table, None, 'Sample World Index', 'GBP', True, 'market_close')
    assert button['interactive']


def test_page_passes_confirmed_benchmark_and_documents_to_review(tmp_path, monkeypatch):
    import asyncio
    from fund_performance import web
    from fund_performance.io import read_prices
    original = read_prices(ROOT / 'demo/sample_index_fund/prices.csv').prices
    price, series = tmp_path / 'prices.csv', tmp_path / 'index.csv'
    original[['date', 'nav']].to_csv(price, index=False)
    original[['date', 'index_level']].to_csv(series, index=False)
    factsheet, benchmark_doc = tmp_path / 'fund.docx', tmp_path / 'benchmark.docx'
    for path in (factsheet, benchmark_doc):
        doc = Document()
        doc.add_paragraph('Sample World Index factsheet')
        doc.save(path)
    entries = add_files([], [str(price), str(factsheet), str(series), str(benchmark_doc)])
    table = rows(entries)
    for row, role in zip(table, [PRICE, FACTSHEET, BENCHMARK, BENCHMARK]):
        row[2] = role
    table[-1][4] = '2026-09-01'
    callbacks = {fn.name: fn.fn for fn in web.build_ui().fns.values()}
    captured = {}

    async def fake_review(*args, benchmark_inputs=None):
        captured.update(benchmark_inputs)
        return web.Outcome('done')

    monkeypatch.setattr(web, 'start_review', fake_review)
    async def collect():
        return [v async for v in callbacks['on_run']('Question?', entries, table, None, web.LIVE,
            'Sample World Index', 'GBP', True, 'market_close')]
    import asyncio
    asyncio.run(collect())
    assert captured == {'series': str(series), 'documents': [{'path': str(benchmark_doc), 'date': '2026-09-01'}],
                        'name': 'Sample World Index', 'currency': 'GBP', 'confirmed': True,
                        'pricing_point': 'market_close'}


def test_selected_supporting_documents_reach_review(tmp_path, monkeypatch):
    import asyncio
    from fund_performance import web
    files = []
    for name in ('fund', 'extra1', 'extra2'):
        path = tmp_path / f'{name}.docx'
        doc = Document()
        doc.add_paragraph('Fund factsheet and investment objectives')
        doc.save(path)
        files.append(str(path))
    entries = add_files([], [str(ROOT / 'demo/sample_index_fund/prices.csv'), *files])
    table = rows(entries)
    for row, kind in zip(table, [PRICE, FACTSHEET, SUPPORTING, SUPPORTING]):
        row[2] = kind
    callbacks = {fn.name: fn.fn for fn in web.build_ui().fns.values()}
    captured = {}

    async def fake_review(*args, supporting_documents=None):
        captured['supporting'] = supporting_documents
        return web.Outcome('done')

    monkeypatch.setattr(web, 'start_review', fake_review)
    async def collect():
        return [v async for v in callbacks['on_run']('Review', entries, table, None, web.LIVE)]
    asyncio.run(collect())
    assert captured['supporting'] == files[1:]
