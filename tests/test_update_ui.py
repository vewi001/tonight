import shutil
import subprocess
from pathlib import Path

import pytest


def test_update_notice_is_local_dismissible_and_preserves_manual_check():
    if not shutil.which('node'):
        pytest.skip('Node is needed for frontend behavior checks')
    root = Path(__file__).resolve().parents[1]
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const storage = {getItem: () => null, setItem: () => {}, removeItem: () => {}};
const sandbox = {document:{querySelector:()=>({})}, localStorage:storage, sessionStorage:storage,
  location:{hostname:'localhost'}, setTimeout:()=>{}, clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/, ''),sandbox);
vm.runInContext(`state.update={phase:'available',available_version:'1.6.5',total_bytes:1048576,install_supported:true,message:'Доступно обновление 1.6.5'}`,sandbox);
let html = vm.runInContext('updateControls()', sandbox);
assert(html.includes('Скачать и обновить') && html.includes('Не сейчас'));
vm.runInContext(`state.updateDismissed='1.6.5'`,sandbox);
assert.equal(vm.runInContext('updateControls()',sandbox),'');
assert(vm.runInContext('updateControls(true)',sandbox).includes('Проверить обновления'));
vm.runInContext(`state.update.phase='downloading'; state.update.download_bytes=524288`,sandbox);
html=vm.runInContext('updateControls()',sandbox);
assert(html.includes('50%') && html.includes('Загрузка обновления'));
sandbox.location.hostname='192.168.1.10';
assert.equal(vm.runInContext('updateControls(true)',sandbox),'');
sandbox.location.hostname='localhost';
vm.runInContext(`api=async()=>({phase:'downloading',current_version:'1.6.4'}); updateNotice=()=>{}; refreshUpdateStatus=()=>{}; installUpdate()`,sandbox)
  .then(()=>assert.equal(vm.runInContext('state.updateInstallingFrom',sandbox),'1.6.4'))
  .catch(error=>{console.error(error); process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', script], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
