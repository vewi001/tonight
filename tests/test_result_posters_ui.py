"""The shared result and its confirmation keep a real, immediately loaded poster."""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


class Images(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.images = []
        self.placeholders = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'img':
            self.images.append(attributes)
        if attributes.get('role') == 'img':
            self.placeholders.append(attributes)


@pytest.fixture(scope='module')
def screens():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs = require('fs'), vm = require('vm');
const storage = {getItem:()=>null,setItem:()=>{}};
const sandbox = {document:{querySelector:()=>({})},localStorage:storage,
  sessionStorage:storage,location:{hostname:'localhost'}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`shell=html=>html;
state.user='lera';
const main={id:'main',title:'Багровая легенда',year:2019,runtime:90,genres:['мультфильм'],
  overview:'Описание фильма',rating:8,match:95,poster_available:true,
  poster_url:'/api/movies/main/poster?v=123&source=local',
  backdrop_url:'/api/movies/main/backdrop?v=fallback-2',backdrop_available:false};
state.session={id:1,status:'recommended',recommendations:[main],selected:main,viewing_company:'couple'};`,sandbox);
const results={};
for (const view of ['Results','Selected']) {
  results[view]={available:vm.runInContext('render'+view+'()',sandbox)};
  vm.runInContext('main.poster_available=false',sandbox);
  results[view].missing=vm.runInContext('render'+view+'()',sandbox);
  vm.runInContext('main.poster_available=true; main.poster_url=""',sandbox);
  results[view].noUrl=vm.runInContext('render'+view+'()',sandbox);
  vm.runInContext('main.poster_url="/api/movies/main/poster?v=123&source=local"',sandbox);
}
console.log(JSON.stringify(results));
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('screen', ['Results', 'Selected'])
def test_real_poster_is_present_without_a_backdrop_and_loads_immediately(screens, screen):
    images = Images(screens[screen]['available']).images
    poster = next((image for image in images if image.get('src') == '/api/movies/main/poster?v=123&source=local'), None)
    assert poster is not None, 'The chosen film must keep its poster even without a backdrop'
    assert poster['alt'] == 'Постер: Багровая легенда'
    assert poster.get('loading') == 'eager', 'The primary image must not wait for lazy-load intersection'


@pytest.mark.parametrize('screen', ['Results', 'Selected'])
@pytest.mark.parametrize('case', ['missing', 'noUrl'])
def test_missing_poster_has_an_explicit_placeholder(screens, screen, case):
    rendered = Images(screens[screen][case])
    assert rendered.placeholders
    assert not any(image.get('src', '').startswith('/api/movies/main/poster') for image in rendered.images)


def test_result_does_not_enlarge_placeholder_art_as_a_backdrop(screens):
    assert not any('/backdrop' in image.get('src', '') for image in Images(screens['Results']['available']).images)


def test_cached_poster_does_not_require_a_cached_backdrop(tmp_path, monkeypatch):
    from PIL import Image
    from backend.movies.catalog import get_movie
    import backend.movies.media as media

    monkeypatch.setattr(media, 'ROOT', tmp_path)
    poster = tmp_path / 'data/posters/arrival.jpg'
    poster.parent.mkdir(parents=True)
    with Image.new('RGB', (20, 30), 'red') as image:
        image.save(poster)
    movie = get_movie('arrival')
    assert movie['poster_available'] is True
    assert movie['backdrop_available'] is False
    backdrop = tmp_path / 'data/backdrops/arrival.jpg'
    backdrop.parent.mkdir()
    with Image.new('RGB', (32, 18), 'blue') as image:
        image.save(backdrop)
    assert get_movie('arrival')['backdrop_available'] is True
