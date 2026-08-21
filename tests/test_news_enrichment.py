import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# El entorno de prueba no necesita la librería completa dateparser: para estas
# pruebas basta un parser ISO mínimo que permita importar main.py.
dateparser_mod = types.ModuleType('dateparser')

def _parse_date(value, languages=None, settings=None):
    if not value:
        return None
    text = str(value).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None

dateparser_mod.parse = _parse_date
search_mod = types.ModuleType('dateparser.search')
search_mod.search_dates = lambda *args, **kwargs: None
sys.modules.setdefault('dateparser', dateparser_mod)
sys.modules.setdefault('dateparser.search', search_mod)

import yaml
from bs4 import BeautifulSoup
import main


class FakeResponse:
    def __init__(self, html: str, url: str = 'https://medio.test/noticia'):
        self.content = html.encode('utf-8')
        self.url = url


class FakeHttp:
    def __init__(self, html: str):
        self.html = html
        self.calls = []

    def get(self, url: str):
        self.calls.append(url)
        return FakeResponse(self.html, url)


class NewsQualityTests(unittest.TestCase):
    def test_clean_news_text_keeps_a_useful_long_summary(self):
        text = ' '.join(
            f'Párrafo informativo número {i} con datos del partido, protagonistas, resultado y contexto deportivo relevante.'
            for i in range(1, 15)
        )
        cleaned = main.clean_news_text(text, 'Título distinto')
        self.assertGreaterEqual(len(cleaned), 750)
        self.assertLessEqual(len(cleaned), 1150)

    def test_article_metadata_prefers_article_body_and_keeps_multiple_paragraphs(self):
        paragraphs = ''.join(
            f'<p>Párrafo {i}: Bolívar prepara su partido internacional con información concreta sobre jugadores, '
            f'el rival, el estadio y la planificación del cuerpo técnico para el encuentro decisivo.</p>'
            for i in range(1, 8)
        )
        html = f'''<html><head>
          <meta property="article:published_time" content="2026-08-21T12:00:00+00:00">
          <meta property="og:image" content="/media/partido.jpg">
          <meta property="og:description" content="Descripción breve que no debe ganar al cuerpo del artículo.">
        </head><body><article>{paragraphs}</article></body></html>'''
        detail = main._article_metadata(FakeHttp(html), 'https://medio.test/noticia', 'Bolívar prepara su partido')
        self.assertTrue(detail['image_url'].endswith('/media/partido.jpg'))
        self.assertGreaterEqual(len(detail['summary']), 750)
        self.assertIn('Párrafo 6', detail['summary'])

    def test_enrichment_runs_when_image_or_text_is_missing_even_if_date_exists(self):
        item = main.Item(
            id='1', kind='news', title='Bolívar gana un partido importante', text='Texto corto.',
            url='https://medio.test/noticia', image_url='', published_at='2026-08-21T12:00:00Z',
            source_id='medio', source_name='Medio', source_type='media', source_authority=0.9,
        )
        detail = {
            'published_at': '2026-08-21T12:00:00Z',
            'summary': ' '.join(['Contenido deportivo detallado y verificable.'] * 30),
            'image_url': 'https://medio.test/foto.jpg',
        }
        with patch.object(main, '_article_metadata', return_value=detail) as metadata:
            main._enrich_missing_news(FakeHttp(''), [item], {'id': 'medio', 'url': 'https://medio.test', 'source_type': 'media'}, limit=10)
        metadata.assert_called_once()
        self.assertEqual(item.image_url, 'https://medio.test/foto.jpg')
        self.assertGreater(len(item.text), 500)

    def test_visible_news_feed_requires_a_real_image(self):
        common = dict(
            kind='news', published_at='2026-08-21T12:00:00Z', source_type='media',
            source_authority=0.9, scope='bolivia', competition='general', rank_score=0.9,
            text='Bolívar consiguió una victoria importante en un partido de la liga profesional y sumó puntos claves. ' * 5,
        )
        with_image = main.Item(id='img', title='Bolívar consigue una victoria importante', image_url='https://medio.test/foto.jpg', source_id='a', source_name='A', **common)
        without_image = main.Item(id='noimg', title='The Strongest prepara su próximo partido', image_url='', source_id='b', source_name='B', **common)
        feed = main.build_app_feed([with_image, without_image], 20)
        ids = [row['id'] for row in feed['items']]
        self.assertEqual(ids, ['img'])

    def test_feed_caps_one_source_so_it_cannot_dominate(self):
        items = []
        for i in range(40):
            items.append(main.Item(
                id=f'a{i}', kind='news', title=f'Bolívar partido importante número {i}',
                text='Resultado, partido, victoria, liga, jugadores y contexto deportivo. ' * 5,
                image_url=f'https://a.test/{i}.jpg', published_at='2026-08-21T12:00:00Z',
                source_id='a', source_name='A', source_type='media', source_authority=0.9,
                scope='bolivia', competition='general', rank_score=0.9,
            ))
        for i in range(10):
            items.append(main.Item(
                id=f'b{i}', kind='news', title=f'The Strongest noticia deportiva número {i}',
                text='Resultado, partido, victoria, liga, jugadores y contexto deportivo. ' * 5,
                image_url=f'https://b.test/{i}.jpg', published_at='2026-08-21T11:00:00Z',
                source_id='b', source_name='B', source_type='media', source_authority=0.9,
                scope='bolivia', competition='general', rank_score=0.88,
            ))
        feed = main.build_app_feed(items, 100, source_cap=30)
        ids = [row['id'] for row in feed['items']]
        self.assertEqual(sum(x.startswith('a') for x in ids), 30)
        self.assertEqual(sum(x.startswith('b') for x in ids), 10)

    def test_heading_fallback_extracts_media_cards_without_article_tag(self):
        html = '''<html><body><div class="listing-item">
          <img src="/foto.jpg"><h2><a href="/deportes/bolivar-gana">Bolívar gana y sube en la tabla</a></h2>
          <p>La Academia venció en un partido intenso y sumó tres puntos importantes en la División Profesional.</p>
          <time datetime="2026-08-21T10:30:00Z">21 agosto 2026</time>
        </div></body></html>'''
        soup = BeautifulSoup(html, 'lxml')
        source = {
            'id': 'medio_nuevo', 'name': 'Medio Nuevo', 'source_type': 'media', 'authority': 0.85,
            'scope': 'bolivia', 'competition': 'general', 'news_link_fallback': True,
        }
        items = main.extract_news_cards(soup, source, 'https://medio.test/deportes')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, 'Bolívar gana y sube en la tabla')
        self.assertEqual(items[0].image_url, 'https://medio.test/foto.jpg')

    def test_sources_yaml_adds_eleven_verified_news_sources(self):
        cfg = yaml.safe_load(Path('sources.yaml').read_text(encoding='utf-8'))
        ids = {s['id'] for s in cfg['web_sources']}
        expected = {
            'eldeber_deportes', 'lostiempos_deportes', 'opinion_futbol_boliviano',
            'erbol_deporte', 'correodelsur_deporte', 'larazon_futbol_boliviano',
            'vision360_futbol_boliviano', 'oxigeno_deportes', 'atb_deportes',
            'abi_deportes', 'redpat_deportes',
        }
        self.assertTrue(expected.issubset(ids))
        self.assertEqual(len(cfg['web_sources']), 42)


if __name__ == '__main__':
    unittest.main()
