"""The exact browser helper reveals one source bar without page scrolling/focus."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from .picker_tabs import reveal_picker_tab_script


def test_restored_active_and_focused_tabs_only_scroll_their_own_bar() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; browser helper needs the Reflex toolchain")
    script = r"""
const assert = require('node:assert/strict');
let changed, resized, focused, frame, disconnected=0;
global.MutationObserver = class {
  constructor(callback){changed=callback} observe(){} disconnect(){disconnected++}
};
global.ResizeObserver = class {
  constructor(callback){resized=callback} observe(){} disconnect(){disconnected++}
};
global.requestAnimationFrame = callback => {frame=callback; return 1};
global.cancelAnimationFrame = () => {};
global.window = {scrollY:137, scrollTo(){throw Error('page scrolled')}};
let active = {getBoundingClientRect:()=>({left:400,right:480})};
const bar = {
  scrollLeft:0, isConnected:true, contains:()=>true,
  getBoundingClientRect:()=>({left:0,right:300}), querySelector:()=>active,
  addEventListener:(event,callback)=>{focused=callback},
  removeEventListener:()=>{focused=null}
};
const other = {scrollLeft:19};
global.document = {getElementById:id=>{assert.equal(id,'picker-tabs-products'); return bar}};
eval(SCRIPT);
frame(); assert.equal(bar.scrollLeft,180); // restored active selection
active = {getBoundingClientRect:()=>({left:-80,right:0})};
changed(); frame(); assert.equal(bar.scrollLeft,100); // changed selection
focused({target:{closest:()=>({getBoundingClientRect:()=>({left:320,right:400})})}});
assert.equal(bar.scrollLeft,200); // keyboard focus remains untouched
assert.equal(other.scrollLeft,19); assert.equal(window.scrollY,137);
bar.isConnected=false; resized(); frame();
assert.equal(disconnected,2); assert.equal(focused,null);
"""
    script = script.replace("SCRIPT", json.dumps(reveal_picker_tab_script("picker-tabs-products")))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
