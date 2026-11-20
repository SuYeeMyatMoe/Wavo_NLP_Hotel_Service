import json
from pathlib import Path
from xml.etree import ElementTree as ET

from streamlit.testing.v1 import AppTest

from hotel import studio
from hotel.metric_ui import metric_markup


def test_metric_escapes_labels_values_and_help():
    markup = metric_markup('<Accuracy "x">', '<script>alert(1)</script>', help='Help <img src=x> & details')
    root = ET.fromstring(markup)
    assert root.attrib['aria-label'] == '<Accuracy "x">'
    assert root.find('dd').text == '<script>alert(1)</script>'
    assert root.find('.//summary').attrib['aria-label'] == 'About <Accuracy "x">'
    assert root.find('.//span[@class="wavo-metric-tooltip"]').text == 'Help <img src=x> & details'
    assert '<script>' not in markup and '<img' not in markup
    assert '<details' not in metric_markup('Count', 0)


def test_evaluation_switch_preserves_scores_and_session_without_native_metrics(monkeypatch):
    report = json.loads((Path(__file__).resolve().parents[1] / 'artifacts/evaluation.json').read_text())
    calls = []

    def request(method, path):
        calls.append((method, path))
        return report

    monkeypatch.setattr(studio, 'request', request)
    # Simulate the native metric widget being unusable. No card may invoke it.
    monkeypatch.setattr(studio.st, 'metric', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Native metric used')))
    ui = AppTest.from_string('from hotel.studio import evaluation\nevaluation()', default_timeout=20)
    ui.session_state.auth = {'access_token': 'test-session'}
    for target in ('urgency', 'department', 'urgency'):
        if ui.selectbox:
            ui.selectbox[0].set_value(target)
        ui.run()
        assert not ui.exception and not ui.metric
        assert ui.session_state.auth == {'access_token': 'test-session'}
        selected = next(r for r in report['targets'][target]['runs'] if r.get('selected'))
        expected = {
            'Accuracy': f"{selected['accuracy']:.3f}",
            'Macro F1': f"{selected['report']['macro avg']['f1-score']:.3f}",
            'Weighted F1': f"{selected['report']['weighted avg']['f1-score']:.3f}",
        }
        cards = [ET.fromstring(e.value) for e in ui.get('html') if 'class="wavo-metric"' in e.value]
        assert {card.attrib['aria-label']: card.find('dd').text for card in cards} == expected
        assert len(ui.dataframe) == 2 and ui.info
    assert calls == [('GET', '/evaluation')] * 3
