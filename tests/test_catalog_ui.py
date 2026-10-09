import shutil
import subprocess
from pathlib import Path
import pytest


def test_catalog_ui_counts_states_permissions_and_escaping():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,
location:{hostname:'localhost'},setTimeout:()=>{},clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`state.catalog={summary:{movie_count:12,local_poster_count:8,trailer_link_count:7,poster_and_trailer_count:5,catalog_version:null,last_successful_update:null},update:{phase:'idle'}}`,sandbox);
let html=vm.runInContext('catalogPanel()',sandbox);
for(const text of ['12','8','7','5','Пакет ещё не установлен','Обновлений пакетом ещё не было','Доступность видео не проверена']) assert(html.includes(text),text);
vm.runInContext(`state.catalog.update={phase:'available',available_version:'1.0.0',total_bytes:1048576,message:'<img onerror=bad>'}`,sandbox);
html=vm.runInContext('catalogPanel()',sandbox);
assert(html.includes('Обновить каталог') && html.includes('&lt;img') && !html.includes('<img onerror'));
vm.runInContext(`state.catalog.update.phase='downloading'; state.catalog.update.download_bytes=524288`,sandbox);
html=vm.runInContext('catalogPanel()',sandbox);
assert(html.includes('50%') && html.includes('disabled') && !html.includes('Каталог обновлён'));
vm.runInContext(`state.catalog.update.phase='recovery_error'`,sandbox);
assert(vm.runInContext('catalogPanel()',sandbox).includes('Повторить восстановление'));
sandbox.location.hostname='192.168.1.20';
assert.equal(vm.runInContext('catalogPanel()',sandbox),'');
assert(!vm.runInContext('shell("test")',sandbox).includes('data-view="catalog"'));
sandbox.location.hostname='localhost';
assert(vm.runInContext('shell("test")',sandbox).includes('data-view="catalog"'));
vm.runInContext(`state.update={phase:'available',available_version:'1.6.6',install_supported:true}`,sandbox);
assert(vm.runInContext('updateControls(true)',sandbox).includes('Обновить приложение'));
'''
    result = subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_catalog_navigation_wraps_inside_small_windows():
    import re
    styles = (Path(__file__).resolve().parents[1]/'frontend/styles.css').read_text(encoding='utf-8')
    for selector in ('topbar','top-actions'):
        rule = re.search(r'\.'+selector+r'\s*\{([^}]+)\}',styles)
        assert rule and 'flex-wrap:wrap' in rule[1]
